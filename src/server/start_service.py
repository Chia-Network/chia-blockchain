import asyncio
import logging
import logging.config
import signal

from sys import platform
from typing import Any, List, Optional, Tuple

try:
    import uvloop
except ImportError:
    uvloop = None

from src.server.outbound_message import NodeType
from src.server.server import ChiaServer, start_server
from src.server.upnp import upnp_remap_port
from src.types.peer_info import PeerInfo
from src.util.logging import initialize_logging
from src.util.config import load_config, load_config_cli
from src.util.setproctitle import setproctitle
from src.rpc.rpc_server import start_rpc_server
from src.server.connection import OnConnectFunc

from .reconnect_task import start_reconnect_task
from .ssl_context import load_ssl_paths


class Service:
    def __init__(
        self,
        root_path,
        api: Any,
        node_type: NodeType,
        advertised_port: int,
        service_name: str,
        upnp_ports: List[int] = [],
        server_listen_ports: List[int] = [],
        connect_peers: List[PeerInfo] = [],
        auth_connect_peers: bool = True,
        on_connect_callback: Optional[OnConnectFunc] = None,
        rpc_info: Optional[Tuple[type, int]] = None,
        parse_cli_args=True,
    ):
        config = load_config(root_path, "config.yaml")
        ping_interval = config.get("ping_interval")
        network_id = config.get("network_id")
        self.self_hostname = config.get("self_hostname")
        self.daemon_port = config.get("daemon_port")
        assert ping_interval is not None
        assert network_id is not None

        self._node_type = node_type
        self._service_name = service_name

        proctitle_name = f"chia_{service_name}"
        setproctitle(proctitle_name)
        self._log = logging.getLogger(service_name)
        if parse_cli_args:
            service_config = load_config_cli(root_path, "config.yaml", service_name)
        else:
            service_config = load_config(root_path, "config.yaml", service_name)
        initialize_logging(service_name, service_config["logging"], root_path)

        self._rpc_info = rpc_info

        ssl_cert_path, ssl_key_path = load_ssl_paths(root_path, service_config)

        self._server = ChiaServer(
            advertised_port,
            api,
            node_type,
            ping_interval,
            network_id,
            ssl_cert_path,
            ssl_key_path,
            name=f"{service_name}_server",
        )
        for _ in ["set_server", "_set_server"]:
            f = getattr(api, _, None)
            if f:
                f(self._server)

        self._connect_peers = connect_peers
        self._auth_connect_peers = auth_connect_peers
        self._upnp_ports = upnp_ports
        self._server_listen_ports = server_listen_ports

        self._api = api
        self._did_start = False
        self._is_stopping = asyncio.Event()
        self._stopped_by_rpc = False

        self._on_connect_callback = on_connect_callback
        self._advertised_port = advertised_port
        self._server_sockets: List = []
        self._reconnect_tasks: List[asyncio.Task] = []

    async def start(self, **kwargs):
        # we include `kwargs` as a hack for the wallet, which for some
        # reason allows parameters to `_start`. This is serious BRAIN DAMAGE,
        # and should be fixed at some point.
        # TODO: move those parameters to `__init__`
        if self._did_start:
            return
        self._did_start = True

        self._enable_signals()

        await self._api._start(**kwargs)

        for port in self._upnp_ports:
            upnp_remap_port(port)

        self._server_sockets = [
            await start_server(self._server, self._on_connect_callback)
            for _ in self._server_listen_ports
        ]

        self._reconnect_tasks = [
            start_reconnect_task(self._server, _, self._log, self._auth_connect_peers)
            for _ in self._connect_peers
        ]

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

    async def run(self):
        await self.start()
        await self.wait_closed()

    def _enable_signals(self):
        signal.signal(signal.SIGINT, self._accept_signal)
        signal.signal(signal.SIGTERM, self._accept_signal)
        if platform == "win32" or platform == "cygwin":
            # pylint: disable=E1101
            signal.signal(signal.SIGBREAK, self._accept_signal)  # type: ignore

    def _accept_signal(self, signal_number: int, stack_frame):
        self._log.info(f"got signal {signal_number}")
        self.stop()

    def stop(self):
        if not self._is_stopping.is_set():
            self._is_stopping.set()
            self._log.info("Closing server sockets")
            for _ in self._server_sockets:
                _.close()
            self._log.info("Cancelling reconnect task")
            for _ in self._reconnect_tasks:
                _.cancel()
            self._log.info("Closing connections")
            self._server.close_all()
            self._api._close()
            self._api._shut_down = True

            self._log.info("Calling service stop callback")

            if self._rpc_task:
                self._log.info("Closing RPC server")

                async def close_rpc_server():
                    await (await self._rpc_task)()

                self._rpc_close_task = asyncio.create_task(close_rpc_server())

    async def wait_closed(self):
        await self._is_stopping.wait()

        self._log.info("Waiting for socket to be closed (if opened)")
        for _ in self._server_sockets:
            await _.wait_closed()

        self._log.info("Waiting for ChiaServer to be closed")
        await self._server.await_closed()

        if self._rpc_close_task:
            self._log.info("Waiting for RPC server")
            await self._rpc_close_task
            self._log.info("Closed RPC server")

        self._log.info("Waiting for service _await_closed callback")
        await self._api._await_closed()
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
