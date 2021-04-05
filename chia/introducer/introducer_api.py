from typing import Callable, Optional

from chia.introducer.introducer import Introducer
from chia.protocols.introducer_protocol import RequestPeersIntroducer, RespondPeersIntroducer
from chia.protocols.protocol_message_types import ProtocolMessageTypes
from chia.server.outbound_message import Message, make_msg
from chia.server.ws_connection import WSChiaConnection
from chia.types.peer_info import TimestampedPeerInfo
from chia.util.api_decorators import api_request, peer_required
from chia.util.ints import uint64


class IntroducerAPI:
    introducer: Introducer

    def __init__(self, introducer):
        self.introducer = introducer

    def _set_state_changed_callback(self, callback: Callable):
        pass

    @peer_required
    @api_request
    async def request_peers_introducer(
        self,
        request: RequestPeersIntroducer,
        peer: WSChiaConnection,
    ) -> Optional[Message]:
        max_peers = self.introducer.max_peers_to_send
        if self.introducer.server is None or self.introducer.server.introducer_peers is None:
            return None
        rawpeers = self.introducer.server.introducer_peers.get_peers(
            max_peers * 5, True, self.introducer.recent_peer_threshold
        )

        peers = []
        for r_peer in rawpeers:
            if r_peer.get_hash() not in self.introducer.vetted:
                continue
            if self.introducer.vetted[r_peer.get_hash()]:
                if r_peer.host == peer.peer_host and r_peer.port == peer.peer_server_port:
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

        msg = make_msg(ProtocolMessageTypes.respond_peers_introducer, RespondPeersIntroducer(peers))
        return msg
