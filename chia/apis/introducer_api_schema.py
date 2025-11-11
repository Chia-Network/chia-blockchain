from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, Optional, cast

from chia.protocols.introducer_protocol import RequestPeersIntroducer
from chia.protocols.outbound_message import Message
from chia.server.api_protocol import ApiMetadata, ApiSchemaProtocol
from chia.server.ws_connection import WSChiaConnection


class IntroducerApiSchema:
    if TYPE_CHECKING:
        _protocol_check: ApiSchemaProtocol = cast("IntroducerApiSchema", None)

    metadata: ClassVar[ApiMetadata] = ApiMetadata()

    @metadata.request(peer_required=True)
    async def request_peers_introducer(
        self,
        request: RequestPeersIntroducer,
        peer: WSChiaConnection,
    ) -> Optional[Message]: ...
