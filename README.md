# iStoreOS Router for Home Assistant (ubus edition)

[English](README.md) | [中文](README_zh.md)

Fork of [SJMTIII/istoreos](https://github.com/SJMTIII/istoreos), migrated to the modern **ubus JSON-RPC 2.0 API** at `/ubus`. Version 2.0.0 no longer uses `/cgi-bin/luci/rpc/*` or requires `luci-mod-rpc`.

## Installation / upgrade

1. Add `https://github.com/ZhaoKuanhong/istoreos` to HACS custom repositories, type **Integration**.
2. Install iStoreOS Router and restart Home Assistant.
3. Add the integration in Settings → Devices & services. Enter a hostname/IP (optionally a port), or an `http://` / `https://` base URL, plus the router username and password. Do not enter a `/cgi-bin/luci/...` URL.

If replacing the original HACS repository, remove its HACS repository/download entry first **without deleting the integration configuration**, then install this fork. Both use the same `istoreos` domain and must not be installed side by side. Existing config entries and entity IDs are retained; restarting Home Assistant loads the new implementation. Alternatively, replace `config/custom_components/istoreos/` with this repository's folder and restart.

## Router requirements

The router must expose `/ubus` through uhttpd (`uhttpd-mod-ubus`) and run `rpcd`. The API was confirmed reachable on iStoreOS 24.10.8; authenticated end-to-end testing with this version of the integration is still required. No router settings are changed by installing the integration. HTTPS certificate validation remains enabled.

The login account needs the following ubus permissions:

| Feature | ubus object / methods |
| --- | --- |
| Authentication | `session.login` |
| Uptime, load and memory | `system.info` |
| Firmware | `system.board` |
| WAN IPv4 address | `network.interface.wan.status` |
| Device and connection counts | `file.read` for `/proc/net/arp` and `/proc/sys/net/netfilter/nf_conntrack_count` |
| Reboot button | `system.reboot` |
| Reconnect WAN button | `network.interface.wan.down` and `.up` |

`file.read` also requires matching file read ACLs, and the rpcd file plugin must be available. Optional metrics return unavailable when their method/path is missing or access is denied; system status remains usable. Buttons require write permissions. Use an account already authorized for the desired features; this repository does not grant or expand router access.

## Behavior

- One shared status refresh every 60 seconds; all sensors use the same coordinator data.
- Sessions automatically renew once after expiry. HTTP, JSON-RPC and ubus status errors are checked before parsing metric data. Passwords and session tokens are not logged.
- Memory uses `system.info` byte values, converted to the existing MiB values; used memory is total minus available memory. Load values use the kernel's 16-bit fixed-point scale.
- Online devices retains the original metric: complete IPv4 ARP entries on `br-lan`. This is an estimate, not a DHCP device list or reliable presence detector.
- WAN IP is the IPv4 address assigned to the `wan` interface, which can be private under NAT. There is no external IP lookup fallback.
- Existing buttons now invoke ubus directly, without shell commands. They have only been tested against a local test server; tests do not reboot or disconnect a real router.

For a 404, verify that `/ubus` is enabled and reachable from Home Assistant. A working LuCI browser login alone does not establish that API access is available. Wrong passwords are reported separately from connection failures. Existing entries with changed credentials can be removed and added again.

## Tests

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m unittest discover -s tests -v
```

Tests run against a local aiohttp HTTP server and cover authentication, session expiry, ACL denial, response validation, unit conversions, optional metrics, and button method selection. They do not require Home Assistant or router credentials. A full Home Assistant runtime and authenticated real-router verification are not part of these tests.
