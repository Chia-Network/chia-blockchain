from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator
from concurrent.futures.thread import ThreadPoolExecutor
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar, Optional, cast

from chia_rs import ConsensusConstants, solve_proof
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint64

from chia.protocols.outbound_message import NodeType
from chia.rpc.rpc_server import StateChangedProtocol, default_get_connections
from chia.server.server import ChiaServer
from chia.server.ws_connection import WSChiaConnection

log = logging.getLogger(__name__)


class Solver:
    if TYPE_CHECKING:
        from chia.rpc.rpc_server import RpcServiceProtocol

        _protocol_check: ClassVar[RpcServiceProtocol] = cast("Solver", None)

    root_path: Path
    _server: Optional[ChiaServer]
    _shut_down: bool
    started: bool = False
    executor: ThreadPoolExecutor
    state_changed_callback: Optional[StateChangedProtocol] = None
    constants: ConsensusConstants
    event_loop: asyncio.events.AbstractEventLoop

    @property
    def server(self) -> ChiaServer:
        if self._server is None:
            raise RuntimeError("server not assigned")

        return self._server

    def __init__(self, root_path: Path, config: dict[str, Any], constants: ConsensusConstants):
        self.log = log
        self.root_path = root_path
        self.config = config
        self._shut_down = False
        num_threads = config["num_threads"]
        self.log.info(f"Initializing solver with {num_threads} threads")
        self.executor = ThreadPoolExecutor(max_workers=num_threads, thread_name_prefix="solver-")
        self._server = None
        self.constants = constants
        self.state_changed_callback: Optional[StateChangedProtocol] = None
        self.log.info("Solver initialization complete")

    @contextlib.asynccontextmanager
    async def manage(self) -> AsyncIterator[None]:
        try:
            self.log.info("Starting solver service")
            self.started = True
            self.log.info("Solver service started successfully")
            yield
        finally:
            self.log.info("Shutting down solver service")
            self._shut_down = True
            self.executor.shutdown(wait=True)
            self.log.info("Solver service shutdown complete")

    def solve(self, partial_proof: list[uint64], plot_id: bytes32, strength: int, size: int) -> Optional[bytes]:
        self.log.info(f"Solve request: partial={partial_proof[:5]} plot-id: {plot_id} k: {size}")
        try:
            return solve_proof(partial_proof, plot_id, strength, size)
        except Exception:
            self.log.exception("solve_proof()")
        return None

    def get_connections(self, request_node_type: Optional[NodeType]) -> list[dict[str, Any]]:
        return default_get_connections(server=self.server, request_node_type=request_node_type)

    async def on_connect(self, connection: WSChiaConnection) -> None:
        if self.server.is_trusted_peer(connection, self.config.get("trusted_peers", {})):
            self.log.info(f"Accepting connection from {connection.get_peer_logging()}")
            return
        if not self.config.get("trusted_peers_only", True):
            self.log.info(
                f"trusted peers check disabled, Accepting connection from untrusted {connection.get_peer_logging()}"
            )
            return
        self.log.warning(f"Rejecting untrusted connection from {connection.get_peer_logging()}")
        await connection.close()

    async def on_disconnect(self, connection: WSChiaConnection) -> None:
        self.log.info(f"peer disconnected {connection.get_peer_logging()}")

    def set_server(self, server: ChiaServer) -> None:
        self._server = server

    def _set_state_changed_callback(self, callback: StateChangedProtocol) -> None:
        self.state_changed_callback = callback
