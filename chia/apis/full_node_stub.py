from __future__ import annotations

import logging
from typing import ClassVar

from typing_extensions import Protocol

from chia.protocols import (
    farmer_protocol,
    full_node_protocol,
    introducer_protocol,
    timelord_protocol,
    wallet_protocol,
)
from chia.protocols.outbound_message import Message
from chia.protocols.protocol_message_types import ProtocolMessageTypes
from chia.server.api_protocol import ApiMetadata, ApiProtocol
from chia.server.ws_connection import WSChiaConnection


class FullNodeApiStub(ApiProtocol, Protocol):
    """Non-functional API stub for FullNodeAPI

    This is a protocol definition only - methods are not implemented and should
    never be called. Use the actual FullNodeAPI implementation at runtime.
    """

    log: logging.Logger
    metadata: ClassVar[ApiMetadata] = ApiMetadata()

    def ready(self) -> bool:
        """Check if the full node is ready."""
        ...

    # PEER PROTOCOL
    @metadata.request(peer_required=True, reply_types=[ProtocolMessageTypes.respond_peers])
    async def request_peers(self, _request: full_node_protocol.RequestPeers, peer: WSChiaConnection) -> Message | None:
        """Handle peer request."""
        ...

    @metadata.request(peer_required=True)
    async def respond_peers(self, request: full_node_protocol.RespondPeers, peer: WSChiaConnection) -> Message | None:
        """Handle peers response."""
        ...

    @metadata.request(peer_required=True)
    async def respond_peers_introducer(
        self, request: introducer_protocol.RespondPeersIntroducer, peer: WSChiaConnection
    ) -> Message | None:
        """Handle peers response from introducer."""
        ...

    # FULL NODE PROTOCOL
    @metadata.request(peer_required=True, execute_task=True)
    async def new_peak(self, request: full_node_protocol.NewPeak, peer: WSChiaConnection) -> None:
        """Handle new peak from peer."""
        ...

    @metadata.request(peer_required=True)
    async def new_transaction(
        self, transaction: full_node_protocol.NewTransaction, peer: WSChiaConnection
    ) -> Message | None:
        """Handle new transaction from peer."""
        ...

    @metadata.request(reply_types=[ProtocolMessageTypes.respond_transaction])
    async def request_transaction(self, request: full_node_protocol.RequestTransaction) -> Message | None:
        """Handle transaction request."""
        ...

    @metadata.request(peer_required=True, bytes_required=True)
    async def respond_transaction(
        self,
        tx: full_node_protocol.RespondTransaction,
        peer: WSChiaConnection,
        tx_bytes: bytes = b"",
        test: bool = False,
    ) -> Message | None:
        """Handle transaction response from peer."""
        ...

    @metadata.request(reply_types=[ProtocolMessageTypes.respond_proof_of_weight])
    async def request_proof_of_weight(self, request: full_node_protocol.RequestProofOfWeight) -> Message | None:
        """Handle proof of weight request."""
        ...

    @metadata.request()
    async def respond_proof_of_weight(self, request: full_node_protocol.RespondProofOfWeight) -> Message | None:
        """Handle proof of weight response."""
        ...

    @metadata.request(reply_types=[ProtocolMessageTypes.respond_block, ProtocolMessageTypes.reject_block])
    async def request_block(self, request: full_node_protocol.RequestBlock) -> Message | None:
        """Handle block request."""
        ...

    @metadata.request(reply_types=[ProtocolMessageTypes.respond_blocks, ProtocolMessageTypes.reject_blocks])
    async def request_blocks(self, request: full_node_protocol.RequestBlocks) -> Message | None:
        """Handle blocks request."""
        ...

    @metadata.request(peer_required=True)
    async def reject_block(
        self,
        request: full_node_protocol.RejectBlock,
        peer: WSChiaConnection,
    ) -> None:
        """Handle block rejection."""
        ...

    @metadata.request(peer_required=True)
    async def reject_blocks(
        self,
        request: full_node_protocol.RejectBlocks,
        peer: WSChiaConnection,
    ) -> None:
        """Handle blocks rejection."""
        ...

    @metadata.request(peer_required=True)
    async def respond_blocks(
        self,
        request: full_node_protocol.RespondBlocks,
        peer: WSChiaConnection,
    ) -> None:
        """Handle blocks response."""
        ...

    @metadata.request(peer_required=True)
    async def respond_block(
        self,
        respond_block: full_node_protocol.RespondBlock,
        peer: WSChiaConnection,
    ) -> Message | None:
        """Handle block response."""
        ...

    @metadata.request()
    async def new_unfinished_block(self, new_unfinished_block: full_node_protocol.NewUnfinishedBlock) -> Message | None:
        """Handle new unfinished block."""
        ...

    @metadata.request(reply_types=[ProtocolMessageTypes.respond_unfinished_block])
    async def request_unfinished_block(
        self, request_unfinished_block: full_node_protocol.RequestUnfinishedBlock
    ) -> Message | None:
        """Handle unfinished block request."""
        ...

    @metadata.request()
    async def new_unfinished_block2(
        self, new_unfinished_block: full_node_protocol.NewUnfinishedBlock2
    ) -> Message | None:
        """Handle new unfinished block v2."""
        ...

    @metadata.request(reply_types=[ProtocolMessageTypes.respond_unfinished_block])
    async def request_unfinished_block2(
        self, request_unfinished_block: full_node_protocol.RequestUnfinishedBlock2
    ) -> Message | None:
        """Handle unfinished block v2 request."""
        ...

    @metadata.request(peer_required=True)
    async def respond_unfinished_block(
        self,
        respond_unfinished_block: full_node_protocol.RespondUnfinishedBlock,
        peer: WSChiaConnection,
    ) -> Message | None:
        """Handle unfinished block response."""
        ...

    @metadata.request(peer_required=True)
    async def new_signage_point_or_end_of_sub_slot(
        self, new_sp: full_node_protocol.NewSignagePointOrEndOfSubSlot, peer: WSChiaConnection
    ) -> Message | None:
        """Handle new signage point or end of sub slot."""
        ...

    @metadata.request(
        reply_types=[ProtocolMessageTypes.respond_signage_point, ProtocolMessageTypes.respond_end_of_sub_slot]
    )
    async def request_signage_point_or_end_of_sub_slot(
        self, request: full_node_protocol.RequestSignagePointOrEndOfSubSlot
    ) -> Message | None:
        """Handle signage point or end of sub slot request."""
        ...

    @metadata.request(peer_required=True)
    async def respond_signage_point(
        self, request: full_node_protocol.RespondSignagePoint, peer: WSChiaConnection
    ) -> Message | None:
        """Handle signage point response."""
        ...

    @metadata.request(peer_required=True)
    async def respond_end_of_sub_slot(
        self, request: full_node_protocol.RespondEndOfSubSlot, peer: WSChiaConnection
    ) -> Message | None:
        """Handle end of sub slot response."""
        ...

    @metadata.request(peer_required=True)
    async def request_mempool_transactions(
        self,
        request: full_node_protocol.RequestMempoolTransactions,
        peer: WSChiaConnection,
    ) -> Message | None:
        """Handle mempool transactions request."""
        ...

    # FARMER PROTOCOL
    @metadata.request(peer_required=True)
    async def declare_proof_of_space(
        self, request: farmer_protocol.DeclareProofOfSpace, peer: WSChiaConnection
    ) -> Message | None:
        """Handle proof of space declaration from farmer."""
        ...

    @metadata.request(peer_required=True)
    async def signed_values(
        self, farmer_request: farmer_protocol.SignedValues, peer: WSChiaConnection
    ) -> Message | None:
        """Handle signed values from farmer."""
        ...

    # TIMELORD PROTOCOL
    @metadata.request(peer_required=True)
    async def new_infusion_point_vdf(
        self, request: timelord_protocol.NewInfusionPointVDF, peer: WSChiaConnection
    ) -> Message | None:
        """Handle new infusion point VDF from timelord."""
        ...

    @metadata.request(peer_required=True)
    async def new_signage_point_vdf(
        self, request: timelord_protocol.NewSignagePointVDF, peer: WSChiaConnection
    ) -> None:
        """Handle new signage point VDF from timelord."""
        ...

    @metadata.request(peer_required=True)
    async def new_end_of_sub_slot_vdf(
        self, request: timelord_protocol.NewEndOfSubSlotVDF, peer: WSChiaConnection
    ) -> Message | None:
        """Handle new end of sub slot VDF from timelord."""
        ...

    @metadata.request(bytes_required=True, execute_task=True)
    async def respond_compact_proof_of_time(
        self, request: timelord_protocol.RespondCompactProofOfTime, request_bytes: bytes = b""
    ) -> None:
        """Handle compact proof of time response from timelord."""

    @metadata.request(peer_required=True, bytes_required=True, execute_task=True)
    async def new_compact_vdf(
        self, request: full_node_protocol.NewCompactVDF, peer: WSChiaConnection, request_bytes: bytes = b""
    ) -> None:
        """Handle new compact VDF."""
        ...

    @metadata.request(peer_required=True, reply_types=[ProtocolMessageTypes.respond_compact_vdf])
    async def request_compact_vdf(self, request: full_node_protocol.RequestCompactVDF, peer: WSChiaConnection) -> None:
        """Handle compact VDF request."""
        ...

    @metadata.request(peer_required=True)
    async def respond_compact_vdf(self, request: full_node_protocol.RespondCompactVDF, peer: WSChiaConnection) -> None:
        """Handle compact VDF response."""
        ...

    # WALLET PROTOCOL
    @metadata.request()
    async def request_block_header(self, request: wallet_protocol.RequestBlockHeader) -> Message | None:
        """Handle block header request from wallet."""
        ...

    @metadata.request()
    async def request_additions(self, request: wallet_protocol.RequestAdditions) -> Message | None:
        """Handle additions request from wallet."""
        ...

    @metadata.request()
    async def request_removals(self, request: wallet_protocol.RequestRemovals) -> Message | None:
        """Handle removals request from wallet."""
        ...

    @metadata.request()
    async def send_transaction(self, request: wallet_protocol.SendTransaction, *, test: bool = False) -> Message | None:
        """Handle transaction send from wallet."""
        ...

    @metadata.request()
    async def request_puzzle_solution(self, request: wallet_protocol.RequestPuzzleSolution) -> Message | None:
        """Handle puzzle solution request from wallet."""
        ...

    @metadata.request()
    async def request_block_headers(self, request: wallet_protocol.RequestBlockHeaders) -> Message | None:
        """Handle block headers request from wallet."""
        ...

    @metadata.request()
    async def request_header_blocks(self, request: wallet_protocol.RequestHeaderBlocks) -> Message | None:
        """Handle header blocks request from wallet (deprecated)."""
        ...

    @metadata.request(peer_required=True)
    async def register_for_ph_updates(
        self, request: wallet_protocol.RegisterForPhUpdates, peer: WSChiaConnection
    ) -> Message:
        """Handle puzzle hash updates registration from wallet."""
        ...

    @metadata.request(peer_required=True)
    async def register_for_coin_updates(
        self, request: wallet_protocol.RegisterForCoinUpdates, peer: WSChiaConnection
    ) -> Message:
        """Handle coin updates registration from wallet."""
        ...

    @metadata.request()
    async def request_children(self, request: wallet_protocol.RequestChildren) -> Message | None:
        """Handle children request from wallet."""
        ...

    @metadata.request()
    async def request_ses_hashes(self, request: wallet_protocol.RequestSESInfo) -> Message:
        """Handle SES hashes request from wallet."""
        ...

    @metadata.request(reply_types=[ProtocolMessageTypes.respond_fee_estimates])
    async def request_fee_estimates(self, request: wallet_protocol.RequestFeeEstimates) -> Message:
        """Handle fee estimates request from wallet."""
        ...

    @metadata.request(
        peer_required=True,
        reply_types=[ProtocolMessageTypes.respond_remove_puzzle_subscriptions],
    )
    async def request_remove_puzzle_subscriptions(
        self, request: wallet_protocol.RequestRemovePuzzleSubscriptions, peer: WSChiaConnection
    ) -> Message:
        """Handle remove puzzle subscriptions request from wallet."""
        ...

    @metadata.request(
        peer_required=True,
        reply_types=[ProtocolMessageTypes.respond_remove_coin_subscriptions],
    )
    async def request_remove_coin_subscriptions(
        self, request: wallet_protocol.RequestRemoveCoinSubscriptions, peer: WSChiaConnection
    ) -> Message:
        """Handle remove coin subscriptions request from wallet."""
        ...

    @metadata.request(peer_required=True, reply_types=[ProtocolMessageTypes.respond_puzzle_state])
    async def request_puzzle_state(
        self, request: wallet_protocol.RequestPuzzleState, peer: WSChiaConnection
    ) -> Message:
        """Handle puzzle state request from wallet."""
        ...

    @metadata.request(peer_required=True, reply_types=[ProtocolMessageTypes.respond_coin_state])
    async def request_coin_state(self, request: wallet_protocol.RequestCoinState, peer: WSChiaConnection) -> Message:
        """Handle coin state request from wallet."""
        ...

    @metadata.request(reply_types=[ProtocolMessageTypes.respond_cost_info])
    async def request_cost_info(self, _request: wallet_protocol.RequestCostInfo) -> Message | None:
        """Handle cost info request from wallet."""
        ...
