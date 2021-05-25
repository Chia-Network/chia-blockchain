import asyncio
import os
import logging
import logging.config
import signal
from sys import platform
from typing import Any, Callable, List, Optional, Tuple

from chia.server.ssl_context import chia_ssl_ca_paths, private_ssl_ca_paths

try:
    import uvloop
except ImportError:
    uvloop = None

from chia.rpc.rpc_server import start_rpc_server
from chia.server.outbound_message import NodeType
from chia.server.server import ChiaServer
from chia.server.upnp import UPnP
from chia.types.peer_info import PeerInfo
from chia.util.chia_logging import initialize_logging
from chia.util.config import load_config, load_config_cli
from chia.util.setproctitle import setproctitle
from chia.util.ints import uint16

from .reconnect_task import start_reconnect_task


# this is used to detect whether we are running in the main process or not, in
# signal handlers. We need to ignore signals in the sub processes.
main_pid: Optional[int] = None


class Service:
    def __init__(
        self,
        root_path,
        node: Any,
        peer_api: Any,
        node_type: NodeType,
        advertised_port: int,
        service_name: str,
        network_id: str,
        upnp_ports: List[int] = [],
        server_listen_ports: List[int] = [],
        connect_peers: List[PeerInfo] = [],
        auth_connect_peers: bool = True,
        on_connect_callback: Optional[Callable] = None,
        rpc_info: Optional[Tuple[type, int]] = None,
        parse_cli_args=True,
        connect_to_daemon=True,
    ) -> None:
        self.root_path = root_path
        self.config = load_config(root_path, "config.yaml")
        ping_interval = self.config.get("ping_interval")
        self.self_hostname = self.config.get("self_hostname")
        self.daemon_port = self.config.get("daemon_port")
        assert ping_interval is not None
        self._connect_to_daemon = connect_to_daemon
        self._node_type = node_type
        self._service_name = service_name
        self._rpc_task: Optional[asyncio.Task] = None
        self._rpc_close_task: Optional[asyncio.Task] = None
        self._network_id: str = network_id

        proctitle_name = f"chia_{service_name}"
        setproctitle(proctitle_name)
        self._log = logging.getLogger(service_name)

        if parse_cli_args:
            service_config = load_config_cli(root_path, "config.yaml", service_name)
        else:
            service_config = load_config(root_path, "config.yaml", service_name)
        initialize_logging(service_name, service_config["logging"], root_path)

        self._rpc_info = rpc_info
        private_ca_crt, private_ca_key = private_ssl_ca_paths(root_path, self.config)
        chia_ca_crt, chia_ca_key = chia_ssl_ca_paths(root_path, self.config)
        inbound_rlp = self.config.get("inbound_rate_limit_percent")
        outbound_rlp = self.config.get("outbound_rate_limit_percent")
        assert inbound_rlp and outbound_rlp
        self._server = ChiaServer(
            advertised_port,
            node,
            peer_api,
            node_type,
            ping_interval,
            network_id,
            inbound_rlp,
            outbound_rlp,
            root_path,
            service_config,
            (private_ca_crt, private_ca_key),
            (chia_ca_crt, chia_ca_key),
            name=f"{service_name}_server",
        )
        f = getattr(node, "set_server", None)
        if f:
            f(self._server)
        else:
            self._log.warning(f"No set_server method for {service_name}")

        self._connect_peers = connect_peers
        self._auth_connect_peers = auth_connect_peers
        self._upnp_ports = upnp_ports
        self._server_listen_ports = server_listen_ports

        self._api = peer_api
        self._node = node
        self._did_start = False
        self._is_stopping = asyncio.Event()
        self._stopped_by_rpc = False

        self._on_connect_callback = on_connect_callback
        self._advertised_port = advertised_port
        self._reconnect_tasks: List[asyncio.Task] = []
        self.upnp: Optional[UPnP] = None

    async def start(self, **kwargs) -> None:
        # we include `kwargs` as a hack for the wallet, which for some
        # reason allows parameters to `_start`. This is serious BRAIN DAMAGE,
        # and should be fixed at some point.
        # TODO: move those parameters to `__init__`
        if self._did_start:
            return None

        assert self.self_hostname is not None
        assert self.daemon_port is not None

        self._did_start = True

        self._enable_signals()

        await self._node._start(**kwargs)

        for port in self._upnp_ports:
            if self.upnp is None:
                self.upnp = UPnP()

            self.upnp.remap(port)

        await self._server.start_server(self._on_connect_callback)

        self._reconnect_tasks = [
            start_reconnect_task(self._server, _, self._log, self._auth_connect_peers) for _ in self._connect_peers
        ]
        self._log.info(f"Started {self._service_name} service on network_id: {self._network_id}")

        self._rpc_close_task = None
        if self._rpc_info:
            rpc_api, rpc_port = self._rpc_info
            self._rpc_task = asyncio.create_task(
                start_rpc_server(
                    rpc_api(self._node),
                    self.self_hostname,
                    self.daemon_port,
                    uint16(rpc_port),
                    self.stop,
                    self.root_path,
                    self.config,
                    self._connect_to_daemon,
                )
            )

    async def run(self) -> None:
        await self.start()
        await self.wait_closed()

    def _enable_signals(self) -> None:

        global main_pid
        main_pid = os.getpid()
        signal.signal(signal.SIGINT, self._accept_signal)
        signal.signal(signal.SIGTERM, self._accept_signal)
        if platform == "win32" or platform == "cygwin":
            # pylint: disable=E1101
            signal.signal(signal.SIGBREAK, self._accept_signal)  # type: ignore

    def _accept_signal(self, signal_number: int, stack_frame):
        self._log.info(f"got signal {signal_number}")

        # we only handle signals in the main process. In the ProcessPoolExecutor
        # processes, we have to ignore them. We'll shut them down gracefully
        # from the main process
        global main_pid
        if os.getpid() != main_pid:
            return
        self.stop()

    def stop(self) -> None:
        if not self._is_stopping.is_set():
            self._is_stopping.set()

            # start with UPnP, since this can take a while, we want it to happen
            # in the background while shutting down everything else
            for port in self._upnp_ports:
                if self.upnp is not None:
                    self.upnp.release(port)

            self._log.info("Cancelling reconnect task")
            for _ in self._reconnect_tasks:
                _.cancel()
            self._log.info("Closing connections")
            self._server.close_all()
            self._node._close()
            self._node._shut_down = True

            self._log.info("Calling service stop callback")

            if self._rpc_task is not None:
                self._log.info("Closing RPC server")

                async def close_rpc_server() -> None:
                    if self._rpc_task:
                        await (await self._rpc_task)()

                self._rpc_close_task = asyncio.create_task(close_rpc_server())

    async def wait_closed(self) -> None:
        await self._is_stopping.wait()

        self._log.info("Waiting for socket to be closed (if opened)")

        self._log.info("Waiting for ChiaServer to be closed")
        await self._server.await_closed()

        if self._rpc_close_task:
            self._log.info("Waiting for RPC server")
            await self._rpc_close_task
            self._log.info("Closed RPC server")

        self._log.info("Waiting for service _await_closed callback")
        await self._node._await_closed()

        if self.upnp is not None:
            # this is a blocking call, waiting for the UPnP thread to exit
            self.upnp.shutdown()

        self._log.info(f"Service {self._service_name} at port {self._advertised_port} fully closed")


async def async_run_service(*args, **kwargs) -> None:
    service = Service(*args, **kwargs)
    return await service.run()


def run_service(*args, **kwargs) -> None:
    if uvloop is not None:
        uvloop.install()
    return asyncio.run(async_run_service(*args, **kwargs))
