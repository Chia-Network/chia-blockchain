from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, Optional, cast

from chia.protocols import farmer_protocol, harvester_protocol
from chia.protocols.harvester_protocol import PlotSyncDone, PlotSyncPathList, PlotSyncPlotList, PlotSyncStart
from chia.protocols.outbound_message import Message
from chia.server.api_protocol import ApiMetadata, ApiProtocolSchema
from chia.server.ws_connection import WSChiaConnection


class FarmerApiSchema:
    if TYPE_CHECKING:
        _protocol_check: ApiProtocolSchema = cast("FarmerApiSchema", None)

    metadata: ClassVar[ApiMetadata] = ApiMetadata()

    @metadata.request(peer_required=True)
    async def new_proof_of_space(
        self, new_proof_of_space: harvester_protocol.NewProofOfSpace, peer: WSChiaConnection
    ) -> None: ...

    @metadata.request()
    async def respond_signatures(self, response: harvester_protocol.RespondSignatures) -> None: ...

    @metadata.request()
    async def new_signage_point(self, new_signage_point: farmer_protocol.NewSignagePoint) -> None: ...

    @metadata.request()
    async def request_signed_values(
        self, full_node_request: farmer_protocol.RequestSignedValues
    ) -> Optional[Message]: ...

    @metadata.request(peer_required=True)
    async def farming_info(self, request: farmer_protocol.FarmingInfo, peer: WSChiaConnection) -> None: ...

    @metadata.request(peer_required=True)
    async def respond_plots(self, _: harvester_protocol.RespondPlots, peer: WSChiaConnection) -> None: ...

    @metadata.request(peer_required=True)
    async def plot_sync_start(self, message: PlotSyncStart, peer: WSChiaConnection) -> None: ...

    @metadata.request(peer_required=True)
    async def plot_sync_loaded(self, message: PlotSyncPlotList, peer: WSChiaConnection) -> None: ...

    @metadata.request(peer_required=True)
    async def plot_sync_removed(self, message: PlotSyncPathList, peer: WSChiaConnection) -> None: ...

    @metadata.request(peer_required=True)
    async def plot_sync_invalid(self, message: PlotSyncPathList, peer: WSChiaConnection) -> None: ...

    @metadata.request(peer_required=True)
    async def plot_sync_keys_missing(self, message: PlotSyncPathList, peer: WSChiaConnection) -> None: ...

    @metadata.request(peer_required=True)
    async def plot_sync_duplicates(self, message: PlotSyncPathList, peer: WSChiaConnection) -> None: ...

    @metadata.request(peer_required=True)
    async def plot_sync_done(self, message: PlotSyncDone, peer: WSChiaConnection) -> None: ...
