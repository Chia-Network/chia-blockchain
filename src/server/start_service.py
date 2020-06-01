import asyncio
import logging
import logging.config
import signal

from typing import Any, AsyncGenerator, Callable, List, Optional

try:
    import uvloop
except ImportError:
    uvloop = None

from src.server.server import ChiaServer, start_server
from src.server.outbound_message import OutboundMessage
from src.server.connection import NodeType
from src.types.peer_info import PeerInfo
from src.util.logging import initialize_logging
from src.util.config import load_config_cli, load_config
from src.util.setproctitle import setproctitle

from .reconnect_task import start_reconnect_task

OutboundMessageGenerator = AsyncGenerator[OutboundMessage, None]


class Service:
    def __init__(
        self,
        root_path,
        api: Any,
        node_type: NodeType,
        advertised_port: int,
        service_name: str,
        server_listen_ports: List[int] = [],
        connect_peers: List[PeerInfo] = [],
        on_connect_callback: Optional[OutboundMessage] = None,
        start_callback: Optional[Callable] = None,
        stop_callback: Optional[Callable] = None,
        await_closed_callback: Optional[Callable] = None,
    ):
        net_config = load_config(root_path, "config.yaml")
        ping_interval = net_config.get("ping_interval")
        network_id = net_config.get("network_id")
        assert ping_interval is not None
        assert network_id is not None

        self._node_type = node_type

        proctitle_name = f"chia_{service_name}"
        setproctitle(proctitle_name)
        self._log = logging.getLogger(service_name)

        config = load_config_cli(root_path, "config.yaml", service_name)
        initialize_logging(f"{service_name:<30s}", config["logging"], root_path)

        self._server = ChiaServer(
            config["port"],
            api,
            node_type,
            ping_interval,
            network_id,
            root_path,
            config,
        )
        for _ in ["set_server", "_set_server"]:
            f = getattr(api, _, None)
            if f:
                f(self._server)

        self._connect_peers = connect_peers
        self._server_listen_ports = server_listen_ports

        self._api = api
        self._task = None
        self._is_stopping = False

        self._on_connect_callback = on_connect_callback
        self._start_callback = start_callback
        self._stop_callback = stop_callback
        self._await_closed_callback = await_closed_callback

    def start(self):
        if self._task is not None:
            return

        async def _run():
            if self._start_callback:
                self._start_callback()
            self._reconnect_tasks = [
                start_reconnect_task(self._server, _, self._log)
                for _ in self._connect_peers
            ]
            self._server_sockets = [
                await start_server(self._server, self._on_connect_callback)
                for _ in self._server_listen_ports
            ]

            try:
                asyncio.get_running_loop().add_signal_handler(signal.SIGINT, self.stop)
                asyncio.get_running_loop().add_signal_handler(signal.SIGTERM, self.stop)
            except NotImplementedError:
                self._log.info("signal handlers unsupported")
            for _ in self._server_sockets:
                await _.wait_closed()
            await self._server.await_closed()

        self._task = asyncio.ensure_future(_run())

    async def run(self):
        self.start()
        await self.wait_closed()
        self._log.info("Closed all node servers.")
        return 0

    def stop(self):
        if not self._is_stopping:
            for _ in self._server_sockets:
                _.close()
            for _ in self._reconnect_tasks:
                _.cancel()
            self._is_stopping = True
            self._server.close_all()
            if self._stop_callback:
                self._stop_callback()

    async def wait_closed(self):
        await self._task
        if self._await_closed_callback:
            await self._await_closed_callback
        self._log.info("%s fully closed", self._node_type)


async def async_run_service(*args, **kwargs):
    service = Service(*args, **kwargs)
    return await service.run()


def run_service(*args, **kwargs):
    if uvloop is not None:
        uvloop.install()
    asyncio.run(async_run_service(*args, **kwargs))
