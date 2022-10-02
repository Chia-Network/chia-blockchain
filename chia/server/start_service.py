import asyncio
import functools
import os
import logging
import logging.config
import signal
import sys
from typing import Any, Callable, Coroutine, Dict, Generic, List, Optional, Tuple, Type, TypeVar

from chia.daemon.server import service_launch_lock_path
from chia.util.lock import Lockfile, LockfileError
from chia.server.ssl_context import chia_ssl_ca_paths, private_ssl_ca_paths
from ..protocols.shared_protocol import capabilities

try:
    import uvloop
except ImportError:
    uvloop = None

from chia.cmds.init_funcs import chia_full_version_str
from chia.rpc.rpc_server import RpcApiProtocol, RpcServiceProtocol, start_rpc_server, RpcServer
from chia.server.outbound_message import NodeType
from chia.server.server import ChiaServer
from chia.server.upnp import UPnP
from chia.types.peer_info import PeerInfo
from chia.util.setproctitle import setproctitle
from chia.util.ints import uint16

from .reconnect_task import start_reconnect_task


# this is used to detect whether we are running in the main process or not, in
# signal handlers. We need to ignore signals in the sub processes.
main_pid: Optional[int] = None

T = TypeVar("T")
_T_RpcServiceProtocol = TypeVar("_T_RpcServiceProtocol", bound=RpcServiceProtocol)

RpcInfo = Tuple[Type[RpcApiProtocol], int]


class ServiceException(Exception):
    pass


