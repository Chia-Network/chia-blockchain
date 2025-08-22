from __future__ import annotations

from typing import Optional

from chia.protocols.introducer_protocol import RequestPeersIntroducer
from chia.protocols.outbound_message import Message
from chia.server.api_protocol import ApiMetadata
from chia.server.ws_connection import WSChiaConnection


class IntroducerApiSchema:
    metadata = ApiMetadata()

    @metadata.request(peer_required=True)
    async def request_peers_introducer(
        self,
        request: RequestPeersIntroducer,
        peer: WSChiaConnection,
    ) -> Optional[Message]: ...
