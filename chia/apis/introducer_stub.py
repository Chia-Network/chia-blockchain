from __future__ import annotations

import logging
from typing import TYPE_CHECKING, ClassVar, Optional, cast

if TYPE_CHECKING:
    from chia.server.api_protocol import ApiProtocol

# Minimal imports to avoid circular dependencies
from chia.protocols.introducer_protocol import RequestPeersIntroducer
from chia.protocols.outbound_message import Message
from chia.server.api_protocol import ApiMetadata
from chia.server.ws_connection import WSChiaConnection


class IntroducerApiStub:
    """Non-functional API stub for IntroducerAPI to break circular dependencies.

    This is a protocol definition only - methods are not implemented and should
    never be called. Use the actual IntroducerAPI implementation at runtime.
    """

    if TYPE_CHECKING:
        _protocol_check: ClassVar[ApiProtocol] = cast("IntroducerApiStub", None)

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
    ) -> Optional[Message]:
        """Handle request for peers from a node."""
        ...
