"""Exercise the real HTTP client against a local ubus test server."""

import importlib.util
from pathlib import Path
import unittest

from aiohttp import web, ClientSession

spec = importlib.util.spec_from_file_location(
    "data_fetcher", Path(__file__).parents[1] / "custom_components/istoreos/data_fetcher.py"
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
DataFetcher = module.DataFetcher


class UbusClientTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.requests = []
        self.logins = 0
        self.mode = "normal"
        self.sid = "a" * 32
        app = web.Application()
        app.router.add_post("/ubus", self.handle)
        self.runner = web.AppRunner(app)
        await self.runner.setup()
        site = web.TCPSite(self.runner, "127.0.0.1", 0)
        await site.start()
        port = site._server.sockets[0].getsockname()[1]
        self.client = DataFetcher(f"127.0.0.1:{port}", "root", "test-password")

    async def asyncTearDown(self):
        await self.client.close()
        await self.runner.cleanup()

    async def handle(self, request):
        body = await request.json()
        self.requests.append(body)
        self.assertEqual(body['jsonrpc'], '2.0')
        self.assertEqual(body['method'], 'call')
        sid, obj, method, args = body['params']
        if self.mode == 'html':
            return web.Response(text='<html>not found</html>', status=404, content_type='text/html')
        if self.mode == 'invalid_json':
            return web.Response(text='not JSON', content_type='application/json')
        if self.mode == 'wrong_id':
            return web.json_response({'jsonrpc':'2.0', 'id':-1, 'result':[0, {}]})
        if obj == 'session':
            self.logins += 1
            self.assertEqual(sid, '0' * 32)
            self.assertEqual(args['username'], 'root')
            self.assertEqual(args['password'], 'test-password')
            if self.mode == 'bad_password':
                result = [6]
            elif self.mode == 'missing_token':
                result = [0, {}]
            else:
                result = [0, {'ubus_rpc_session': self.sid}]
        elif sid != self.sid:
            if self.mode == 'json_expiry':
                return web.json_response({'jsonrpc':'2.0','id':body['id'], 'error':{'code':-32001,'message':'Session not found'}})
            result = [6]
        elif self.mode == 'denied' and obj == 'system':
            result = [6]
        elif self.mode == 'missing_files' and obj == 'file':
            result = [4]
        elif self.mode == 'rpc_error':
            return web.json_response({'jsonrpc':'2.0','id':body['id'],'error':{'code':-32602,'message':'Invalid params'}})
        else:
            data = {
                ('system', 'info'): {'uptime': 90061, 'load':[65536,32768,0], 'memory': {'total': 1024**3,'free':128*1024**2,'available':512*1024**2}},
                ('system', 'board'): {'release':{'description':'iStoreOS test'}},
                ('network.interface.wan', 'status'): {'ipv4-address':[{'address':'203.0.113.1'}]},
            }.get((obj, method), {})
            if obj == 'file':
                data = {'data': '42\n'} if 'nf_conntrack' in args['path'] else {'data': 'IP address HW type Flags HW address Mask Device\n192.0.2.1 0x1 0x2 aa:bb:cc:dd:ee:01 * br-lan\n192.0.2.2 0x1 0x0 aa:bb:cc:dd:ee:02 * br-lan\n192.0.2.3 0x1 0x2 aa:bb:cc:dd:ee:03 * eth1\n'}
            result = [0, data]
        return web.json_response({'jsonrpc':'2.0', 'id':body['id'], 'result':result})

    async def test_status_units_and_all_metrics(self):
        result = await self.client.fetch_status()
        self.assertEqual(result['load_1min'], 1.0)
        self.assertEqual(result['load_5min'], 0.5)
        self.assertEqual(result['mem_total_mb'], 1024)
        self.assertEqual(result['mem_used_mb'], 512)
        self.assertEqual(result['mem_used_percent'], 50)
        self.assertEqual(result['uptime_human'], '1 天 1 小时')
        self.assertEqual(result['wan_ip'], '203.0.113.1')
        self.assertEqual(result['online_devices'], 1)
        self.assertEqual(result['connections'], 42)
        self.assertEqual(self.logins, 1)
        self.assertEqual(await self.client.get_firmware_version(), 'iStoreOS test')

    async def test_expired_session_reauthenticates(self):
        await self.client.login()
        self.sid = 'b' * 32
        await self.client.call('system', 'info')
        self.assertEqual(self.logins, 2)

    async def test_json_rpc_session_expiry(self):
        await self.client.login()
        self.sid = 'b' * 32
        self.mode = 'json_expiry'
        await self.client.call('system', 'info')
        self.assertEqual(self.logins, 2)

    async def test_denied_acl_retries_only_once(self):
        self.mode = 'denied'
        with self.assertRaises(module.UbusError):
            await self.client.call('system', 'info')
        self.assertEqual(self.logins, 2)

    async def test_bad_password(self):
        self.mode = 'bad_password'
        with self.assertRaises(module.AuthenticationError):
            await self.client.fetch_status()
        self.assertEqual(self.logins, 1)

    async def test_missing_token(self):
        self.mode = 'missing_token'
        with self.assertRaises(module.AuthenticationError):
            await self.client.login()

    async def test_http_404_is_actionable(self):
        self.mode = 'html'
        with self.assertRaisesRegex(module.RouterError, 'HTTP 404'):
            await self.client.login()

    async def test_invalid_json(self):
        self.mode = 'invalid_json'
        with self.assertRaisesRegex(module.RouterError, 'invalid JSON'):
            await self.client.login()

    async def test_wrong_response_id(self):
        self.mode = 'wrong_id'
        with self.assertRaisesRegex(module.RouterError, 'Invalid ubus JSON-RPC'):
            await self.client.login()

    async def test_optional_metrics_missing(self):
        self.mode = 'missing_files'
        result = await self.client.fetch_status()
        self.assertIsNone(result['online_devices'])
        self.assertIsNone(result['connections'])
        self.assertEqual(result['load_1min'], 1)

    async def test_rpc_error(self):
        self.mode = 'rpc_error'
        with self.assertRaises(module.UbusError) as context:
            await self.client.call('system', 'info')
        self.assertEqual(context.exception.code, -32602)

    async def test_buttons_use_ubus_without_shell(self):
        await self.client.reboot()
        await self.client.reconnect_wan()
        self.assertEqual([req['params'][1:3] for req in self.requests], [
            ['session','login'],['system','reboot'],
            ['network.interface.wan','down'],['network.interface.wan','up'],
        ])

    async def test_shared_session_not_closed(self):
        async with ClientSession() as session:
            client = DataFetcher('https://router:8443', 'root', '', session=session)
            await client.close()
            self.assertFalse(session.closed)
            self.assertEqual(client._url, 'https://router:8443/ubus')

    async def test_invalid_hosts(self):
        for host in ('ftp://router', 'http://root:password@router', 'http://router/cgi-bin/luci', 'http://router?x=1'):
            with self.subTest(host=host), self.assertRaises(ValueError):
                DataFetcher(host, 'root', '')


if __name__ == '__main__':
    unittest.main()
