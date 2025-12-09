from __future__ import annotations

import logging
from typing import ClassVar

from typing_extensions import Protocol

from chia.protocols.introducer_protocol import RequestPeersIntroducer
from chia.protocols.outbound_message import Message
from chia.server.api_protocol import ApiMetadata, ApiProtocol
from chia.server.ws_connection import WSChiaConnection


class IntroducerApiStub(ApiProtocol, Protocol):
    """Non-functional API stub for IntroducerAPI

    This is a protocol definition only - methods are not implemented and should
    never be called. Use the actual IntroducerAPI implementation at runtime.
    """

    log: logging.Logger
    metadata: ClassVar[ApiMetadata] = ApiMetadata()

    def ready(self) -> bool:
        """Check if the introducer is ready."""
        ...

    @metadata.request(peer_required=True)
    async def request_peers_introducer(
        self,
        request: RequestPeersIntroducer,
        peer: WSChiaConnection,
    ) -> Message | None:
        """Handle request for peers from a node."""
        ...
