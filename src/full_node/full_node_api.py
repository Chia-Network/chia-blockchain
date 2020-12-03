import dataclasses
import time

import src.server.ws_connection as ws
from typing import AsyncGenerator, List, Optional, Tuple, Callable
from chiabip158 import PyBIP158
from blspy import G2Element

from src.consensus.block_creation import unfinished_block_to_full_block, create_unfinished_block
from src.consensus.difficulty_adjustment import get_sub_slot_iters_and_difficulty
from src.consensus.pot_iterations import (
    is_overflow_sub_block,
    calculate_ip_iters,
    calculate_sp_iters,
    calculate_iterations_quality,
)

from src.full_node.full_node import FullNode
from src.full_node.signage_point import SignagePoint
from src.consensus.sub_block_record import SubBlockRecord

from src.protocols import (
    introducer_protocol,
    farmer_protocol,
    full_node_protocol,
    timelord_protocol,
)
from src.server.outbound_message import Message, NodeType, OutboundMessage

from src.types.end_of_slot_bundle import EndOfSubSlotBundle
from src.types.full_block import FullBlock

from src.types.mempool_inclusion_status import MempoolInclusionStatus
from src.types.mempool_item import MempoolItem
from src.types.sized_bytes import bytes32
from src.types.spend_bundle import SpendBundle
from src.types.unfinished_block import UnfinishedBlock
from src.util.api_decorators import api_request, peer_required
from src.util.ints import uint64, uint128, uint8
from src.types.peer_info import PeerInfo

OutboundMessageGenerator = AsyncGenerator[OutboundMessage, None]


