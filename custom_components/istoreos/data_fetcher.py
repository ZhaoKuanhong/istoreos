"""iStoreOS client using the uhttpd ubus JSON-RPC 2.0 API."""

import asyncio
import logging
from urllib.parse import urlsplit

import aiohttp

_LOGGER = logging.getLogger(__name__)
_ANONYMOUS = "0" * 32


class RouterError(Exception):
    """The router did not return a usable RPC response."""


class AuthenticationError(RouterError):
    """The router rejected the credentials."""


class UbusError(RouterError):
    """A JSON-RPC or ubus method failed."""

    def __init__(self, object_name, method, code):
        self.code = code
        super().__init__(f"ubus {object_name}.{method} failed (code {code})")


class DataFetcher:
    def __init__(self, host, username, password, session=None):
        base = host.strip().rstrip("/")
        if "://" not in base:
            base = f"http://{base}"
        parsed = urlsplit(base)
        if (parsed.scheme not in ("http", "https") or not parsed.hostname
                or parsed.username or parsed.password or parsed.query
                or parsed.fragment or parsed.path not in ("", "/ubus")):
            raise ValueError("Enter a router hostname or http(s)://host[:port], without a LuCI path")
        self._url = f"{parsed.scheme}://{parsed.netloc}/ubus"
        self._username = username
        self._password = password
        self._owns_session = session is None
        self._session = session if session is not None else aiohttp.ClientSession()
        self._token = None
        self._request_id = 0
        self._login_lock = asyncio.Lock()

    async def _request(self, token, object_name, method, arguments):
        self._request_id += 1
        request_id = self._request_id
        payload = {
            "jsonrpc": "2.0", "id": request_id, "method": "call",
            "params": [token, object_name, method, arguments],
        }
        async with self._session.post(
            self._url, json=payload, timeout=aiohttp.ClientTimeout(total=15),
            allow_redirects=False,
        ) as resp:
            if resp.status != 200:
                raise RouterError(
                    f"/ubus returned HTTP {resp.status}; check the router address "
                    "and uhttpd-mod-ubus configuration"
                )
            try:
                data = await resp.json()
            except (aiohttp.ContentTypeError, ValueError) as err:
                raise RouterError("/ubus returned invalid JSON; check uhttpd-mod-ubus") from err
        if (not isinstance(data, dict) or data.get("jsonrpc") != "2.0"
                or data.get("id") != request_id):
            raise RouterError("Invalid ubus JSON-RPC response")
        if data.get("error"):
            error = data["error"]
            raise UbusError(object_name, method, error.get("code") if isinstance(error, dict) else None)
        result = data.get("result")
        if not isinstance(result, list) or not result or type(result[0]) is not int:
            raise RouterError("Invalid ubus result")
        if result[0] != 0:
            raise UbusError(object_name, method, result[0])
        body = result[1] if len(result) > 1 else {}
        if not isinstance(body, dict):
            raise RouterError("Invalid ubus result data")
        return body

    async def login(self):
        self._token = None
        try:
            data = await self._request(_ANONYMOUS, "session", "login", {
                "username": self._username, "password": self._password, "timeout": 300,
            })
        except UbusError as err:
            if err.code in (6, -32002):
                raise AuthenticationError("Router rejected the username or password") from err
            raise
        token = data.get("ubus_rpc_session")
        if not isinstance(token, str) or len(token) != 32 or token == _ANONYMOUS:
            raise AuthenticationError("Router did not return an authenticated session")
        self._token = token

    async def call(self, object_name, method, arguments=None):
        async with self._login_lock:
            if not self._token:
                await self.login()
            token = self._token
        try:
            return await self._request(token, object_name, method, arguments or {})
        except UbusError as err:
            if err.code not in (6, -32001, -32002):
                raise
        # Reauthenticate once, including when a router reboot invalidated the session.
        async with self._login_lock:
            if self._token == token:
                await self.login()
        return await self._request(self._token, object_name, method, arguments or {})

    async def _optional_call(self, object_name, method, arguments=None):
        try:
            return await self.call(object_name, method, arguments)
        except UbusError as err:
            if err.code not in (3, 4, 6, -32000, -32002):
                raise
            _LOGGER.debug("Optional router metric unavailable: %s", err)
            return {}

    async def get_firmware_version(self):
        board = await self.call("system", "board")
        release = board.get("release", {})
        return release.get("description") or release.get("version") or "未知版本"

    async def fetch_status(self):
        info = await self.call("system", "info")
        result = {}
        uptime = int(info.get("uptime", 0))
        days, seconds = divmod(uptime, 86400)
        hours, seconds = divmod(seconds, 3600)
        minutes = seconds // 60
        result.update({
            "uptime_raw": str(uptime), "uptime_days": days,
            "uptime_hours": hours, "uptime_minutes": minutes,
            "uptime_human": f"{days} 天 {hours} 小时" if days else f"{hours} 小时 {minutes} 分钟",
        })
        load = info.get("load", [])
        if len(load) == 3:
            values = [round(value / 65536, 2) for value in load]
            result.update(zip(("load_1min", "load_5min", "load_15min"), values))
            result["load_summary"] = " / ".join(str(value) for value in values)

        # system.info reports bytes; retain the existing KiB and MiB sensor values.
        memory = info.get("memory", {})
        total = memory.get("total", 0)
        if total > 0:
            free = memory.get("free", 0)
            available = memory.get("available", free)
            used = max(0, total - available)
            percent = round(used / total * 100, 2)
            for key, value in {"total": total, "used": used, "free": free, "available": available}.items():
                result[f"mem_{key}"] = value / 1024
                result[f"mem_{key}_mb"] = round(value / 1024**2, 1)
            result["mem_used_percent"] = percent
            result["mem_summary"] = f"{result['mem_used_mb']} MB / {result['mem_total_mb']} MB ({percent}%)"

        wan = await self._optional_call("network.interface.wan", "status")
        addresses = wan.get("ipv4-address", [])
        result["wan_ip"] = addresses[0].get("address") if addresses else None
        # Preserve the old metric's meaning: complete IPv4 ARP entries on br-lan.
        arp = await self._optional_call("file", "read", {"path": "/proc/net/arp"})
        result["online_devices"] = None
        if isinstance(arp.get("data"), str):
            result["online_devices"] = sum(
                1 for line in arp["data"].splitlines()[1:]
                if len(fields := line.split()) >= 6 and fields[2] == "0x2" and fields[5] == "br-lan"
            )
        connections = await self._optional_call("file", "read", {
            "path": "/proc/sys/net/netfilter/nf_conntrack_count",
        })
        count = connections.get("data", "").strip()
        result["connections"] = int(count) if count.isdigit() else None
        return result

    async def reboot(self):
        await self.call("system", "reboot")

    async def reconnect_wan(self):
        await self.call("network.interface.wan", "down")
        await self.call("network.interface.wan", "up")

    async def close(self):
        if self._owns_session:
            await self._session.close()
