import asyncio
import logging
import logging.config
import signal

from sys import platform
from typing import Any, Callable, List, Optional, Tuple

try:
    import uvloop
except ImportError:
    uvloop = None

from src.server.outbound_message import NodeType
from src.server.server import ChiaServer, start_server
from src.types.peer_info import PeerInfo
from src.util.logging import initialize_logging
from src.util.config import load_config, load_config_cli
from src.util.setproctitle import setproctitle
from src.rpc.rpc_server import start_rpc_server
from src.server.connection import OnConnectFunc

from .reconnect_task import start_reconnect_task


stopped_by_signal = False


def global_signal_handler(*args):
    global stopped_by_signal
    stopped_by_signal = True


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
        auth_connect_peers: bool = True,
        on_connect_callback: Optional[OnConnectFunc] = None,
        rpc_info: Optional[Tuple[type, int]] = None,
        start_callback: Optional[Callable] = None,
        stop_callback: Optional[Callable] = None,
        await_closed_callback: Optional[Callable] = None,
        parse_cli_args=True,
    ):
        net_config = load_config(root_path, "config.yaml")
        ping_interval = net_config.get("ping_interval")
        network_id = net_config.get("network_id")
        self.self_hostname = net_config.get("self_hostname")
        self.daemon_port = net_config.get("daemon_port")
        assert ping_interval is not None
        assert network_id is not None

        self._node_type = node_type
        self._service_name = service_name

        proctitle_name = f"chia_{service_name}"
        setproctitle(proctitle_name)
        self._log = logging.getLogger(service_name)
        if parse_cli_args:
            config = load_config_cli(root_path, "config.yaml", service_name)
        else:
            config = load_config(root_path, "config.yaml", service_name)
        initialize_logging(service_name, config["logging"], root_path)

        self._rpc_info = rpc_info

        self._server = ChiaServer(
            advertised_port,
            api,
            node_type,
            ping_interval,
            network_id,
            root_path,
            config,
            name=f"{service_name}_server",
        )
        for _ in ["set_server", "_set_server"]:
            f = getattr(api, _, None)
            if f:
                f(self._server)

        self._connect_peers = connect_peers
        self._auth_connect_peers = auth_connect_peers
        self._server_listen_ports = server_listen_ports

        self._api = api
        self._task = None
        self._is_stopping = False
        self._stopped_by_rpc = False

        self._on_connect_callback = on_connect_callback
        self._start_callback = start_callback
        self._stop_callback = stop_callback
        self._await_closed_callback = await_closed_callback
        self._advertised_port = advertised_port
        self._server_sockets: List = []

    def start(self):
        if self._task is not None:
            return

        async def _run():
            if self._start_callback:
                await self._start_callback()

            self._rpc_task = None
            self._rpc_close_task = None
            if self._rpc_info:
                rpc_api, rpc_port = self._rpc_info

                self._rpc_task = asyncio.create_task(
                    start_rpc_server(
                        rpc_api(self._api),
                        self.self_hostname,
                        self.daemon_port,
                        rpc_port,
                        self.stop,
                    )
                )

            self._reconnect_tasks = [
                start_reconnect_task(
                    self._server, _, self._log, self._auth_connect_peers
                )
                for _ in self._connect_peers
            ]
            self._server_sockets = [
                await start_server(self._server, self._on_connect_callback)
                for _ in self._server_listen_ports
            ]

            signal.signal(signal.SIGINT, global_signal_handler)
            signal.signal(signal.SIGTERM, global_signal_handler)
            if platform == "win32" or platform == "cygwin":
                # pylint: disable=E1101
                signal.signal(signal.SIGBREAK, global_signal_handler)  # type: ignore

        self._task = asyncio.create_task(_run())

    async def run(self):
        self.start()
        await self._task
        while not stopped_by_signal and not self._is_stopping:
            await asyncio.sleep(1)

        self.stop()
        await self.wait_closed()
        return 0

    def stop(self):
        if not self._is_stopping:
            self._is_stopping = True
            self._log.info("Closing server sockets")
            for _ in self._server_sockets:
                _.close()
            self._log.info("Cancelling reconnect task")
            for _ in self._reconnect_tasks:
                _.cancel()
            self._log.info("Closing connections")
            self._server.close_all()
            self._api._shut_down = True

            self._log.info("Calling service stop callback")
            if self._stop_callback:
                self._stop_callback()

            if self._rpc_task:
                self._log.info("Closing RPC server")

                async def close_rpc_server():
                    await (await self._rpc_task)()

                self._rpc_close_task = asyncio.create_task(close_rpc_server())

    async def wait_closed(self):
        self._log.info("Waiting for socket to be closed (if opened)")
        for _ in self._server_sockets:
            await _.wait_closed()

        self._log.info("Waiting for ChiaServer to be closed")
        await self._server.await_closed()

        if self._rpc_close_task:
            self._log.info("Waiting for RPC server")
            await self._rpc_close_task
            self._log.info("Closed RPC server")

        if self._await_closed_callback:
            self._log.info("Waiting for service _await_closed callback")
            await self._await_closed_callback()
        self._log.info(
            f"Service {self._service_name} at port {self._advertised_port} fully closed"
        )


async def async_run_service(*args, **kwargs):
    service = Service(*args, **kwargs)
    return await service.run()


def run_service(*args, **kwargs):
    if uvloop is not None:
        uvloop.install()
    return asyncio.run(async_run_service(*args, **kwargs))
