from __future__ import annotations

import logging
from typing import ClassVar

from chia_rs import RespondToPhUpdates
from typing_extensions import Protocol

from chia.protocols import full_node_protocol, introducer_protocol, wallet_protocol
from chia.protocols.wallet_protocol import (
    CoinStateUpdate,
    RejectAdditionsRequest,
    RejectBlockHeaders,
    RejectHeaderBlocks,
    RejectHeaderRequest,
    RejectPuzzleSolution,
    RejectRemovalsRequest,
    RespondAdditions,
    RespondBlockHeader,
    RespondBlockHeaders,
    RespondChildren,
    RespondHeaderBlocks,
    RespondPuzzleSolution,
    RespondRemovals,
    RespondSESInfo,
    RespondToCoinUpdates,
    TransactionAck,
)
from chia.server.api_protocol import ApiMetadata, ApiProtocol
from chia.server.ws_connection import WSChiaConnection


class WalletNodeApiStub(ApiProtocol, Protocol):
    """Non-functional API stub for WalletNodeAPI

    This is a protocol definition only - methods are not implemented and should
    never be called. Use the actual WalletNodeAPI implementation at runtime.
    """

    log: logging.Logger
    metadata: ClassVar[ApiMetadata] = ApiMetadata()

    def ready(self) -> bool:
        """Check if the wallet is ready."""
        ...

    @metadata.request(peer_required=True)
    async def respond_removals(self, response: RespondRemovals, peer: WSChiaConnection) -> None:
        """Handle removals response from full node."""
        ...

    async def reject_removals_request(self, response: RejectRemovalsRequest, peer: WSChiaConnection) -> None:
        """Handle reject removals request from full node."""
        ...

    @metadata.request()
    async def reject_additions_request(self, response: RejectAdditionsRequest) -> None:
        """Handle reject additions request from full node."""
        ...

    @metadata.request(peer_required=True, execute_task=True)
    async def new_peak_wallet(self, peak: wallet_protocol.NewPeakWallet, peer: WSChiaConnection) -> None:
        """Handle new peak from full node."""
        ...

    @metadata.request()
    async def reject_header_request(self, response: RejectHeaderRequest) -> None:
        """Handle reject header request from full node."""
        ...

    @metadata.request()
    async def respond_block_header(self, response: RespondBlockHeader) -> None:
        """Handle block header response from full node."""
        ...

    @metadata.request(peer_required=True)
    async def respond_additions(self, response: RespondAdditions, peer: WSChiaConnection) -> None:
        """Handle additions response from full node."""
        ...

    @metadata.request()
    async def respond_proof_of_weight(self, response: full_node_protocol.RespondProofOfWeight) -> None:
        """Handle proof of weight response from full node."""
        ...

    @metadata.request(peer_required=True)
    async def transaction_ack(self, ack: TransactionAck, peer: WSChiaConnection) -> None:
        """Handle transaction acknowledgment from full node."""
        ...

    @metadata.request(peer_required=True)
    async def respond_peers_introducer(
        self, request: introducer_protocol.RespondPeersIntroducer, peer: WSChiaConnection
    ) -> None:
        """Handle peers response from introducer."""
        ...

    @metadata.request(peer_required=True)
    async def respond_peers(self, request: full_node_protocol.RespondPeers, peer: WSChiaConnection) -> None:
        """Handle peers response from full node."""
        ...

    @metadata.request()
    async def respond_puzzle_solution(self, request: RespondPuzzleSolution) -> None:
        """Handle puzzle solution response from full node."""
        ...

    @metadata.request()
    async def reject_puzzle_solution(self, request: RejectPuzzleSolution) -> None:
        """Handle reject puzzle solution from full node."""
        ...

    @metadata.request()
    async def respond_header_blocks(self, request: RespondHeaderBlocks) -> None:
        """Handle header blocks response from full node."""
        ...

    @metadata.request()
    async def respond_block_headers(self, request: RespondBlockHeaders) -> None:
        """Handle block headers response from full node."""
        ...

    @metadata.request()
    async def reject_header_blocks(self, request: RejectHeaderBlocks) -> None:
        """Handle reject header blocks from full node."""
        ...

    @metadata.request()
    async def reject_block_headers(self, request: RejectBlockHeaders) -> None:
        """Handle reject block headers from full node."""
        ...

    @metadata.request(peer_required=True, execute_task=True)
    async def coin_state_update(self, request: CoinStateUpdate, peer: WSChiaConnection) -> None:
        """Handle coin state update from full node."""
        ...

    @metadata.request()  # type: ignore[type-var]
    async def respond_to_ph_updates(self, request: RespondToPhUpdates) -> None:
        """Handle puzzle hash updates response from full node."""
        ...

    @metadata.request()
    async def respond_to_coin_updates(self, request: RespondToCoinUpdates) -> None:
        """Handle coin updates response from full node."""
        ...

    @metadata.request()
    async def respond_children(self, request: RespondChildren) -> None:
        """Handle children response from full node."""
        ...

    @metadata.request()
    async def respond_ses_hashes(self, request: RespondSESInfo) -> None:
        """Handle SES hashes response from full node."""
        ...

    @metadata.request()
    async def respond_blocks(self, request: full_node_protocol.RespondBlocks) -> None:
        """Handle blocks response from full node."""
        ...
