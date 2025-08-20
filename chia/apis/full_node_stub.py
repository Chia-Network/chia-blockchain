from __future__ import annotations

import logging
from typing import TYPE_CHECKING, ClassVar, Optional, cast

if TYPE_CHECKING:
    from chia.server.api_protocol import ApiProtocol

# Minimal imports to avoid circular dependencies
from chia.protocols import farmer_protocol, full_node_protocol, introducer_protocol, timelord_protocol, wallet_protocol
from chia.protocols.outbound_message import Message
from chia.protocols.protocol_message_types import ProtocolMessageTypes
from chia.server.api_protocol import ApiMetadata
from chia.server.ws_connection import WSChiaConnection


class FullNodeApiStub:
    """Lightweight API stub for FullNodeAPI to break circular dependencies."""

    if TYPE_CHECKING:
        _protocol_check: ClassVar[ApiProtocol] = cast("FullNodeApiStub", None)

    log: logging.Logger
    metadata: ClassVar[ApiMetadata] = ApiMetadata()

    def ready(self) -> bool:
        """Check if the full node is ready."""
        return True

    @metadata.request(peer_required=True, reply_types=[ProtocolMessageTypes.respond_peers])
    async def request_peers(
        self, _request: full_node_protocol.RequestPeers, peer: WSChiaConnection
    ) -> Optional[Message]:
        raise NotImplementedError("Stub method should not be called")

    @metadata.request(peer_required=True)
    async def respond_peers(self, request: full_node_protocol.RespondPeers, peer: WSChiaConnection) -> None:
        raise NotImplementedError("Stub method should not be called")

    @metadata.request(peer_required=True)
    async def respond_peers_introducer(
        self, request: introducer_protocol.RespondPeersIntroducer, peer: WSChiaConnection
    ) -> None:
        raise NotImplementedError("Stub method should not be called")

    @metadata.request(peer_required=True, execute_task=True)
    async def new_peak(self, request: full_node_protocol.NewPeak, peer: WSChiaConnection) -> None:
        raise NotImplementedError("Stub method should not be called")

    @metadata.request(peer_required=True)
    async def new_transaction(self, transaction: full_node_protocol.NewTransaction, peer: WSChiaConnection) -> None:
        raise NotImplementedError("Stub method should not be called")

    @metadata.request(reply_types=[ProtocolMessageTypes.respond_transaction])
    async def request_transaction(self, request: full_node_protocol.RequestTransaction) -> Optional[Message]:
        raise NotImplementedError("Stub method should not be called")

    @metadata.request(peer_required=True, bytes_required=True)
    async def respond_transaction(
        self,
        response: full_node_protocol.RespondTransaction,
        peer: WSChiaConnection,
        tx_bytes: bytes = b"",
    ) -> None:
        raise NotImplementedError("Stub method should not be called")

    @metadata.request(reply_types=[ProtocolMessageTypes.respond_proof_of_weight])
    async def request_proof_of_weight(self, request: full_node_protocol.RequestProofOfWeight) -> Optional[Message]:
        raise NotImplementedError("Stub method should not be called")

    @metadata.request()
    async def respond_proof_of_weight(self, request: full_node_protocol.RespondProofOfWeight) -> Optional[Message]:
        raise NotImplementedError("Stub method should not be called")

    @metadata.request(reply_types=[ProtocolMessageTypes.respond_block, ProtocolMessageTypes.reject_block])
    async def request_block(self, request: full_node_protocol.RequestBlock) -> Optional[Message]:
        raise NotImplementedError("Stub method should not be called")

    @metadata.request(reply_types=[ProtocolMessageTypes.respond_blocks, ProtocolMessageTypes.reject_blocks])
    async def request_blocks(self, request: full_node_protocol.RequestBlocks) -> Optional[Message]:
        raise NotImplementedError("Stub method should not be called")

    @metadata.request(peer_required=True)
    async def reject_block(
        self,
        reject_block: full_node_protocol.RejectBlock,
        peer: WSChiaConnection,
    ) -> None:
        raise NotImplementedError("Stub method should not be called")

    @metadata.request(peer_required=True)
    async def reject_blocks(
        self,
        reject_blocks_request: full_node_protocol.RejectBlocks,
        peer: WSChiaConnection,
    ) -> None:
        raise NotImplementedError("Stub method should not be called")

    @metadata.request(peer_required=True)
    async def respond_blocks(
        self,
        request: full_node_protocol.RespondBlocks,
        peer: WSChiaConnection,
    ) -> None:
        raise NotImplementedError("Stub method should not be called")

    @metadata.request(peer_required=True)
    async def respond_block(
        self,
        request: full_node_protocol.RespondBlock,
        peer: WSChiaConnection,
    ) -> None:
        raise NotImplementedError("Stub method should not be called")

    @metadata.request()
    async def new_unfinished_block(
        self, new_unfinished_block: full_node_protocol.NewUnfinishedBlock
    ) -> Optional[Message]:
        raise NotImplementedError("Stub method should not be called")

    @metadata.request(reply_types=[ProtocolMessageTypes.respond_unfinished_block])
    async def request_unfinished_block(
        self, request_unfinished_block: full_node_protocol.RequestUnfinishedBlock
    ) -> Optional[Message]:
        raise NotImplementedError("Stub method should not be called")

    @metadata.request()
    async def new_unfinished_block2(
        self, new_unfinished_block: full_node_protocol.NewUnfinishedBlock2
    ) -> Optional[Message]:
        raise NotImplementedError("Stub method should not be called")

    @metadata.request(reply_types=[ProtocolMessageTypes.respond_unfinished_block])
    async def request_unfinished_block2(
        self, request_unfinished_block: full_node_protocol.RequestUnfinishedBlock2
    ) -> Optional[Message]:
        raise NotImplementedError("Stub method should not be called")

    @metadata.request(peer_required=True)
    async def respond_unfinished_block(
        self,
        respond_unfinished_block: full_node_protocol.RespondUnfinishedBlock,
        peer: WSChiaConnection,
    ) -> None:
        raise NotImplementedError("Stub method should not be called")

    @metadata.request(peer_required=True)
    async def new_signage_point_or_end_of_sub_slot(
        self, new_sp: full_node_protocol.NewSignagePointOrEndOfSubSlot, peer: WSChiaConnection
    ) -> Optional[Message]:
        raise NotImplementedError("Stub method should not be called")

    @metadata.request(
        reply_types=[ProtocolMessageTypes.respond_signage_point, ProtocolMessageTypes.respond_end_of_sub_slot]
    )
    async def request_signage_point_or_end_of_sub_slot(
        self, request: full_node_protocol.RequestSignagePointOrEndOfSubSlot
    ) -> Optional[Message]:
        raise NotImplementedError("Stub method should not be called")

    @metadata.request(peer_required=True)
    async def respond_signage_point(
        self, request: full_node_protocol.RespondSignagePoint, peer: WSChiaConnection
    ) -> None:
        raise NotImplementedError("Stub method should not be called")

    @metadata.request(peer_required=True)
    async def respond_end_of_sub_slot(
        self, request: full_node_protocol.RespondEndOfSubSlot, peer: WSChiaConnection
    ) -> Optional[Message]:
        raise NotImplementedError("Stub method should not be called")

    @metadata.request(peer_required=True)
    async def request_mempool_transactions(
        self,
        request: full_node_protocol.RequestMempoolTransactions,
        peer: WSChiaConnection,
    ) -> None:
        raise NotImplementedError("Stub method should not be called")

    @metadata.request(peer_required=True)
    async def declare_proof_of_space(
        self, request: farmer_protocol.DeclareProofOfSpace, peer: WSChiaConnection
    ) -> None:
        raise NotImplementedError("Stub method should not be called")

    @metadata.request(peer_required=True)
    async def signed_values(self, farmer_request: farmer_protocol.SignedValues, peer: WSChiaConnection) -> None:
        raise NotImplementedError("Stub method should not be called")

    @metadata.request(peer_required=True)
    async def new_infusion_point_vdf(
        self, request: timelord_protocol.NewInfusionPointVDF, peer: WSChiaConnection
    ) -> None:
        raise NotImplementedError("Stub method should not be called")

    @metadata.request(peer_required=True)
    async def new_signage_point_vdf(
        self, request: timelord_protocol.NewSignagePointVDF, peer: WSChiaConnection
    ) -> None:
        raise NotImplementedError("Stub method should not be called")

    @metadata.request(peer_required=True)
    async def new_end_of_sub_slot_vdf(
        self, request: timelord_protocol.NewEndOfSubSlotVDF, peer: WSChiaConnection
    ) -> Optional[Message]:
        raise NotImplementedError("Stub method should not be called")

    @metadata.request()
    async def request_block_header(self, request: wallet_protocol.RequestBlockHeader) -> Optional[Message]:
        raise NotImplementedError("Stub method should not be called")

    @metadata.request()
    async def request_additions(self, request: wallet_protocol.RequestAdditions) -> Optional[Message]:
        raise NotImplementedError("Stub method should not be called")

    @metadata.request()
    async def request_removals(self, request: wallet_protocol.RequestRemovals) -> Optional[Message]:
        raise NotImplementedError("Stub method should not be called")

    @metadata.request()
    async def send_transaction(
        self, request: wallet_protocol.SendTransaction, *, test: bool = False
    ) -> Optional[Message]:
        raise NotImplementedError("Stub method should not be called")

    @metadata.request()
    async def request_puzzle_solution(self, request: wallet_protocol.RequestPuzzleSolution) -> Optional[Message]:
        raise NotImplementedError("Stub method should not be called")

    @metadata.request()
    async def request_block_headers(self, request: wallet_protocol.RequestBlockHeaders) -> Optional[Message]:
        raise NotImplementedError("Stub method should not be called")

    @metadata.request()
    async def request_header_blocks(self, request: wallet_protocol.RequestHeaderBlocks) -> Optional[Message]:
        raise NotImplementedError("Stub method should not be called")

    @metadata.request(bytes_required=True, execute_task=True)
    async def respond_compact_proof_of_time(
        self, request: timelord_protocol.RespondCompactProofOfTime, request_bytes: bytes = b""
    ) -> None:
        raise NotImplementedError("Stub method should not be called")

    @metadata.request(peer_required=True, bytes_required=True, execute_task=True)
    async def new_compact_vdf(
        self, request: full_node_protocol.NewCompactVDF, peer: WSChiaConnection, request_bytes: bytes = b""
    ) -> None:
        raise NotImplementedError("Stub method should not be called")

    @metadata.request(peer_required=True, reply_types=[ProtocolMessageTypes.respond_compact_vdf])
    async def request_compact_vdf(self, request: full_node_protocol.RequestCompactVDF, peer: WSChiaConnection) -> None:
        raise NotImplementedError("Stub method should not be called")

    @metadata.request(peer_required=True)
    async def respond_compact_vdf(self, request: full_node_protocol.RespondCompactVDF, peer: WSChiaConnection) -> None:
        raise NotImplementedError("Stub method should not be called")

    @metadata.request(peer_required=True)
    async def register_for_ph_updates(
        self, request: wallet_protocol.RegisterForPhUpdates, peer: WSChiaConnection
    ) -> Optional[Message]:
        raise NotImplementedError("Stub method should not be called")

    @metadata.request(peer_required=True)
    async def register_for_coin_updates(
        self, request: wallet_protocol.RegisterForCoinUpdates, peer: WSChiaConnection
    ) -> Optional[Message]:
        raise NotImplementedError("Stub method should not be called")

    @metadata.request()
    async def request_children(self, request: wallet_protocol.RequestChildren) -> Optional[Message]:
        raise NotImplementedError("Stub method should not be called")

    @metadata.request()
    async def request_ses_hashes(self, request: wallet_protocol.RequestSESInfo) -> Message:
        raise NotImplementedError("Stub method should not be called")

    @metadata.request(reply_types=[ProtocolMessageTypes.respond_fee_estimates])
    async def request_fee_estimates(self, request: wallet_protocol.RequestFeeEstimates) -> Message:
        raise NotImplementedError("Stub method should not be called")

    @metadata.request(
        peer_required=True,
        reply_types=[ProtocolMessageTypes.respond_remove_puzzle_subscriptions],
    )
    async def request_remove_puzzle_subscriptions(
        self, request: wallet_protocol.RequestRemovePuzzleSubscriptions, peer: WSChiaConnection
    ) -> Message:
        raise NotImplementedError("Stub method should not be called")

    @metadata.request(
        peer_required=True,
        reply_types=[ProtocolMessageTypes.respond_remove_coin_subscriptions],
    )
    async def request_remove_coin_subscriptions(
        self, request: wallet_protocol.RequestRemoveCoinSubscriptions, peer: WSChiaConnection
    ) -> Message:
        raise NotImplementedError("Stub method should not be called")

    @metadata.request(peer_required=True, reply_types=[ProtocolMessageTypes.respond_puzzle_state])
    async def request_puzzle_state(
        self, request: wallet_protocol.RequestPuzzleState, peer: WSChiaConnection
    ) -> Message:
        raise NotImplementedError("Stub method should not be called")

    @metadata.request(peer_required=True, reply_types=[ProtocolMessageTypes.respond_coin_state])
    async def request_coin_state(self, request: wallet_protocol.RequestCoinState, peer: WSChiaConnection) -> Message:
        raise NotImplementedError("Stub method should not be called")

    @metadata.request(reply_types=[ProtocolMessageTypes.respond_cost_info])
    async def request_cost_info(self, _request: wallet_protocol.RequestCostInfo) -> Optional[Message]:
        raise NotImplementedError("Stub method should not be called")
