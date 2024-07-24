from __future__ import annotations

import asyncio
import contextlib
import logging
import logging.config
import os
import signal
from pathlib import Path
from types import FrameType
from typing import (
    Any,
    AsyncIterator,
    Awaitable,
    Callable,
    Coroutine,
    Dict,
    Generic,
    List,
    Optional,
    Set,
    Tuple,
    Type,
    TypeVar,
    cast,
)

from chia.daemon.server import service_launch_lock_path
from chia.rpc.rpc_server import RpcApiProtocol, RpcServer, RpcServiceProtocol, start_rpc_server
from chia.server.api_protocol import ApiProtocol
from chia.server.chia_policy import set_chia_policy
from chia.server.outbound_message import NodeType
from chia.server.server import ChiaServer
from chia.server.signal_handlers import SignalHandlers
from chia.server.ssl_context import chia_ssl_ca_paths, private_ssl_ca_paths
from chia.server.upnp import UPnP
from chia.server.ws_connection import WSChiaConnection
from chia.types.peer_info import PeerInfo, UnresolvedPeerInfo
from chia.util.ints import uint16
from chia.util.lock import Lockfile, LockfileError
from chia.util.log_exceptions import log_exceptions
from chia.util.network import resolve
from chia.util.setproctitle import setproctitle

from ..protocols.shared_protocol import default_capabilities
from ..util.chia_version import chia_short_version

# this is used to detect whether we are running in the main process or not, in
# signal handlers. We need to ignore signals in the sub processes.
main_pid: Optional[int] = None

T = TypeVar("T")
_T_RpcServiceProtocol = TypeVar("_T_RpcServiceProtocol", bound=RpcServiceProtocol)
_T_ApiProtocol = TypeVar("_T_ApiProtocol", bound=ApiProtocol)
_T_RpcApiProtocol = TypeVar("_T_RpcApiProtocol", bound=RpcApiProtocol)

RpcInfo = Tuple[Type[_T_RpcApiProtocol], int]

log = logging.getLogger(__name__)


class ServiceException(Exception):
    pass


