from __future__ import annotations

import logging
from typing import TYPE_CHECKING, ClassVar, Optional, cast

if TYPE_CHECKING:
    from chia.server.api_protocol import ApiProtocol

# Minimal imports to avoid circular dependencies
from chia.protocols import harvester_protocol
from chia.protocols.harvester_protocol import PlotSyncResponse
from chia.protocols.outbound_message import Message
from chia.protocols.protocol_message_types import ProtocolMessageTypes
from chia.server.api_protocol import ApiMetadata
from chia.server.ws_connection import WSChiaConnection


class HarvesterApiStub:
    """Lightweight API stub for HarvesterAPI to break circular dependencies."""

    if TYPE_CHECKING:
        _protocol_check: ClassVar[ApiProtocol] = cast("HarvesterApiStub", None)

    log: logging.Logger
    metadata: ClassVar[ApiMetadata] = ApiMetadata()

    def ready(self) -> bool:
        """Check if the harvester is ready."""
        return True

    @metadata.request(peer_required=True)
    async def harvester_handshake(
        self, harvester_handshake: harvester_protocol.HarvesterHandshake, peer: WSChiaConnection
    ) -> None:
        """Handshake between the harvester and farmer."""
        raise NotImplementedError("Stub method should not be called")

    @metadata.request(peer_required=True)
    async def new_signage_point_harvester(
        self, new_challenge: harvester_protocol.NewSignagePointHarvester, peer: WSChiaConnection
    ) -> None:
        """Handle new signage point from farmer."""
        raise NotImplementedError("Stub method should not be called")

    @metadata.request(reply_types=[ProtocolMessageTypes.respond_signatures])
    async def request_signatures(self, request: harvester_protocol.RequestSignatures) -> Optional[Message]:
        """Handle signature request from farmer."""
        raise NotImplementedError("Stub method should not be called")

    @metadata.request()
    async def request_plots(self, _: harvester_protocol.RequestPlots) -> Message:
        """Handle request for plot information."""
        raise NotImplementedError("Stub method should not be called")

    @metadata.request()
    async def plot_sync_response(self, response: PlotSyncResponse) -> None:
        """Handle plot sync response."""
        raise NotImplementedError("Stub method should not be called")
