import asyncio
import logging
import time
from typing import AsyncGenerator, Dict, Optional
from src.types.sized_bytes import bytes32
from src.protocols.introducer_protocol import RespondPeers, RequestPeers
from src.server.connection import PeerConnections
from src.server.outbound_message import Delivery, Message, NodeType, OutboundMessage
from src.server.server import ChiaServer
from src.util.api_decorators import api_request
from src.types.peer_info import PeerInfo, TimestampedPeerInfo
from src.util.ints import uint64

log = logging.getLogger(__name__)


class Introducer:
    def __init__(self, max_peers_to_send: int, recent_peer_threshold: int):
        self.vetted: Dict[bytes32, bool] = {}
        self.vetted_timestamps: Dict[bytes32, int] = {}
        self.max_peers_to_send = max_peers_to_send
        self.recent_peer_threshold = recent_peer_threshold
        self._shut_down = False
        self.server: Optional[ChiaServer] = None

    async def _start(self):
        self._vetting_task = asyncio.create_task(self._vetting_loop())

    def _close(self):
        self._shut_down = True

    async def _await_closed(self):
        await self._vetting_task

    def _set_server(self, server: ChiaServer):
        self.server = server

    async def _vetting_loop(self):
        while True:
            if self._shut_down:
                return
            try:
                log.info("Vetting random peers.")
                if self.global_connections.introducer_peers is None:
                    await asyncio.sleep(3)
                    continue
                rawpeers = self.global_connections.introducer_peers.get_peers(
                    100, True, 3 * self.recent_peer_threshold
                )

                for peer in rawpeers:
                    if self._shut_down:
                        return
                    if peer.get_hash() in self.vetted_timestamps:
                        if time.time() > self.vetted_timestamps[peer.get_hash()] + 3600:
                            if peer.get_hash() in self.vetted:
                                self.vetted[peer.get_hash()] = False
                    if (
                        peer.get_hash() not in self.vetted
                        or not self.vetted[peer.get_hash()]
                    ):
                        try:
                            log.info(f"Vetting peer {peer.host} {peer.port}")
                            r, w = await asyncio.wait_for(
                                asyncio.open_connection(peer.host, int(peer.port)),
                                timeout=3,
                            )
                            w.close()
                        except Exception as e:
                            log.warning(f"Could not vet {peer}. {type(e)}{str(e)}")
                            self.vetted[peer.get_hash()] = False
                            continue

                        log.info(f"Have vetted {peer} successfully!")
                        self.vetted[peer.get_hash()] = True
                        self.vetted_timestamps[peer.get_hash()] = int(time.time())
            except Exception as e:
                log.error(e)
            for i in range(30):
                if self._shut_down:
                    return
                await asyncio.sleep(1)

    def _set_global_connections(self, global_connections: PeerConnections):
        self.global_connections: PeerConnections = global_connections

    @api_request
    async def request_peers_with_peer_info(
        self,
        request: RequestPeers,
        peer_info: PeerInfo,
    ) -> AsyncGenerator[OutboundMessage, None]:
        max_peers = self.max_peers_to_send
        if self.global_connections.introducer_peers is None:
            return
        rawpeers = self.global_connections.introducer_peers.get_peers(
            max_peers * 5, True, self.recent_peer_threshold
        )

        peers = []
        for peer in rawpeers:
            if peer.get_hash() not in self.vetted:
                continue
            if self.vetted[peer.get_hash()]:
                if peer.host == peer_info.host and peer.port == peer_info.port:
                    continue
                peer_without_timestamp = TimestampedPeerInfo(
                    peer.host,
                    peer.port,
                    uint64(0),
                )
                peers.append(peer_without_timestamp)

            if len(peers) >= max_peers:
                break

        log.info(f"Sending vetted {peers}")

        msg = Message("respond_peers", RespondPeers(peers))
        yield OutboundMessage(NodeType.FULL_NODE, msg, Delivery.RESPOND)
        yield OutboundMessage(NodeType.WALLET, msg, Delivery.RESPOND)
