from __future__ import annotations

from typing import Optional

from chia.protocols import harvester_protocol
from chia.protocols.harvester_protocol import PlotSyncResponse
from chia.protocols.outbound_message import Message
from chia.protocols.protocol_message_types import ProtocolMessageTypes
from chia.server.api_protocol import ApiMetadata
from chia.server.ws_connection import WSChiaConnection


class HarvesterApiSchema:
    metadata = ApiMetadata()

    @metadata.request(peer_required=True)
    async def harvester_handshake(
        self, harvester_handshake: harvester_protocol.HarvesterHandshake, peer: WSChiaConnection
    ) -> None: ...

    @metadata.request(peer_required=True)
    async def new_signage_point_harvester(
        self, new_challenge: harvester_protocol.NewSignagePointHarvester, peer: WSChiaConnection
    ) -> None: ...

    @metadata.request(reply_types=[ProtocolMessageTypes.respond_signatures])
    async def request_signatures(self, request: harvester_protocol.RequestSignatures) -> Optional[Message]: ...

    @metadata.request()
    async def request_plots(self, _: harvester_protocol.RequestPlots) -> Message: ...

    @metadata.request()
    async def plot_sync_response(self, response: PlotSyncResponse) -> None: ...