class FullNodeAPI:
    full_node: FullNode

    def __init__(self, full_node):
        self.full_node = full_node

    def _set_state_changed_callback(self, callback: Callable):
        self.full_node.state_changed_callback = callback

    @property
    def server(self):
        return self.full_node.server

    @property
    def log(self):
        return self.full_node.log

    @peer_required
    @api_request
    async def request_peers(self, request: full_node_protocol.RequestPeers, peer: ws.WSChiaConnection):
        if peer.peer_server_port is None:
            return None
        peer_info = PeerInfo(peer.peer_host, peer.peer_server_port)
        msg = await self.full_node.full_node_peers.request_peers(peer_info)
        return msg

    @peer_required
    @api_request
    async def respond_peers(
        self, request: introducer_protocol.RespondPeers, peer: ws.WSChiaConnection
    ) -> Optional[Message]:
        await self.full_node.full_node_peers.respond_peers(request, peer.get_peer_info(), False)
        await peer.close()
        return None

    @api_request
    async def new_peak(self, request: full_node_protocol.NewPeak) -> Optional[Message]:
        """
        A peer notifies us that they have added a new peak to their blockchain. If we don't have it,
        we can ask for it.
        """
        # Check if we have this block in the blockchain
        if self.full_node.blockchain.contains_sub_block(request.header_hash):
            return

        # Not interested in less heavy peaks
        if (
            self.full_node.blockchain.get_peak() is not None
            and self.full_node.blockchain.get_peak().weight > request.weight
        ):
            return

        # TODO: potential optimization, don't request blocks that we have already sent out
        request_transactions: bool = (
            self.full_node.full_node_store.get_unfinished_block(request.unfinished_reward_block_hash) is None
        )
        message = Message(
            "request_sub_block",
            full_node_protocol.RequestSubBlock(request.sub_block_height, request_transactions),
        )
        return message

    @api_request
    async def new_transaction(self, transaction: full_node_protocol.NewTransaction) -> Optional[Message]:
        """
        A peer notifies us of a new transaction.
        Requests a full transaction if we haven't seen it previously, and if the fees are enough.
        """
        # Ignore if syncing
        if self.full_node.sync_store.get_sync_mode():
            return None
        # Ignore if already seen
        if self.full_node.mempool_manager.seen(transaction.transaction_id):
            return None

        if self.full_node.mempool_manager.is_fee_enough(transaction.fees, transaction.cost):
            request_tx = full_node_protocol.RequestTransaction(transaction.transaction_id)
            msg = Message("request_transaction", request_tx)
            return msg

    @api_request
    async def request_transaction(self, request: full_node_protocol.RequestTransaction) -> Optional[Message]:
        """ Peer has requested a full transaction from us. """
        # Ignore if syncing
        if self.full_node.sync_store.get_sync_mode():
            return
        spend_bundle = self.full_node.mempool_manager.get_spendbundle(request.transaction_id)
        if spend_bundle is None:
            return

        transaction = full_node_protocol.RespondTransaction(spend_bundle)

        msg = Message("respond_transaction", transaction)
        self.log.info(f"sending transaction (tx_id: {spend_bundle.name()}) to peer")
        return msg

    @peer_required
    @api_request
    async def respond_transaction(
        self, tx: full_node_protocol.RespondTransaction, peer: ws.WSChiaConnection
    ) -> Optional[Message]:
        """
        Receives a full transaction from peer.
        If tx is added to mempool, send tx_id to others. (new_transaction)
        """
        # Ignore if syncing
        if self.full_node.sync_store.get_sync_mode():
            return

        async with self.full_node.blockchain.lock:
            # Ignore if we have already added this transaction
            if self.full_node.mempool_manager.get_spendbundle(tx.transaction.name()) is not None:
                return
            cost, status, error = await self.full_node.mempool_manager.add_spendbundle(tx.transaction)
            if status == MempoolInclusionStatus.SUCCESS:
                self.log.info(f"Added transaction to mempool: {tx.transaction.name()}")
                fees = tx.transaction.fees()
                assert fees >= 0
                assert cost is not None
                new_tx = full_node_protocol.NewTransaction(
                    tx.transaction.name(),
                    cost,
                    uint64(tx.transaction.fees()),
                )
                message = Message("new_transaction", new_tx)
                await self.server.send_to_all_except([message], NodeType.FULL_NODE, peer.peer_node_id)
            else:
                self.log.warning(
                    f"Was not able to add transaction with id {tx.transaction.name()}, {status} error: {error}"
                )
                return

    @api_request
    async def request_proof_of_weight(self, tx: full_node_protocol.RequestProofOfWeight) -> OutboundMessageGenerator:
        # TODO(mariano/almog)
        pass

    @api_request
    async def respond_proof_of_weight(self, tx: full_node_protocol.RespondProofOfWeight) -> OutboundMessageGenerator:
        # TODO(mariano/almog)
        pass

    @api_request
    async def request_sub_block(self, request: full_node_protocol.RequestSubBlock) -> Optional[Message]:
        if request.height not in self.full_node.blockchain.height_to_hash:
            return
        block: Optional[FullBlock] = await self.full_node.block_store.get_full_block(
            self.full_node.blockchain.height_to_hash[request.height]
        )
        if block is not None:
            if not request.include_transaction_block:
                block = dataclasses.replace(block, transactions_generator=None)
            msg = Message("respond_sub_block", full_node_protocol.RespondSubBlock(block))
            return msg
        return

    @api_request
    async def respond_sub_block(self, respond_sub_block: full_node_protocol.RespondSubBlock) -> Optional[Message]:
        """
        Receive a full block from a peer full node (or ourselves).
        """
        return await self.full_node.respond_sub_block(respond_sub_block)

    @api_request
    async def new_unfinished_sub_block(
        self, new_unfinished_sub_block: full_node_protocol.NewUnfinishedSubBlock
    ) -> Optional[Message]:
        if (
            self.full_node.full_node_store.get_unfinished_block(new_unfinished_sub_block.unfinished_reward_hash)
            is not None
        ):
            return

        msg = Message(
            "request_unfinished_sub_block",
            full_node_protocol.RequestUnfinishedSubBlock(new_unfinished_sub_block.unfinished_reward_hash),
        )
        return msg

    @api_request
    async def request_unfinished_sub_block(
        self, request_unfinished_sub_block: full_node_protocol.RequestUnfinishedSubBlock
    ) -> Optional[Message]:
        unfinished_block: Optional[UnfinishedBlock] = self.full_node.full_node_store.get_unfinished_block(
            request_unfinished_sub_block.unfinished_reward_hash
        )
        if unfinished_block is not None:
            msg = Message(
                "respond_unfinished_block",
                full_node_protocol.RespondUnfinishedSubBlock(unfinished_block),
            )
            return msg

    @peer_required
    @api_request
    async def respond_unfinished_sub_block(
        self, respond_unfinished_sub_block: full_node_protocol.RespondUnfinishedSubBlock, peer: ws.WSChiaConnection
    ) -> Optional[Message]:
        return await self.full_node._respond_unfinished_sub_block(respond_unfinished_sub_block, peer)

    @api_request
    async def new_signage_point_or_end_of_sub_slot(
        self, new_sp: full_node_protocol.NewSignagePointOrEndOfSubSlot
    ) -> Optional[Message]:
        if (
            self.full_node.full_node_store.get_signage_point_by_index(
                new_sp.challenge_hash, new_sp.index_from_challenge, new_sp.last_rc_infusion
            )
            is not None
        ):
            return

        if new_sp.index_from_challenge == 0 and new_sp.prev_challenge_hash is not None:
            if self.full_node.full_node_store.get_sub_slot(new_sp.prev_challenge_hash) is None:
                # If this is an end of sub slot, and we don't have the prev, request the prev instead
                full_node_request = full_node_protocol.RequestSignagePointOrEndOfSubSlot(
                    new_sp.prev_challenge_hash, uint8(0), new_sp.last_rc_infusion
                )
                return Message("request_signage_point_or_end_of_sub_slot", full_node_request)
        if new_sp.index_from_challenge > 0:
            if (
                new_sp.challenge_hash != self.full_node.constants.FIRST_CC_CHALLENGE
                and self.full_node.full_node_store.get_sub_slot(new_sp.challenge_hash) is None
            ):
                # If this is a normal signage point,, and we don't have the end of sub slot, request the end of sub slot
                full_node_request = full_node_protocol.RequestSignagePointOrEndOfSubSlot(
                    new_sp.challenge_hash, uint8(0), new_sp.last_rc_infusion
                )
                return Message("request_signage_point_or_end_of_sub_slot", full_node_request)

        # Otherwise (we have the prev or the end of sub slot), request it normally
        full_node_request = full_node_protocol.RequestSignagePointOrEndOfSubSlot(
            new_sp.challenge_hash, new_sp.index_from_challenge, new_sp.last_rc_infusion
        )

        return Message("request_signage_point_or_end_of_sub_slot", full_node_request)

    @api_request
    async def request_signage_point_or_end_of_sub_slot(
        self, request: full_node_protocol.RequestSignagePointOrEndOfSubSlot
    ) -> Optional[Message]:
        if request.index_from_challenge == 0:
            sub_slot: Optional[Tuple[EndOfSubSlotBundle, int]] = self.full_node.full_node_store.get_sub_slot(
                request.challenge_hash
            )
            if sub_slot is not None:
                return Message("respond_end_of_sub_slot", full_node_protocol.RespondEndOfSubSlot(sub_slot[0]))
            else:
                self.log.warning("Don't have sub slot")
        else:
            if self.full_node.full_node_store.get_sub_slot(request.challenge_hash) is None:
                if request.challenge_hash != self.full_node.constants.FIRST_CC_CHALLENGE:
                    self.log.warning(f"Don't have challenge hash {request.challenge_hash}")

            sp: Optional[SignagePoint] = self.full_node.full_node_store.get_signage_point_by_index(
                request.challenge_hash, request.index_from_challenge, request.last_rc_infusion
            )
            if sp is not None:
                full_node_response = full_node_protocol.RespondSignagePoint(
                    request.index_from_challenge,
                    sp.cc_vdf,
                    sp.cc_proof,
                    sp.rc_vdf,
                    sp.rc_proof,
                )
                return Message("respond_signage_point", full_node_response)
            else:
                self.log.warning(f"Don't have signage point {request}")

    @peer_required
    @api_request
    async def respond_signage_point(
        self, request: full_node_protocol.RespondSignagePoint, peer: ws.WSChiaConnection
    ) -> Optional[Message]:
        peak = self.full_node.blockchain.get_peak()
        if peak is not None and peak.height > 2:
            sub_slot_iters = peak.sub_slot_iters
            difficulty = uint64(peak.weight - self.full_node.blockchain.sub_blocks[peak.prev_hash].weight)
            next_sub_slot_iters = self.full_node.blockchain.get_next_slot_iters(peak.header_hash, True)
            next_difficulty = self.full_node.blockchain.get_next_difficulty(peak.header_hash, True)
            _, ip_sub_slot = await self.full_node.blockchain.get_sp_and_ip_sub_slots(peak.header_hash)
        else:
            sub_slot_iters = self.full_node.constants.SUB_SLOT_ITERS_STARTING
            difficulty = self.full_node.constants.DIFFICULTY_STARTING
            next_sub_slot_iters = sub_slot_iters
            next_difficulty = difficulty
            ip_sub_slot = None

        added = self.full_node.full_node_store.new_signage_point(
            request.index_from_challenge,
            self.full_node.blockchain.sub_blocks,
            self.full_node.blockchain.get_peak(),
            next_sub_slot_iters,
            SignagePoint(
                request.challenge_chain_vdf,
                request.challenge_chain_proof,
                request.reward_chain_vdf,
                request.reward_chain_proof,
            ),
        )

        if added:
            self.log.info(
                f"Finished signage point {request.index_from_challenge}/{self.full_node.constants.NUM_SPS_SUB_SLOT}"
            )
            sub_slot_tuple = self.full_node.full_node_store.get_sub_slot(request.challenge_chain_vdf.challenge)
            if sub_slot_tuple is not None:
                prev_challenge = sub_slot_tuple[0].challenge_chain.challenge_chain_end_of_slot_vdf.challenge
            else:
                prev_challenge = None
            # Notify nodes of the new signage point
            broadcast = full_node_protocol.NewSignagePointOrEndOfSubSlot(
                prev_challenge,
                request.challenge_chain_vdf.challenge,
                request.index_from_challenge,
                request.reward_chain_vdf.challenge,
            )
            msg = Message("new_signage_point_or_end_of_sub_slot", broadcast)
            await self.server.send_to_all_except([msg], NodeType.FULL_NODE, peer.peer_node_id)

            if peak is not None and peak.height > 2:
                # Makes sure to potentially update the difficulty if we are past the peak (into a new sub-slot)
                assert ip_sub_slot is not None
                if request.challenge_chain_vdf.challenge != ip_sub_slot.challenge_chain.get_hash():
                    difficulty = next_difficulty
                    sub_slot_iters = next_sub_slot_iters

            # Notify farmers of the new signage point
            broadcast_farmer = farmer_protocol.NewSignagePoint(
                request.challenge_chain_vdf.challenge,
                request.challenge_chain_vdf.output.get_hash(),
                request.reward_chain_vdf.output.get_hash(),
                difficulty,
                sub_slot_iters,
                request.index_from_challenge,
            )
            msg = Message("new_signage_point", broadcast_farmer)
            await self.server.send_to_all([msg], NodeType.FARMER)
        else:
            self.log.info("Signage point not added")

        return

    @peer_required
    @api_request
    async def respond_end_of_sub_slot(
        self, request: full_node_protocol.RespondEndOfSubSlot, peer: ws.WSChiaConnection
    ) -> Optional[Message]:
        if (
            self.full_node.full_node_store.get_sub_slot(
                request.end_of_slot_bundle.challenge_chain.challenge_chain_end_of_slot_vdf.challenge
            )
            is None
            and request.end_of_slot_bundle.challenge_chain.challenge_chain_end_of_slot_vdf.challenge
            != self.full_node.constants.FIRST_CC_CHALLENGE
        ):
            # If we don't have the prev, request the prev instead
            full_node_request = full_node_protocol.RequestSignagePointOrEndOfSubSlot(
                request.end_of_slot_bundle.challenge_chain.challenge_chain_end_of_slot_vdf.challenge,
                uint8(0),
                bytes([0] * 32),
            )
            return Message("request_signage_point_or_end_of_sub_slot", full_node_request)

        peak = self.full_node.blockchain.get_peak()
        if peak is not None and peak.height > 2:
            next_sub_slot_iters = self.full_node.blockchain.get_next_slot_iters(peak.header_hash, True)
            next_difficulty = self.full_node.blockchain.get_next_difficulty(peak.header_hash, True)
        else:
            next_sub_slot_iters = self.full_node.constants.SUB_SLOT_ITERS_STARTING
            next_difficulty = self.full_node.constants.DIFFICULTY_STARTING

        # Adds the sub slot and potentially get new infusions
        new_infusions = self.full_node.full_node_store.new_finished_sub_slot(
            request.end_of_slot_bundle, self.full_node.blockchain.sub_blocks, self.full_node.blockchain.get_peak()
        )
        # It may be an empty list, even if it's not None. Not None means added successfully
        if new_infusions is not None:
            self.log.info(
                f"Finished sub slot {request.end_of_slot_bundle.challenge_chain.get_hash()}, number of sub-slots: "
                f"{len(self.full_node.full_node_store.finished_sub_slots)}"
            )
            # Notify full nodes of the new sub-slot
            broadcast = full_node_protocol.NewSignagePointOrEndOfSubSlot(
                request.end_of_slot_bundle.challenge_chain.challenge_chain_end_of_slot_vdf.challenge,
                request.end_of_slot_bundle.challenge_chain.get_hash(),
                uint8(0),
                request.end_of_slot_bundle.reward_chain.end_of_slot_vdf.challenge,
            )
            msg = Message("new_signage_point_or_end_of_sub_slot", broadcast)
            await self.server.send_to_all_except([msg], NodeType.FULL_NODE, peer.peer_node_id)

            for infusion in new_infusions:
                await self.new_infusion_point_vdf(infusion)

            # Notify farmers of the new sub-slot
            broadcast_farmer = farmer_protocol.NewSignagePoint(
                request.end_of_slot_bundle.challenge_chain.get_hash(),
                request.end_of_slot_bundle.challenge_chain.get_hash(),
                request.end_of_slot_bundle.reward_chain.get_hash(),
                next_difficulty,
                next_sub_slot_iters,
                uint8(0),
            )
            msg = Message("new_signage_point", broadcast_farmer)
            await self.server.send_to_all([msg], NodeType.FARMER)
        else:
            self.log.info("End of slot not added")

    @peer_required
    @api_request
    async def request_mempool_transactions(
        self, request: full_node_protocol.RequestMempoolTransactions, peer: ws.WSChiaConnection
    ) -> Optional[Message]:
        received_filter = PyBIP158(bytearray(request.filter))

        items: List[MempoolItem] = await self.full_node.mempool_manager.get_items_not_in_filter(received_filter)

        for item in items:
            transaction = full_node_protocol.RespondTransaction(item.spend_bundle)
            msg = Message("respond_transaction", transaction)
            await peer.send_message(msg)
        return

    # FARMER PROTOCOL
    @api_request
    async def declare_proof_of_space(self, request: farmer_protocol.DeclareProofOfSpace) -> Optional[Message]:
        """
        Creates a block body and header, with the proof of space, coinbase, and fee targets provided
        by the farmer, and sends the hash of the header data back to the farmer.
        """
        if request.pool_target is None or request.pool_signature is None:
            raise ValueError("Adaptable pool protocol not yet available.")

        sp_vdfs: Optional[SignagePoint] = self.full_node.full_node_store.get_signage_point(request.challenge_chain_sp)

        if sp_vdfs is None:
            self.log.warning(f"Received proof of space for an unknown signage point {request.challenge_chain_sp}")
            return

        if request.signage_point_index == 0:
            cc_challenge_hash: bytes32 = request.challenge_chain_sp
        else:
            cc_challenge_hash: bytes32 = sp_vdfs.cc_vdf.challenge

        pos_sub_slot: Optional[Tuple[EndOfSubSlotBundle, int]] = None
        if request.challenge_hash != self.full_node.constants.FIRST_CC_CHALLENGE:
            # Checks that the proof of space is a response to a recent challenge and valid SP
            pos_sub_slot = self.full_node.full_node_store.get_sub_slot(cc_challenge_hash)
            if pos_sub_slot is None:
                self.log.warning(f"Received proof of space for an unknown sub slot: {request}")
                return
            total_iters_pos_slot: uint128 = pos_sub_slot[2]
        else:
            total_iters_pos_slot: uint128 = uint128(0)
        assert cc_challenge_hash == request.challenge_hash

        # Now we know that the proof of space has a signage point either:
        # 1. In the previous sub-slot of the peak (overflow)
        # 2. In the same sub-slot as the peak
        # 3. In a future sub-slot that we already know of

        # Checks that the proof of space is valid
        quality_string: Optional[bytes32] = request.proof_of_space.verify_and_get_quality_string(
            self.full_node.constants, cc_challenge_hash, request.challenge_chain_sp
        )
        assert quality_string is not None and len(quality_string) == 32

        # Grab best transactions from Mempool for given tip target
        async with self.full_node.blockchain.lock:
            peak: Optional[SubBlockRecord] = self.full_node.blockchain.get_peak()
            if peak is None:
                spend_bundle: Optional[SpendBundle] = None
            else:
                spend_bundle: Optional[SpendBundle] = await self.full_node.mempool_manager.create_bundle_from_mempool(
                    peak.header_hash
                )
        if peak is None or peak.height == 0:
            difficulty = self.full_node.constants.DIFFICULTY_STARTING
            sub_slot_iters = self.full_node.constants.SUB_SLOT_ITERS_STARTING
        else:
            assert pos_sub_slot is not None
            if pos_sub_slot[0].challenge_chain.new_difficulty is not None:
                difficulty = pos_sub_slot[0].challenge_chain.new_difficulty
                sub_slot_iters = pos_sub_slot[0].challenge_chain.new_sub_slot_iters
            else:
                difficulty = uint64(peak.weight - self.full_node.blockchain.sub_blocks[peak.prev_hash].weight)
                sub_slot_iters = peak.sub_slot_iters

        required_iters: uint64 = calculate_iterations_quality(
            quality_string,
            request.proof_of_space.size,
            difficulty,
            request.challenge_chain_sp,
        )
        sp_iters: uint64 = calculate_sp_iters(self.full_node.constants, sub_slot_iters, request.signage_point_index)
        ip_iters: uint64 = calculate_ip_iters(
            self.full_node.constants, sub_slot_iters, request.signage_point_index, required_iters
        )

        def get_plot_sig(to_sign, _) -> G2Element:
            if to_sign == request.challenge_chain_sp:
                return request.challenge_chain_sp_signature
            elif to_sign == request.reward_chain_sp:
                return request.reward_chain_sp_signature
            return G2Element.infinity()

        def get_pool_sig(to_sign, _) -> G2Element:
            return request.pool_signature

        finished_sub_slots: List[EndOfSubSlotBundle] = self.full_node.full_node_store.get_finished_sub_slots(
            peak, self.full_node.blockchain.sub_blocks, cc_challenge_hash
        )

        unfinished_block: Optional[UnfinishedBlock] = create_unfinished_block(
            self.full_node.constants,
            total_iters_pos_slot,
            sub_slot_iters,
            request.signage_point_index,
            sp_iters,
            ip_iters,
            request.proof_of_space,
            cc_challenge_hash,
            request.farmer_puzzle_hash,
            request.pool_target,
            get_plot_sig,
            get_pool_sig,
            sp_vdfs,
            uint64(int(time.time())),
            b"",
            spend_bundle,
            peak,
            self.full_node.blockchain.sub_blocks,
            finished_sub_slots,
        )
        prev_sb: Optional[SubBlockRecord] = self.full_node.blockchain.sub_blocks.get(
            unfinished_block.prev_header_hash, None
        )
        if prev_sb is not None:
            height = prev_sb.height + 1
        else:
            height = 0
        self.full_node.full_node_store.add_candidate_block(quality_string, height, unfinished_block)

        message = farmer_protocol.RequestSignedValues(
            quality_string,
            unfinished_block.foliage_sub_block.foliage_sub_block_data.get_hash(),
            unfinished_block.foliage_sub_block.foliage_block_hash,
        )
        return Message("request_signed_values", message)

    @api_request
    async def signed_values(self, farmer_request: farmer_protocol.SignedValues) -> Optional[Message]:
        """
        Signature of header hash, by the harvester. This is enough to create an unfinished
        block, which only needs a Proof of Time to be finished. If the signature is valid,
        we call the unfinished_block routine.
        """
        candidate: Optional[UnfinishedBlock] = self.full_node.full_node_store.get_candidate_block(
            farmer_request.quality_string
        )
        if candidate is None:
            self.log.warning(f"Quality string {farmer_request.quality_string} not found in database")
            return

        fsb2 = dataclasses.replace(
            candidate.foliage_sub_block,
            foliage_sub_block_signature=farmer_request.foliage_sub_block_signature,
        )
        fsb3 = dataclasses.replace(fsb2, foliage_block_signature=farmer_request.foliage_block_signature)
        new_candidate = dataclasses.replace(candidate, foliage_sub_block=fsb3)

        # Propagate to ourselves (which validates and does further propagations)
        request = full_node_protocol.RespondUnfinishedSubBlock(new_candidate)

        await self.full_node._respond_unfinished_sub_block(request, None)

    # TIMELORD PROTOCOL
    @api_request
    async def new_infusion_point_vdf(self, request: timelord_protocol.NewInfusionPointVDF) -> Optional[Message]:
        # Lookup unfinished blocks
        unfinished_block: Optional[UnfinishedBlock] = self.full_node.full_node_store.get_unfinished_block(
            request.unfinished_reward_hash
        )

        if unfinished_block is None:
            self.log.warning(
                f"Do not have unfinished reward chain block {request.unfinished_reward_hash}, cannot finish."
            )

        prev_sb: Optional[SubBlockRecord] = None
        if request.reward_chain_ip_vdf.challenge == self.full_node.constants.FIRST_RC_CHALLENGE:
            # Genesis
            assert request.challenge_chain_ip_vdf.challenge == self.full_node.constants.FIRST_RC_CHALLENGE
        else:
            # Find the prev block
            curr: Optional[SubBlockRecord] = self.full_node.blockchain.get_peak()
            if curr is None:
                self.log.warning(f"Have no blocks in chain, so can not complete block {unfinished_block.height}")
                return
            for _ in range(10):
                if curr.reward_infusion_new_challenge == request.reward_chain_ip_vdf.challenge:
                    # Found our prev block
                    prev_sb = curr
                    break
                if self.full_node.blockchain.sub_blocks.get(curr.prev_hash, None) is None:
                    return

            # If not found, cache keyed on prev block
            if prev_sb is None:
                self.full_node.full_node_store.add_to_future_ip(request)
                return

        sub_slot_iters, difficulty = get_sub_slot_iters_and_difficulty(
            self.full_node.constants,
            unfinished_block,
            self.full_node.blockchain.height_to_hash,
            prev_sb,
            self.full_node.blockchain.sub_blocks,
        )
        overflow = is_overflow_sub_block(
            self.full_node.constants, unfinished_block.reward_chain_sub_block.signage_point_index
        )
        if overflow:
            finished_sub_slots = self.full_node.full_node_store.get_finished_sub_slots(
                prev_sb,
                self.full_node.blockchain.sub_blocks,
                unfinished_block.reward_chain_sub_block.challenge_chain_sp_vdf.challenge,
                True,
            )
        else:
            finished_sub_slots = unfinished_block.finished_sub_slots

        if unfinished_block.reward_chain_sub_block.signage_point_index == 0:
            cc_sp_output_hash = unfinished_block.reward_chain_sub_block.pos_ss_cc_challenge_hash
        else:
            cc_sp_output_hash = unfinished_block.reward_chain_sub_block.challenge_chain_sp_vdf.output.get_hash()

        quality_string: Optional[
            bytes32
        ] = unfinished_block.reward_chain_sub_block.proof_of_space.verify_and_get_quality_string(
            self.full_node.constants,
            unfinished_block.reward_chain_sub_block.challenge_chain_sp_vdf.challenge,
            cc_sp_output_hash,
        )
        required_iters: uint64 = calculate_iterations_quality(
            quality_string,
            unfinished_block.reward_chain_sub_block.proof_of_space.size,
            difficulty,
            cc_sp_output_hash,
        )
        ip_iters = calculate_ip_iters(
            self.full_node.constants,
            sub_slot_iters,
            unfinished_block.reward_chain_sub_block.signage_point_index,
            required_iters,
        )
        modified_cc_ip_vdf = dataclasses.replace(request.challenge_chain_ip_vdf, number_of_iterations=ip_iters)
        block: FullBlock = unfinished_block_to_full_block(
            unfinished_block,
            modified_cc_ip_vdf,
            request.challenge_chain_ip_proof,
            request.reward_chain_ip_vdf,
            request.reward_chain_ip_proof,
            request.infused_challenge_chain_ip_vdf,
            request.infused_challenge_chain_ip_proof,
            finished_sub_slots,
            prev_sb,
            difficulty,
        )

        await self.respond_sub_block(full_node_protocol.RespondSubBlock(block))

    @peer_required
    @api_request
    async def new_signage_point_vdf(
        self, request: timelord_protocol.NewSignagePointVDF, peer: ws.WSChiaConnection
    ) -> Optional[Message]:
        full_node_message = full_node_protocol.RespondSignagePoint(
            request.index_from_challenge,
            request.challenge_chain_sp_vdf,
            request.challenge_chain_sp_proof,
            request.reward_chain_sp_vdf,
            request.reward_chain_sp_proof,
        )
        return await self.respond_signage_point(full_node_message, peer)

    @peer_required
    @api_request
    async def new_end_of_sub_slot_vdf(
        self, request: timelord_protocol.NewEndOfSubSlotVDF, peer: ws.WSChiaConnection
    ) -> Optional[Message]:
        # Calls our own internal message to handle the end of sub slot, and potentially broadcasts to other peers.
        full_node_message = full_node_protocol.RespondEndOfSubSlot(request.end_of_sub_slot_bundle)
        return await self.respond_end_of_sub_slot(full_node_message, peer)
