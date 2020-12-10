import dataclasses
import time

import src.server.ws_connection as ws
from typing import AsyncGenerator, List, Optional, Tuple, Callable, Dict
from chiabip158 import PyBIP158
from blspy import G2Element, AugSchemeMPL

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
from src.full_node.weight_proof import init_block_block_cache_mock, WeightProofHandler

from src.protocols import introducer_protocol, farmer_protocol, full_node_protocol, timelord_protocol, wallet_protocol
from src.protocols.wallet_protocol import RejectHeaderRequest
from src.server.outbound_message import Message, NodeType, OutboundMessage
from src.types.coin import Coin, hash_coin_list

from src.types.end_of_slot_bundle import EndOfSubSlotBundle
from src.types.full_block import FullBlock
from src.types.header_block import HeaderBlock

from src.types.mempool_inclusion_status import MempoolInclusionStatus
from src.types.mempool_item import MempoolItem
from src.types.pool_target import PoolTarget
from src.types.sized_bytes import bytes32
from src.types.spend_bundle import SpendBundle
from src.types.unfinished_block import UnfinishedBlock
from src.util.api_decorators import api_request, peer_required
from src.util.errors import ConsensusError
from src.util.ints import uint64, uint128, uint8, uint32
from src.types.peer_info import PeerInfo
from src.util.merkle_set import MerkleSet

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
    async def request_peers(self, _request: full_node_protocol.RequestPeers, peer: ws.WSChiaConnection):
        if peer.peer_server_port is None:
            return None
        peer_info = PeerInfo(peer.peer_host, peer.peer_server_port)
        if self.full_node.full_node_peers is not None:
            msg = await self.full_node.full_node_peers.request_peers(peer_info)
            return msg

    @peer_required
    @api_request
    async def respond_peers(
        self, request: introducer_protocol.RespondPeers, peer: ws.WSChiaConnection
    ) -> Optional[Message]:
        if self.full_node.full_node_peers is not None:
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
            return None

        # Not interested in less heavy peaks
        peak: Optional[SubBlockRecord] = self.full_node.blockchain.get_peak()
        if peak is not None and peak.weight > request.weight:
            return None

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
        return None

    @api_request
    async def request_transaction(self, request: full_node_protocol.RequestTransaction) -> Optional[Message]:
        """ Peer has requested a full transaction from us. """
        # Ignore if syncing
        if self.full_node.sync_store.get_sync_mode():
            return None
        spend_bundle = self.full_node.mempool_manager.get_spendbundle(request.transaction_id)
        if spend_bundle is None:
            return None

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
            return None

        async with self.full_node.blockchain.lock:
            # Ignore if we have already added this transaction
            if self.full_node.mempool_manager.get_spendbundle(tx.transaction.name()) is not None:
                return None
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
        return None

    @api_request
    async def request_proof_of_weight(self, request: full_node_protocol.RequestProofOfWeight) -> Optional[Message]:
        self.log.info(f"got weight proof request {request}")
        cache = await init_block_block_cache_mock(self.full_node.blockchain, uint32(0), request.total_number_of_blocks)
        wpf = WeightProofHandler(self.full_node.constants, cache)
        wpf.set_block_cache(cache)
        wp = wpf.create_proof_of_weight(
            uint32(self.full_node.constants.WEIGHT_PROOF_RECENT_BLOCKS), request.total_number_of_blocks, request.tip
        )
        return Message("respond_proof_of_weight", full_node_protocol.RespondProofOfWeight(wp))

    @api_request
    async def respond_proof_of_weight(self, response: full_node_protocol.RespondProofOfWeight) -> Optional[Message]:
        self.log.info(f"got weight proof response {response.wp}")
        cache = await init_block_block_cache_mock(
            self.full_node.blockchain, uint32(0), self.full_node.blockchain.peak_height
        )
        wpf = WeightProofHandler(self.full_node.constants, cache)
        wpf.set_block_cache(cache)
        return await wpf.validate_weight_proof(response.wp)

    @api_request
    async def request_sub_block(self, request: full_node_protocol.RequestSubBlock) -> Optional[Message]:
        if request.sub_height not in self.full_node.blockchain.sub_height_to_hash:
            return None
        block: Optional[FullBlock] = await self.full_node.block_store.get_full_block(
            self.full_node.blockchain.sub_height_to_hash[request.sub_height]
        )
        if block is not None:
            if not request.include_transaction_block:
                block = dataclasses.replace(block, transactions_generator=None)
            msg = Message("respond_sub_block", full_node_protocol.RespondSubBlock(block))
            return msg
        return None

    @api_request
    @peer_required
    async def respond_sub_block(
        self, respond_sub_block: full_node_protocol.RespondSubBlock, peer: ws.WSChiaConnection
    ) -> Optional[Message]:
        """
        Receive a full block from a peer full node (or ourselves).
        """
        if self.full_node.sync_store.get_sync_mode():
            return await self.full_node.respond_sub_block(respond_sub_block, peer)
        else:
            async with self.full_node.timelord_lock:
                return await self.full_node.respond_sub_block(respond_sub_block, peer)

    @api_request
    async def new_unfinished_sub_block(
        self, new_unfinished_sub_block: full_node_protocol.NewUnfinishedSubBlock
    ) -> Optional[Message]:
        # Ignore if syncing
        if self.full_node.sync_store.get_sync_mode():
            return None
        if (
            self.full_node.full_node_store.get_unfinished_block(new_unfinished_sub_block.unfinished_reward_hash)
            is not None
        ):
            return None

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
                "respond_unfinished_sub_block",
                full_node_protocol.RespondUnfinishedSubBlock(unfinished_block),
            )
            return msg
        return None

    @peer_required
    @api_request
    async def respond_unfinished_sub_block(
        self, respond_unfinished_sub_block: full_node_protocol.RespondUnfinishedSubBlock, peer: ws.WSChiaConnection
    ) -> Optional[Message]:
        await self.full_node.respond_unfinished_sub_block(respond_unfinished_sub_block, peer)
        return None

    @api_request
    async def new_signage_point_or_end_of_sub_slot(
        self, new_sp: full_node_protocol.NewSignagePointOrEndOfSubSlot
    ) -> Optional[Message]:
        # Ignore if syncing
        if self.full_node.sync_store.get_sync_mode():
            return None
        if (
            self.full_node.full_node_store.get_signage_point_by_index(
                new_sp.challenge_hash, new_sp.index_from_challenge, new_sp.last_rc_infusion
            )
            is not None
        ):
            return None
        if self.full_node.full_node_store.have_newer_signage_point(
            new_sp.challenge_hash, new_sp.index_from_challenge, new_sp.last_rc_infusion
        ):
            return None

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
            sub_slot: Optional[Tuple[EndOfSubSlotBundle, int, uint128]] = self.full_node.full_node_store.get_sub_slot(
                request.challenge_hash
            )
            if sub_slot is not None:
                return Message("respond_end_of_sub_slot", full_node_protocol.RespondEndOfSubSlot(sub_slot[0]))
        else:
            if self.full_node.full_node_store.get_sub_slot(request.challenge_hash) is None:
                if request.challenge_hash != self.full_node.constants.FIRST_CC_CHALLENGE:
                    self.log.warning(f"Don't have challenge hash {request.challenge_hash}")

            sp: Optional[SignagePoint] = self.full_node.full_node_store.get_signage_point_by_index(
                request.challenge_hash, request.index_from_challenge, request.last_rc_infusion
            )
            if sp is not None:
                assert (
                    sp.cc_vdf is not None
                    and sp.cc_proof is not None
                    and sp.rc_vdf is not None
                    and sp.rc_proof is not None
                )
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
        return None

    @peer_required
    @api_request
    async def respond_signage_point(
        self, request: full_node_protocol.RespondSignagePoint, peer: ws.WSChiaConnection
    ) -> Optional[Message]:
        peak = self.full_node.blockchain.get_peak()
        if peak is not None and peak.sub_block_height > self.full_node.constants.MAX_SUB_SLOT_SUB_BLOCKS:
            sub_slot_iters = peak.sub_slot_iters
            difficulty = uint64(peak.weight - self.full_node.blockchain.sub_blocks[peak.prev_hash].weight)
            next_sub_slot_iters = self.full_node.blockchain.get_next_slot_iters(peak.header_hash, True)
            next_difficulty = self.full_node.blockchain.get_next_difficulty(peak.header_hash, True)
            sub_slots_for_peak = await self.full_node.blockchain.get_sp_and_ip_sub_slots(peak.header_hash)
            assert sub_slots_for_peak is not None
            ip_sub_slot: Optional[EndOfSubSlotBundle] = sub_slots_for_peak[1]
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
                f"⏲️  Finished signage point {request.index_from_challenge}/"
                f"{self.full_node.constants.NUM_SPS_SUB_SLOT}: "
                f"{request.challenge_chain_vdf.output.get_hash()} "
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

            if peak is not None and peak.sub_block_height > self.full_node.constants.MAX_SUB_SLOT_SUB_BLOCKS:
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
            self.log.warning(f"Signage point not added {request}")

        return None

    @peer_required
    @api_request
    async def respond_end_of_sub_slot(
        self, request: full_node_protocol.RespondEndOfSubSlot, peer: ws.WSChiaConnection
    ) -> Optional[Message]:

        async with self.full_node.timelord_lock:
            fetched_ss = self.full_node.full_node_store.get_sub_slot(
                request.end_of_slot_bundle.challenge_chain.challenge_chain_end_of_slot_vdf.challenge
            )
            if (
                (fetched_ss is None)
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
            if peak is not None and peak.sub_block_height > 2:
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
                    f"⏲️  Finished sub slot {request.end_of_slot_bundle.challenge_chain.get_hash()}, "
                    f"number of sub-slots: {len(self.full_node.full_node_store.finished_sub_slots)}, "
                    f"RC hash: {request.end_of_slot_bundle.reward_chain.get_hash()}, "
                    f"Deficit {request.end_of_slot_bundle.reward_chain.deficit}"
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
                self.log.warning(f"End of slot not added {request}")
        return None

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
        return None

    # FARMER PROTOCOL
    @api_request
    async def declare_proof_of_space(self, request: farmer_protocol.DeclareProofOfSpace) -> Optional[Message]:
        """
        Creates a block body and header, with the proof of space, coinbase, and fee targets provided
        by the farmer, and sends the hash of the header data back to the farmer.
        """
        async with self.full_node.timelord_lock:
            if request.pool_target is None or request.pool_signature is None:
                raise ValueError("Adaptable pool protocol not yet available.")

            sp_vdfs: Optional[SignagePoint] = self.full_node.full_node_store.get_signage_point(
                request.challenge_chain_sp
            )

            if sp_vdfs is None:
                self.log.warning(f"Received proof of space for an unknown signage point {request.challenge_chain_sp}")
                return None
            if request.signage_point_index > 0:
                assert sp_vdfs.rc_vdf is not None
                if sp_vdfs.rc_vdf.output.get_hash() != request.reward_chain_sp:
                    self.log.info(
                        f"Received proof of space for a potentially old signage point {request.challenge_chain_sp}. "
                        f"Current sp: {sp_vdfs.rc_vdf.output.get_hash()}"
                    )
                    return None

            if request.signage_point_index == 0:
                cc_challenge_hash: bytes32 = request.challenge_chain_sp
            else:
                assert sp_vdfs.cc_vdf is not None
                cc_challenge_hash = sp_vdfs.cc_vdf.challenge

            pos_sub_slot: Optional[Tuple[EndOfSubSlotBundle, int, uint128]] = None
            if request.challenge_hash != self.full_node.constants.FIRST_CC_CHALLENGE:
                # Checks that the proof of space is a response to a recent challenge and valid SP
                pos_sub_slot = self.full_node.full_node_store.get_sub_slot(cc_challenge_hash)
                if pos_sub_slot is None:
                    self.log.warning(f"Received proof of space for an unknown sub slot: {request}")
                    return None
                total_iters_pos_slot: uint128 = pos_sub_slot[2]
            else:
                total_iters_pos_slot = uint128(0)
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
                    spend_bundle = await self.full_node.mempool_manager.create_bundle_from_mempool(peak.header_hash)
            if peak is None or peak.sub_block_height <= self.full_node.constants.MAX_SUB_SLOT_SUB_BLOCKS:
                difficulty = self.full_node.constants.DIFFICULTY_STARTING
                sub_slot_iters = self.full_node.constants.SUB_SLOT_ITERS_STARTING
            else:
                assert pos_sub_slot is not None
                if pos_sub_slot[0].challenge_chain.new_difficulty is not None:
                    assert pos_sub_slot[0].challenge_chain.new_sub_slot_iters is not None
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

            def get_pool_sig(_1, _2) -> G2Element:
                return request.pool_signature

            # Get the previous sub block at the signage point
            if peak is not None:
                curr = peak
                while curr.total_iters > (total_iters_pos_slot + sp_iters) and curr.sub_block_height > 0:
                    curr = self.full_node.blockchain.sub_blocks[curr.prev_hash]
                if curr.total_iters > (total_iters_pos_slot + sp_iters):
                    pool_target = PoolTarget(self.full_node.constants.GENESIS_PRE_FARM_POOL_PUZZLE_HASH, uint32(0))
                    prev_sb = None
                else:
                    self.log.warning(
                        f"Making a non-genesis block. curr total iters{curr.total_iters} {total_iters_pos_slot + sp_iters}"
                    )
                    pool_target = request.pool_target
                    prev_sb = curr
            else:
                pool_target = PoolTarget(self.full_node.constants.GENESIS_PRE_FARM_POOL_PUZZLE_HASH, uint32(0))
                prev_sb = None
            try:
                finished_sub_slots: List[EndOfSubSlotBundle] = self.full_node.full_node_store.get_finished_sub_slots(
                    prev_sb, self.full_node.blockchain.sub_blocks, cc_challenge_hash
                )
            except ValueError as e:
                self.log.warning(f"Value Error: {e}")
                return None
            if len(finished_sub_slots) == 0:
                if prev_sb is not None:
                    if request.signage_point_index == 0:
                        # No need to get correct block since SP RC is not validated for this sub block
                        pass
                    else:
                        assert sp_vdfs.rc_vdf is not None
                        found = False
                        attempts = 0
                        while prev_sb is not None and attempts < 10:
                            if prev_sb.reward_infusion_new_challenge == sp_vdfs.rc_vdf.challenge:
                                found = True
                                break
                            if (
                                prev_sb.finished_reward_slot_hashes is not None
                                and len(prev_sb.finished_reward_slot_hashes) > 0
                            ):
                                if prev_sb.finished_reward_slot_hashes[-1] == sp_vdfs.rc_vdf.challenge:
                                    prev_sb = self.full_node.blockchain.sub_blocks.get(prev_sb.prev_hash, None)
                                    found = True
                                    break
                            prev_sb = self.full_node.blockchain.sub_blocks.get(prev_sb.prev_hash, None)
                            attempts += 1
                        if not found:
                            self.log.info("Did not find a previous block with the correct reward chain hash")
                            return None
            elif request.signage_point_index > 0:
                assert sp_vdfs.rc_vdf is not None
                assert finished_sub_slots[-1].reward_chain.get_hash() == sp_vdfs.rc_vdf.challenge

            unfinished_block: UnfinishedBlock = create_unfinished_block(
                self.full_node.constants,
                total_iters_pos_slot,
                sub_slot_iters,
                request.signage_point_index,
                sp_iters,
                ip_iters,
                request.proof_of_space,
                cc_challenge_hash,
                request.farmer_puzzle_hash,
                pool_target,
                get_plot_sig,
                get_pool_sig,
                sp_vdfs,
                uint64(int(time.time())),
                b"",
                spend_bundle,
                prev_sb,
                self.full_node.blockchain.sub_blocks,
                finished_sub_slots,
            )
            if prev_sb is not None:
                height: uint32 = uint32(prev_sb.sub_block_height + 1)
            else:
                height = uint32(0)
            self.full_node.full_node_store.add_candidate_block(quality_string, height, unfinished_block)

            foliage_sb_data_hash = unfinished_block.foliage_sub_block.foliage_sub_block_data.get_hash()
            if unfinished_block.is_block():
                foliage_block_hash = unfinished_block.foliage_sub_block.foliage_block_hash
            else:
                foliage_block_hash = bytes([0] * 32)

            message = farmer_protocol.RequestSignedValues(
                quality_string,
                foliage_sb_data_hash,
                foliage_block_hash,
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
            return None

        if not AugSchemeMPL.verify(
            candidate.reward_chain_sub_block.proof_of_space.plot_public_key,
            candidate.foliage_sub_block.foliage_sub_block_data.get_hash(),
            farmer_request.foliage_sub_block_signature,
        ):
            self.log.warning("Signature not valid. There might be a collision in plots. Ignore this during tests.")
            return None

        fsb2 = dataclasses.replace(
            candidate.foliage_sub_block,
            foliage_sub_block_signature=farmer_request.foliage_sub_block_signature,
        )
        if candidate.is_block():
            fsb2 = dataclasses.replace(fsb2, foliage_block_signature=farmer_request.foliage_block_signature)

        new_candidate = dataclasses.replace(candidate, foliage_sub_block=fsb2)
        if not self.full_node.has_valid_pool_sig(new_candidate):
            self.log.warning("Trying to make a pre-farm block but height is not 0")
            return None

        # Propagate to ourselves (which validates and does further propagations)
        request = full_node_protocol.RespondUnfinishedSubBlock(new_candidate)

        await self.full_node.respond_unfinished_sub_block(request, None)
        return None

    # TIMELORD PROTOCOL
    @api_request
    async def new_infusion_point_vdf(self, request: timelord_protocol.NewInfusionPointVDF) -> Optional[Message]:
        # Lookup unfinished blocks

        async with self.full_node.timelord_lock:
            unfinished_block: Optional[UnfinishedBlock] = self.full_node.full_node_store.get_unfinished_block(
                request.unfinished_reward_hash
            )

            if unfinished_block is None:
                self.log.warning(
                    f"Do not have unfinished reward chain block {request.unfinished_reward_hash}, cannot finish."
                )
                return None

            prev_sb: Optional[SubBlockRecord] = None

            target_rc_hash = request.reward_chain_ip_vdf.challenge

            # Backtracks through end of slot objects, should work for multiple empty sub slots
            for eos, _, _ in reversed(self.full_node.full_node_store.finished_sub_slots):
                if eos is not None and eos.reward_chain.get_hash() == target_rc_hash:
                    target_rc_hash = eos.reward_chain.end_of_slot_vdf.challenge
            if target_rc_hash == self.full_node.constants.FIRST_RC_CHALLENGE:
                prev_sb = None
            else:
                # Find the prev block, starts looking backwards from the peak
                # TODO: should we look at end of slots too?
                curr: Optional[SubBlockRecord] = self.full_node.blockchain.get_peak()

                for _ in range(10):
                    if curr is None:
                        break
                    if curr.reward_infusion_new_challenge == target_rc_hash:
                        # Found our prev block
                        prev_sb = curr
                        break
                    curr = self.full_node.blockchain.sub_blocks.get(curr.prev_hash, None)

                # If not found, cache keyed on prev block
                if prev_sb is None:
                    self.full_node.full_node_store.add_to_future_ip(request)
                    self.log.warning(f"Previous block is None, infusion point {request.reward_chain_ip_vdf.challenge}")
                    return None

            sub_slot_iters, difficulty = get_sub_slot_iters_and_difficulty(
                self.full_node.constants,
                unfinished_block,
                self.full_node.blockchain.sub_height_to_hash,
                prev_sb,
                self.full_node.blockchain.sub_blocks,
            )
            overflow = is_overflow_sub_block(
                self.full_node.constants, unfinished_block.reward_chain_sub_block.signage_point_index
            )
            finished_sub_slots = self.full_node.full_node_store.get_finished_sub_slots(
                prev_sb,
                self.full_node.blockchain.sub_blocks,
                unfinished_block.reward_chain_sub_block.pos_ss_cc_challenge_hash,
                overflow,
            )

            if (
                unfinished_block.reward_chain_sub_block.pos_ss_cc_challenge_hash
                == self.full_node.constants.FIRST_CC_CHALLENGE
            ):
                sub_slot_start_iters = uint128(0)
            else:
                ss_res = self.full_node.full_node_store.get_sub_slot(
                    unfinished_block.reward_chain_sub_block.pos_ss_cc_challenge_hash
                )
                if ss_res is None:
                    self.log.warning(
                        f"Do not have sub slot {unfinished_block.reward_chain_sub_block.pos_ss_cc_challenge_hash}"
                    )
                    return None
                _, _, sub_slot_start_iters = ss_res
            sp_total_iters = uint128(
                sub_slot_start_iters
                + calculate_sp_iters(
                    self.full_node.constants,
                    sub_slot_iters,
                    unfinished_block.reward_chain_sub_block.signage_point_index,
                )
            )

            block: FullBlock = unfinished_block_to_full_block(
                unfinished_block,
                request.challenge_chain_ip_vdf,
                request.challenge_chain_ip_proof,
                request.reward_chain_ip_vdf,
                request.reward_chain_ip_proof,
                request.infused_challenge_chain_ip_vdf,
                request.infused_challenge_chain_ip_proof,
                finished_sub_slots,
                prev_sb,
                self.full_node.blockchain.sub_blocks,
                sp_total_iters,
                difficulty,
            )
            first_ss_new_epoch = False
            if not self.full_node.has_valid_pool_sig(block):
                self.log.warning("Trying to make a pre-farm block but height is not 0")
                return None
            if len(block.finished_sub_slots) > 0:
                if block.finished_sub_slots[0].challenge_chain.new_difficulty is not None:
                    first_ss_new_epoch = True
            else:
                curr = prev_sb
                while (curr is not None) and not curr.first_in_sub_slot:
                    curr = self.full_node.blockchain.sub_blocks.get(curr.prev_hash, None)
                if (
                    curr is not None
                    and curr.first_in_sub_slot
                    and curr.sub_epoch_summary_included is not None
                    and curr.sub_epoch_summary_included.new_difficulty is not None
                ):
                    first_ss_new_epoch = True
            if first_ss_new_epoch and overflow:
                # No overflow sub-blocks in the first sub-slot of each epoch
                return None
            try:
                await self.full_node.respond_sub_block(full_node_protocol.RespondSubBlock(block))
            except ConsensusError as e:
                self.log.warning(f"Consensus error validating sub-block: {e}")
        return None

    @peer_required
    @api_request
    async def new_signage_point_vdf(
        self, request: timelord_protocol.NewSignagePointVDF, peer: ws.WSChiaConnection
    ) -> None:
        full_node_message = full_node_protocol.RespondSignagePoint(
            request.index_from_challenge,
            request.challenge_chain_sp_vdf,
            request.challenge_chain_sp_proof,
            request.reward_chain_sp_vdf,
            request.reward_chain_sp_proof,
        )
        await self.respond_signage_point(full_node_message, peer)

    @peer_required
    @api_request
    async def new_end_of_sub_slot_vdf(
        self, request: timelord_protocol.NewEndOfSubSlotVDF, peer: ws.WSChiaConnection
    ) -> Optional[Message]:
        # Calls our own internal message to handle the end of sub slot, and potentially broadcasts to other peers.
        full_node_message = full_node_protocol.RespondEndOfSubSlot(request.end_of_sub_slot_bundle)
        await self.respond_end_of_sub_slot(full_node_message, peer)
        return None

    @api_request
    async def request_sub_block_header(self, request: wallet_protocol.RequestSubBlockHeader) -> Optional[Message]:
        if request.sub_height not in self.full_node.blockchain.sub_height_to_hash:
            msg = Message("reject_sub_block_header", RejectHeaderRequest(request.sub_height))
            return msg
        block: Optional[FullBlock] = await self.full_node.block_store.get_full_block(
            self.full_node.blockchain.sub_height_to_hash[request.sub_height]
        )
        if block is not None:
            header_block: HeaderBlock = await block.get_block_header()
            msg = Message("respond_sub_block_header", wallet_protocol.RespondSubBlockHeader(header_block))
            return msg
        return None

    @api_request
    async def request_additions(self, request: wallet_protocol.RequestAdditions) -> Optional[Message]:
        block: Optional[FullBlock] = await self.full_node.block_store.get_full_block(request.header_hash)
        if (
            block is None
            or block.is_block() is False
            or block.sub_block_height not in self.full_node.blockchain.sub_height_to_hash
        ):
            reject = wallet_protocol.RejectAdditionsRequest(request.sub_height, request.header_hash)

            msg = Message("reject_additions_request", reject)
            return msg

        assert block is not None and block.foliage_block is not None
        _, additions = await block.tx_removals_and_additions()
        puzzlehash_coins_map: Dict[bytes32, List[Coin]] = {}
        for coin in additions + list(block.get_included_reward_coins()):
            if coin.puzzle_hash in puzzlehash_coins_map:
                puzzlehash_coins_map[coin.puzzle_hash].append(coin)
            else:
                puzzlehash_coins_map[coin.puzzle_hash] = [coin]

        coins_map: List[Tuple[bytes32, List[Coin]]] = []
        proofs_map: List[Tuple[bytes32, bytes, Optional[bytes]]] = []

        if request.puzzle_hashes is None:
            for puzzle_hash, coins in puzzlehash_coins_map.items():
                coins_map.append((puzzle_hash, coins))
            response = wallet_protocol.RespondAdditions(block.sub_block_height, block.header_hash, coins_map, None)
        else:
            # Create addition Merkle set
            addition_merkle_set = MerkleSet()
            # Addition Merkle set contains puzzlehash and hash of all coins with that puzzlehash
            for puzzle, coins in puzzlehash_coins_map.items():
                addition_merkle_set.add_already_hashed(puzzle)
                addition_merkle_set.add_already_hashed(hash_coin_list(coins))

            assert addition_merkle_set.get_root() == block.foliage_block.additions_root
            for puzzle_hash in request.puzzle_hashes:
                result, proof = addition_merkle_set.is_included_already_hashed(puzzle_hash)
                if puzzle_hash in puzzlehash_coins_map:
                    coins_map.append((puzzle_hash, puzzlehash_coins_map[puzzle_hash]))
                    hash_coin_str = hash_coin_list(puzzlehash_coins_map[puzzle_hash])
                    result_2, proof_2 = addition_merkle_set.is_included_already_hashed(hash_coin_str)
                    assert result
                    assert result_2
                    proofs_map.append((puzzle_hash, proof, proof_2))
                else:
                    coins_map.append((puzzle_hash, []))
                    assert not result
                    proofs_map.append((puzzle_hash, proof, None))
            response = wallet_protocol.RespondAdditions(
                block.sub_block_height, block.header_hash, coins_map, proofs_map
            )
        msg = Message("respond_additions", response)
        return msg

    @api_request
    async def request_removals(self, request: wallet_protocol.RequestRemovals) -> Optional[Message]:
        block: Optional[FullBlock] = await self.full_node.block_store.get_full_block(request.header_hash)
        if (
            block is None
            or block.is_block() is False
            or block.sub_block_height != request.sub_height
            or block.sub_block_height not in self.full_node.blockchain.sub_height_to_hash
            or self.full_node.blockchain.sub_height_to_hash[block.sub_block_height] != block.header_hash
        ):
            reject = wallet_protocol.RejectRemovalsRequest(request.sub_height, request.header_hash)
            msg = Message("reject_removals_request", reject)
            return msg

        assert block is not None and block.foliage_block is not None
        all_removals, _ = await block.tx_removals_and_additions()

        coins_map: List[Tuple[bytes32, Optional[Coin]]] = []
        proofs_map: List[Tuple[bytes32, bytes]] = []

        # If there are no transactions, respond with empty lists
        if block.transactions_generator is None:
            proofs: Optional[List]
            if request.coin_names is None:
                proofs = None
            else:
                proofs = []
            response = wallet_protocol.RespondRemovals(block.height, block.header_hash, [], proofs)
        elif request.coin_names is None or len(request.coin_names) == 0:
            for removal in all_removals:
                cr = await self.full_node.coin_store.get_coin_record(removal)
                assert cr is not None
                coins_map.append((cr.coin.name(), cr.coin))
            response = wallet_protocol.RespondRemovals(block.height, block.header_hash, coins_map, None)
        else:
            assert block.transactions_generator
            removal_merkle_set = MerkleSet()
            for coin_name in all_removals:
                removal_merkle_set.add_already_hashed(coin_name)
            assert removal_merkle_set.get_root() == block.foliage_block.additions_root
            for coin_name in request.coin_names:
                result, proof = removal_merkle_set.is_included_already_hashed(coin_name)
                proofs_map.append((coin_name, proof))
                if coin_name in all_removals:
                    cr = await self.full_node.coin_store.get_coin_record(coin_name)
                    assert cr is not None
                    coins_map.append((coin_name, cr.coin))
                    assert result
                else:
                    coins_map.append((coin_name, None))
                    assert not result
            response = wallet_protocol.RespondRemovals(block.height, block.header_hash, coins_map, proofs_map)

        msg = Message("respond_removals", response)
        return msg