class Service(Generic[_T_RpcServiceProtocol]):
    def __init__(
        self,
        root_path,
        node: _T_RpcServiceProtocol,
        peer_api: Any,
        node_type: NodeType,
        advertised_port: int,
        service_name: str,
        network_id: str,
        *,
        config: Dict[str, Any],
        upnp_ports: List[int] = [],
        server_listen_ports: List[int] = [],
        connect_peers: List[PeerInfo] = [],
        on_connect_callback: Optional[Callable] = None,
        rpc_info: Optional[RpcInfo] = None,
        connect_to_daemon=True,
        max_request_body_size: Optional[int] = None,
        override_capabilities: Optional[List[Tuple[uint16, str]]] = None,
    ) -> None:
        self.root_path = root_path
        self.config = config
        ping_interval = self.config.get("ping_interval")
        self.self_hostname = self.config.get("self_hostname")
        self.daemon_port = self.config.get("daemon_port")
        assert ping_interval is not None
        self._connect_to_daemon = connect_to_daemon
        self._node_type = node_type
        self._service_name = service_name
        self.rpc_server: Optional[RpcServer] = None
        self._rpc_close_task: Optional[asyncio.Task] = None
        self._network_id: str = network_id
        self.max_request_body_size = max_request_body_size

        self._log = logging.getLogger(service_name)
        self._log.info(f"chia-blockchain version: {chia_full_version_str()}")

        self.service_config = self.config[service_name]

        self._rpc_info = rpc_info
        private_ca_crt, private_ca_key = private_ssl_ca_paths(root_path, self.config)
        chia_ca_crt, chia_ca_key = chia_ssl_ca_paths(root_path, self.config)
        inbound_rlp = self.config.get("inbound_rate_limit_percent")
        outbound_rlp = self.config.get("outbound_rate_limit_percent")
        if node_type == NodeType.WALLET:
            inbound_rlp = self.service_config.get("inbound_rate_limit_percent", inbound_rlp)
            outbound_rlp = 60
        capabilities_to_use: List[Tuple[uint16, str]] = capabilities
        if override_capabilities is not None:
            capabilities_to_use = override_capabilities

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
            capabilities_to_use,
            root_path,
            self.service_config,
            (private_ca_crt, private_ca_key),
            (chia_ca_crt, chia_ca_key),
            name=f"{service_name}_server",
        )
        f = getattr(node, "set_server", None)
        if f:
            f(self._server)
        else:
            self._log.warning(f"No set_server method for {service_name}")

        self._upnp_ports = upnp_ports
        self._server_listen_ports = server_listen_ports

        self._api = peer_api
        self._node = node
        self._did_start = False
        self._is_stopping = asyncio.Event()
        self._stopped_by_rpc = False

        self._on_connect_callback = on_connect_callback
        self._advertised_port = advertised_port
        self._reconnect_tasks: Dict[PeerInfo, Optional[asyncio.Task]] = {peer: None for peer in connect_peers}
        self.upnp: UPnP = UPnP()

    async def start(self) -> None:
        # TODO: move those parameters to `__init__`
        if self._did_start:
            return None

        assert self.self_hostname is not None
        assert self.daemon_port is not None

        self._did_start = True

        await self._node._start()
        self._node._shut_down = False

        if len(self._upnp_ports) > 0:
            self.upnp.setup()

            for port in self._upnp_ports:
                self.upnp.remap(port)

        await self._server.start_server(self.config.get("prefer_ipv6", False), self._on_connect_callback)
        self._advertised_port = self._server.get_port()

        for peer in self._reconnect_tasks.keys():
            self.add_peer(peer)

        self._log.info(f"Started {self._service_name} service on network_id: {self._network_id}")

        self._rpc_close_task = None
        if self._rpc_info:
            rpc_api, rpc_port = self._rpc_info
            self.rpc_server = await start_rpc_server(
                rpc_api(self._node),
                self.self_hostname,
                self.daemon_port,
                uint16(rpc_port),
                self.stop,
                self.root_path,
                self.config,
                self._connect_to_daemon,
                max_request_body_size=self.max_request_body_size,
            )

    async def run(self) -> None:
        try:
            with Lockfile.create(service_launch_lock_path(self.root_path, self._service_name), timeout=1):
                await self.start()
                await self.wait_closed()
        except LockfileError as e:
            self._log.error(f"{self._service_name}: already running")
            raise ValueError(f"{self._service_name}: already running") from e

    def add_peer(self, peer: PeerInfo) -> None:
        if self._reconnect_tasks.get(peer) is not None:
            raise ServiceException(f"Peer {peer} already added")

        self._reconnect_tasks[peer] = start_reconnect_task(
            self._server, peer, self._log, self.config.get("prefer_ipv6")
        )

    async def setup_process_global_state(self) -> None:
        # Being async forces this to be run from within an active event loop as is
        # needed for the signal handler setup.
        proctitle_name = f"chia_{self._service_name}"
        setproctitle(proctitle_name)

        global main_pid
        main_pid = os.getpid()
        if sys.platform == "win32" or sys.platform == "cygwin":
            # pylint: disable=E1101
            signal.signal(signal.SIGBREAK, self._accept_signal)
            signal.signal(signal.SIGINT, self._accept_signal)
            signal.signal(signal.SIGTERM, self._accept_signal)
        else:
            loop = asyncio.get_running_loop()
            loop.add_signal_handler(
                signal.SIGINT,
                functools.partial(self._accept_signal, signal_number=signal.SIGINT),
            )
            loop.add_signal_handler(
                signal.SIGTERM,
                functools.partial(self._accept_signal, signal_number=signal.SIGTERM),
            )

    def _accept_signal(self, signal_number: int, stack_frame=None):
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
                self.upnp.release(port)

            self._log.info("Cancelling reconnect task")
            for task in self._reconnect_tasks.values():
                if task is not None:
                    task.cancel()
            self._reconnect_tasks.clear()
            self._log.info("Closing connections")
            self._server.close_all()
            self._node._close()
            self._node._shut_down = True

            self._log.info("Calling service stop callback")

            if self.rpc_server is not None:
                self._log.info("Closing RPC server")
                self.rpc_server.close()

    async def wait_closed(self) -> None:
        await self._is_stopping.wait()

        self._log.info("Waiting for socket to be closed (if opened)")

        self._log.info("Waiting for ChiaServer to be closed")
        await self._server.await_closed()

        if self.rpc_server:
            self._log.info("Waiting for RPC server")
            await self.rpc_server.await_closed()
            self._log.info("Closed RPC server")

        self._log.info("Waiting for service _await_closed callback")
        await self._node._await_closed()

        # this is a blocking call, waiting for the UPnP thread to exit
        self.upnp.shutdown()

        self._did_start = False
        self._is_stopping.clear()
        self._log.info(f"Service {self._service_name} at port {self._advertised_port} fully closed")


def async_run(coro: Coroutine[object, object, T]) -> T:
    if uvloop is not None:
        uvloop.install()
    return asyncio.run(coro)
