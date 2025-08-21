from __future__ import annotations

import logging
from typing import TYPE_CHECKING, ClassVar, cast

if TYPE_CHECKING:
    from chia.server.api_protocol import ApiProtocol

# Minimal imports to avoid circular dependencies
from chia.protocols.full_node_protocol import RespondBlocks, RespondPeers, RespondProofOfWeight
from chia.protocols.introducer_protocol import RespondPeersIntroducer
from chia.protocols.wallet_protocol import (
    CoinStateUpdate,
    NewPeakWallet,
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
    RespondToPhUpdates,
    TransactionAck,
)
from chia.server.api_protocol import ApiMetadata
from chia.server.ws_connection import WSChiaConnection


class WalletNodeApiStub:
    """Lightweight API stub for WalletNodeAPI to break circular dependencies."""

    if TYPE_CHECKING:
        _protocol_check: ClassVar[ApiProtocol] = cast("WalletNodeApiStub", None)

    log: logging.Logger
    metadata: ClassVar[ApiMetadata] = ApiMetadata()

    def ready(self) -> bool:
        """Check if the wallet is ready."""
        return True

    @metadata.request(peer_required=True)
    async def respond_removals(self, response: RespondRemovals, peer: WSChiaConnection) -> None:
        raise NotImplementedError("Stub method should not be called")

    async def reject_removals_request(self, response: RejectRemovalsRequest, peer: WSChiaConnection) -> None:
        raise NotImplementedError("Stub method should not be called")

    @metadata.request()
    async def reject_additions_request(self, response: RejectAdditionsRequest) -> None:
        raise NotImplementedError("Stub method should not be called")

    @metadata.request(peer_required=True, execute_task=True)
    async def new_peak_wallet(self, peak: NewPeakWallet, peer: WSChiaConnection) -> None:
        raise NotImplementedError("Stub method should not be called")

    @metadata.request()
    async def reject_header_request(self, response: RejectHeaderRequest) -> None:
        raise NotImplementedError("Stub method should not be called")

    @metadata.request()
    async def respond_block_header(self, response: RespondBlockHeader) -> None:
        raise NotImplementedError("Stub method should not be called")

    @metadata.request(peer_required=True)
    async def respond_additions(self, response: RespondAdditions, peer: WSChiaConnection) -> None:
        raise NotImplementedError("Stub method should not be called")

    @metadata.request()
    async def respond_proof_of_weight(self, response: RespondProofOfWeight) -> None:
        raise NotImplementedError("Stub method should not be called")

    @metadata.request(peer_required=True)
    async def transaction_ack(self, ack: TransactionAck, peer: WSChiaConnection) -> None:
        return None

    @metadata.request(peer_required=True)
    async def respond_peers_introducer(self, request: RespondPeersIntroducer, peer: WSChiaConnection) -> None:
        raise NotImplementedError("Stub method should not be called")

    @metadata.request(peer_required=True)
    async def respond_peers(self, request: RespondPeers, peer: WSChiaConnection) -> None:
        return None

    @metadata.request()
    async def respond_puzzle_solution(self, request: RespondPuzzleSolution) -> None:
        raise NotImplementedError("Stub method should not be called")

    @metadata.request()
    async def reject_puzzle_solution(self, request: RejectPuzzleSolution) -> None:
        raise NotImplementedError("Stub method should not be called")

    @metadata.request()
    async def respond_header_blocks(self, request: RespondHeaderBlocks) -> None:
        raise NotImplementedError("Stub method should not be called")

    @metadata.request()
    async def respond_block_headers(self, request: RespondBlockHeaders) -> None:
        raise NotImplementedError("Stub method should not be called")

    @metadata.request()
    async def reject_header_blocks(self, request: RejectHeaderBlocks) -> None:
        raise NotImplementedError("Stub method should not be called")

    @metadata.request()
    async def reject_block_headers(self, request: RejectBlockHeaders) -> None:
        raise NotImplementedError("Stub method should not be called")

    @metadata.request(peer_required=True, execute_task=True)
    async def coin_state_update(self, request: CoinStateUpdate, peer: WSChiaConnection) -> None:
        raise NotImplementedError("Stub method should not be called")

    @metadata.request()  # type: ignore[type-var]
    async def respond_to_ph_updates(self, request: RespondToPhUpdates) -> None:
        raise NotImplementedError("Stub method should not be called")

    @metadata.request()
    async def respond_to_coin_updates(self, request: RespondToCoinUpdates) -> None:
        raise NotImplementedError("Stub method should not be called")

    @metadata.request()
    async def respond_children(self, request: RespondChildren) -> None:
        raise NotImplementedError("Stub method should not be called")

    @metadata.request()
    async def respond_ses_hashes(self, request: RespondSESInfo) -> None:
        raise NotImplementedError("Stub method should not be called")

    @metadata.request()
    async def respond_blocks(self, request: RespondBlocks) -> None:
        raise NotImplementedError("Stub method should not be called")
