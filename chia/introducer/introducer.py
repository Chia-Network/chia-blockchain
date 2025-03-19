from __future__ import annotations

import asyncio
import contextlib
import logging
import random
import time
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Any, ClassVar, Optional, cast

import dns.asyncresolver
from chia_rs.sized_ints import uint16, uint64

from chia.rpc.rpc_server import StateChangedProtocol, default_get_connections
from chia.server.introducer_peers import VettedPeer
from chia.server.outbound_message import NodeType
from chia.server.server import ChiaServer
from chia.server.ws_connection import WSChiaConnection
from chia.types.peer_info import TimestampedPeerInfo
from chia.util.task_referencer import create_referenced_task


class Introducer:
    if TYPE_CHECKING:
        from chia.rpc.rpc_server import RpcServiceProtocol

        _protocol_check: ClassVar[RpcServiceProtocol] = cast("Introducer", None)

    @property
    def server(self) -> ChiaServer:
        # This is a stop gap until the class usage is refactored such the values of
        # integral attributes are known at creation of the instance.
        if self._server is None:
            raise RuntimeError("server not assigned")

        return self._server

    def __init__(self, max_peers_to_send: int, recent_peer_threshold: int, default_port: int, dns_servers: list[str]):
        self.max_peers_to_send = max_peers_to_send
        self.recent_peer_threshold = recent_peer_threshold
        self.default_port = uint16(default_port)
        self.dns_servers = dns_servers
        self.resolver = dns.asyncresolver.Resolver()
        self._shut_down = False
        self._server: Optional[ChiaServer] = None
        self.log = logging.getLogger(__name__)

    @contextlib.asynccontextmanager
    async def manage(self) -> AsyncIterator[None]:
        self._vetting_task = create_referenced_task(self._vetting_loop())
        try:
            yield
        finally:
            self._shut_down = True
            self._vetting_task.cancel()
            # await self._vetting_task

    async def on_connect(self, peer: WSChiaConnection) -> None:
        pass

    def _set_state_changed_callback(self, callback: StateChangedProtocol) -> None:
        # TODO: fill this out?
        pass

    def get_connections(self, request_node_type: Optional[NodeType]) -> list[dict[str, Any]]:
        return default_get_connections(server=self.server, request_node_type=request_node_type)

    def set_server(self, server: ChiaServer):
        self._server = server

    async def _vetting_loop(self):
        while True:
            if self._shut_down:
                return None
            try:
                for i in range(60):
                    if self._shut_down:
                        return None
                    await asyncio.sleep(1)
                self.log.info("Vetting random peers.")
                if self._server.introducer_peers is None:
                    continue
                raw_peers = self.server.introducer_peers.get_peers(100, True, 3 * self.recent_peer_threshold)

                if len(raw_peers) == 0:
                    continue

                peer: VettedPeer
                for peer in raw_peers:
                    if self._shut_down:
                        return None

                    now = time.time()

                    # if it was too long ago we checked this peer, check it
                    # again
                    if peer.vetted > 0 and now > peer.vetted_timestamp + 3600:
                        peer.vetted = 0

                    if peer.vetted > 0:
                        continue

                    # don't re-vet peers too frequently
                    if now < peer.last_attempt + 500:
                        continue

                    try:
                        peer.last_attempt = uint64(time.time())

                        self.log.info(f"Vetting peer {peer.host} {peer.port}")
                        _r, w = await asyncio.wait_for(
                            asyncio.open_connection(peer.host, int(peer.port)),
                            timeout=3,
                        )
                        w.close()
                    except Exception as e:
                        self.log.warning(f"Could not vet {peer}, removing. {type(e)}{e!s}")
                        peer.vetted = min(peer.vetted - 1, -1)

                        # if we have failed 6 times in a row, remove the peer
                        if peer.vetted < -6:
                            self.server.introducer_peers.remove(peer)
                        continue

                    self.log.info(f"Have vetted {peer} successfully!")
                    peer.vetted_timestamp = uint64(time.time())
                    peer.vetted = max(peer.vetted + 1, 1)
            except Exception as e:
                self.log.error(e)

    async def get_peers_from_dns(self, num_peers: int) -> list[TimestampedPeerInfo]:
        if len(self.dns_servers) == 0:
            return []

        peers: list[TimestampedPeerInfo] = []
        dns_address = random.choice(self.dns_servers)
        for rdtype in ("A", "AAAA"):
            result = await self.resolver.resolve(qname=dns_address, rdtype=rdtype, lifetime=30)
            for ip in result:
                peers.append(
                    TimestampedPeerInfo(
                        ip.to_text(),
                        self.default_port,
                        uint64(0),
                    )
                )
            if len(peers) > num_peers:
                break

        return peers
