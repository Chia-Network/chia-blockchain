import signal
from typing import Any, Dict
from aiohttp import web
import asyncio
from aiohttp.web_app import Application
from chia.rpc.full_node_rpc_client import FullNodeRpcClient


class SpendbundleServer:
    app: Application
    shut_down: bool
    shut_down_event: asyncio.Event
    log: Any
    full_node_rpc: FullNodeRpcClient

    @staticmethod
    async def create_web_server(chia_config: Dict[str, Any], root_path):
        self = SpendbundleServer()

        self.shut_down = False
        self.shut_down_event = asyncio.Event()
        self.app = web.Application()

        routes = []
        self.app.add_routes(routes)
        asyncio.get_running_loop().add_signal_handler(signal.SIGINT, self.stop_all)
        asyncio.get_running_loop().add_signal_handler(signal.SIGTERM, self.stop_all)

        self_hostname = chia_config["self_hostname"]
        rpc_port = chia_config["full_node"]["rpc_port"]
        self.full_node_rpc = await FullNodeRpcClient.create(self_hostname, rpc_port, root_path, chia_config)

        return self

    def stop_all(self):
        self.shut_down = True
        asyncio.ensure_future(self.app.shutdown())
        asyncio.ensure_future(self.app.cleanup())
        self.shut_down_event.set()

    async def run(self):
        runner = web.AppRunner(self.app, access_log=None)
        await runner.setup()
        site = web.TCPSite(runner, None, 4001)
        await site.start()


async def run_wallet_server(config, root_path):
    server: SpendbundleServer = await SpendbundleServer.create_web_server(chia_config=config, root_path=root_path)
    await server.run()
    await server.shut_down_event.wait()