class Service(Generic[_T_RpcServiceProtocol, _T_ApiProtocol, _T_RpcApiProtocol]):
    def __init__(
        self,
        root_path: Path,
        node: _T_RpcServiceProtocol,
        peer_api: _T_ApiProtocol,
        node_type: NodeType,
        advertised_port: Optional[int],
        service_name: str,
        network_id: str,
        *,
        config: Dict[str, Any],
        upnp_ports: Optional[List[int]] = None,
        connect_peers: Optional[Set[UnresolvedPeerInfo]] = None,
        on_connect_callback: Optional[Callable[[WSChiaConnection], Awaitable[None]]] = None,
        rpc_info: Optional[RpcInfo[_T_RpcApiProtocol]] = None,
        connect_to_daemon: bool = True,
        max_request_body_size: Optional[int] = None,
        override_capabilities: Optional[List[Tuple[uint16, str]]] = None,
    ) -> None:
        if upnp_ports is None:
            upnp_ports = []

        if connect_peers is None:
            connect_peers = set()

        self.root_path = root_path
        self.config = config
        ping_interval = self.config.get("ping_interval")
        self.self_hostname = cast(str, self.config.get("self_hostname"))
        self.daemon_port = self.config.get("daemon_port")
        assert ping_interval is not None
        self._connect_to_daemon = connect_to_daemon
        self._node_type = node_type
        self._service_name = service_name
        self.rpc_server: Optional[RpcServer[_T_RpcApiProtocol]] = None
        self._network_id: str = network_id
        self.max_request_body_size = max_request_body_size
        self.reconnect_retry_seconds: int = 3

        self._log = logging.getLogger(service_name)
        self._log.info(f"Starting service {self._service_name} ...")
        self._log.info(f"chia-blockchain version: {chia_short_version()}")

        self.service_config = self.config[service_name]

        self._rpc_info = rpc_info
        private_ca_crt, private_ca_key = private_ssl_ca_paths(root_path, self.config)
        chia_ca_crt, chia_ca_key = chia_ssl_ca_paths(root_path, self.config)
        inbound_rlp = self.config.get("inbound_rate_limit_percent")
        outbound_rlp = self.config.get("outbound_rate_limit_percent")
        if node_type == NodeType.WALLET:
            inbound_rlp = self.service_config.get("inbound_rate_limit_percent", inbound_rlp)
            outbound_rlp = 60
        capabilities_to_use: List[Tuple[uint16, str]] = default_capabilities[node_type]
        if override_capabilities is not None:
            capabilities_to_use = override_capabilities

        assert inbound_rlp and outbound_rlp
        self._server = ChiaServer.create(
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

        self._api = peer_api
        self._node = node
        self._stopped_by_rpc = False

        self._on_connect_callback = on_connect_callback
        self._advertised_port = advertised_port
        self._connect_peers = connect_peers
        self._connect_peers_task: Optional[asyncio.Task[None]] = None
        self.upnp: UPnP = UPnP()
        self.stop_requested = asyncio.Event()

    async def _connect_peers_task_handler(self) -> None:
        resolved_peers: Dict[UnresolvedPeerInfo, PeerInfo] = {}
        prefer_ipv6 = self.config.get("prefer_ipv6", False)
        while True:
            for unresolved in self._connect_peers:
                resolved = resolved_peers.get(unresolved)
                if resolved is None:
                    try:
                        resolved = PeerInfo(await resolve(unresolved.host, prefer_ipv6=prefer_ipv6), unresolved.port)
                    except Exception as e:
                        self._log.warning(f"Failed to resolve {unresolved.host}: {e}")
                        continue
                    self._log.info(f"Add resolved {resolved}")
                    resolved_peers[unresolved] = resolved

                if any(connection.peer_info == resolved for connection in self._server.all_connections.values()):
                    continue
                if any(
                    connection.peer_info.host == resolved.host and connection.peer_server_port == resolved.port
                    for connection in self._server.all_connections.values()
                ):
                    continue

                if not await self._server.start_client(resolved, None):
                    self._log.info(f"Failed to connect to {resolved}")
                    # Re-resolve to make sure the IP didn't change, this helps for example to keep dyndns hostnames
                    # up to date.
                    try:
                        resolved_new = PeerInfo(
                            await resolve(unresolved.host, prefer_ipv6=prefer_ipv6), unresolved.port
                        )
                    except Exception as e:
                        self._log.warning(f"Failed to resolve after connection failure {unresolved.host}: {e}")
                        continue
                    if resolved_new != resolved:
                        self._log.info(f"Host {unresolved.host} changed from {resolved} to {resolved_new}")
                        resolved_peers[unresolved] = resolved_new
            await asyncio.sleep(self.reconnect_retry_seconds)

    async def run(self) -> None:
        try:
            with Lockfile.create(service_launch_lock_path(self.root_path, self._service_name), timeout=1):
                async with self.manage():
                    await self.stop_requested.wait()
        except LockfileError as e:
            self._log.error(f"{self._service_name}: already running")
            raise ValueError(f"{self._service_name}: already running") from e

    @contextlib.asynccontextmanager
    async def manage(self, *, start: bool = True) -> AsyncIterator[None]:
        # NOTE: avoid start=False, this is presently used for corner case setup type tests
        async with contextlib.AsyncExitStack() as async_exit_stack:
            try:
                if start:
                    self.stop_requested = asyncio.Event()

                    assert self.self_hostname is not None
                    assert self.daemon_port is not None

                    await async_exit_stack.enter_async_context(self._node.manage())
                    self._node._shut_down = False

                    if len(self._upnp_ports) > 0:
                        async_exit_stack.enter_context(self.upnp.manage(self._upnp_ports))

                    await self._server.start(
                        prefer_ipv6=self.config.get("prefer_ipv6", False),
                        on_connect=self._on_connect_callback,
                    )
                    try:
                        self._advertised_port = self._server.get_port()
                    except ValueError:
                        pass

                    self._connect_peers_task = asyncio.create_task(self._connect_peers_task_handler())

                    self._log.info(
                        f"Started {self._service_name} service on network_id: {self._network_id} "
                        f"at port {self._advertised_port}"
                    )

                    if self._rpc_info:
                        rpc_api, rpc_port = self._rpc_info
                        self.rpc_server = await start_rpc_server(
                            rpc_api(self._node),
                            self.self_hostname,
                            self.daemon_port,
                            uint16(rpc_port),
                            self.stop_requested.set,
                            self.root_path,
                            self.config,
                            self._connect_to_daemon,
                            max_request_body_size=self.max_request_body_size,
                        )
                yield
            finally:
                self._log.info(f"Stopping service {self._service_name} at port {self._advertised_port} ...")

                # start with UPnP, since this can take a while, we want it to happen
                # in the background while shutting down everything else
                for port in self._upnp_ports:
                    self.upnp.release(port)

                self._log.info("Cancelling reconnect task")
                if self._connect_peers_task is not None:
                    self._connect_peers_task.cancel()
                self._log.info("Closing connections")
                self._server.close_all()

                if self.rpc_server is not None:
                    self._log.info("Closing RPC server")
                    self.rpc_server.close()

                self._log.info("Waiting for socket to be closed (if opened)")

                self._log.info("Waiting for ChiaServer to be closed")
                await self._server.await_closed()

                if self.rpc_server:
                    self._log.info("Waiting for RPC server")
                    await self.rpc_server.await_closed()
                    self._log.info("Closed RPC server")

                self._log.info(f"Service {self._service_name} at port {self._advertised_port} fully stopped")

    def add_peer(self, peer: UnresolvedPeerInfo) -> None:
        self._connect_peers.add(peer)

    async def setup_process_global_state(self, signal_handlers: SignalHandlers) -> None:
        # Being async forces this to be run from within an active event loop as is
        # needed for the signal handler setup.
        proctitle_name = f"chia_{self._service_name}"
        setproctitle(proctitle_name)

        global main_pid
        main_pid = os.getpid()
        signal_handlers.setup_sync_signal_handler(handler=self._accept_signal)

    def _accept_signal(
        self,
        signal_: signal.Signals,
        stack_frame: Optional[FrameType],
        loop: asyncio.AbstractEventLoop,
    ) -> None:
        # we only handle signals in the main process. In the ProcessPoolExecutor
        # processes, we have to ignore them. We'll shut them down gracefully
        # from the main process
        global main_pid
        ignore = os.getpid() != main_pid

        # TODO: if we remove this conditional behavior, consider moving logging to common signal handling
        if ignore:
            message = "ignoring in worker process"
        else:
            message = "shutting down"

        self._log.info("Received signal %s (%s), %s.", signal_.name, signal_.value, message)

        if ignore:
            return

        self.stop_requested.set()


def async_run(coro: Coroutine[object, object, T], connection_limit: Optional[int] = None) -> T:
    with log_exceptions(log=log, message="fatal uncaught exception"):
        if connection_limit is not None:
            set_chia_policy(connection_limit)
        return asyncio.run(coro)
