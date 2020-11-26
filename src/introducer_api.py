from typing import Optional

from src.introducer import Introducer
from src.server.outbound_message import Message
from src.server.ws_connection import WSChiaConnection
from src.types.peer_info import TimestampedPeerInfo
from src.util.api_decorators import api_request
from src.util.ints import uint64
from src.protocols.introducer_protocol import RespondPeers, RequestPeers


class IntroducerAPI:
    introducer: Introducer

    def __init__(self, introducer):
        self.introducer = introducer

    @api_request
    async def request_peers_with_peer_info(
        self,
        request: RequestPeers,
        peer: WSChiaConnection,
    ) -> Optional[Message]:
        max_peers = self.introducer.max_peers_to_send
        if (
            self.introducer.server is None
            or self.introducer.server.introducer_peers is None
        ):
            return None
        rawpeers = self.introducer.server.introducer_peers.get_peers(
            max_peers * 5, True, self.introducer.recent_peer_threshold
        )

        peers = []
        for r_peer in rawpeers:
            if r_peer.get_hash() not in self.introducer.vetted:
                continue
            if self.introducer.vetted[r_peer.get_hash()]:
                if (
                    r_peer.host == peer.peer_host
                    and r_peer.port == peer.peer_server_port
                ):
                    continue
                peer_without_timestamp = TimestampedPeerInfo(
                    r_peer.host,
                    r_peer.port,
                    uint64(0),
                )
                peers.append(peer_without_timestamp)

            if len(peers) >= max_peers:
                break

        self.introducer.log.info(f"Sending vetted {peers}")

        msg = Message("respond_peers", RespondPeers(peers))
        return msg
