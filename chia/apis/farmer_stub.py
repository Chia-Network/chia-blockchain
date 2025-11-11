from __future__ import annotations

import logging
from typing import ClassVar, Optional

from typing_extensions import Protocol

from chia.protocols import farmer_protocol, harvester_protocol
from chia.protocols.harvester_protocol import (
    PlotSyncDone,
    PlotSyncPathList,
    PlotSyncPlotList,
    PlotSyncStart,
    RespondPlots,
    RespondSignatures,
)
from chia.protocols.outbound_message import Message
from chia.server.api_protocol import ApiMetadata, ApiProtocol
from chia.server.ws_connection import WSChiaConnection


class FarmerApiStub(ApiProtocol, Protocol):
    """Non-functional API stub for FarmerAPI

    This is a protocol definition only - methods are not implemented and should
    never be called. Use the actual FarmerAPI implementation at runtime.
    """

    log: logging.Logger
    # Create a concrete instance for decorators while keeping the ClassVar type hint for mypy
    metadata: ClassVar[ApiMetadata] = ApiMetadata()

    def ready(self) -> bool:
        """Check if the farmer is ready."""
        ...

    @metadata.request(peer_required=True)
    async def new_proof_of_space(
        self, new_proof_of_space: harvester_protocol.NewProofOfSpace, peer: WSChiaConnection
    ) -> None:
        """Handle new proof of space from harvester."""
        ...

    @metadata.request()
    async def respond_signatures(self, response: RespondSignatures) -> None:
        """Handle signature response from harvester."""
        ...

    @metadata.request()
    async def new_signage_point(self, new_signage_point: farmer_protocol.NewSignagePoint) -> None:
        """Handle new signage point from full node."""
        ...

    @metadata.request()
    async def request_signed_values(self, full_node_request: farmer_protocol.RequestSignedValues) -> Optional[Message]:
        """Handle request for signed values from full node."""
        ...

    @metadata.request(peer_required=True)
    async def farming_info(self, request: farmer_protocol.FarmingInfo, peer: WSChiaConnection) -> None:
        """Handle farming info from full node."""
        ...

    @metadata.request(peer_required=True)
    async def respond_plots(self, _: RespondPlots, peer: WSChiaConnection) -> None:
        """Handle respond plots from harvester."""
        ...

    @metadata.request(peer_required=True)
    async def plot_sync_start(self, message: PlotSyncStart, peer: WSChiaConnection) -> None:
        """Handle plot sync start."""
        ...

    @metadata.request(peer_required=True)
    async def plot_sync_loaded(self, message: PlotSyncPlotList, peer: WSChiaConnection) -> None:
        """Handle plot sync loaded."""
        ...

    @metadata.request(peer_required=True)
    async def plot_sync_removed(self, message: PlotSyncPathList, peer: WSChiaConnection) -> None:
        """Handle plot sync removed."""
        ...

    @metadata.request(peer_required=True)
    async def plot_sync_invalid(self, message: PlotSyncPathList, peer: WSChiaConnection) -> None:
        """Handle plot sync invalid."""
        ...

    @metadata.request(peer_required=True)
    async def plot_sync_keys_missing(self, message: PlotSyncPathList, peer: WSChiaConnection) -> None:
        """Handle plot sync keys missing."""
        ...

    @metadata.request(peer_required=True)
    async def plot_sync_duplicates(self, message: PlotSyncPathList, peer: WSChiaConnection) -> None:
        """Handle plot sync duplicates."""
        ...

    @metadata.request(peer_required=True)
    async def plot_sync_done(self, message: PlotSyncDone, peer: WSChiaConnection) -> None:
        """Handle plot sync done."""
        ...
