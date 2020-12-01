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
    async def request_sub_block(self, request_block: full_node_protocol.RequestSubBlock) -> Optional[Message]:
        if request_block.height not in self.full_node.blockchain.height_to_hash:
            return
        block: Optional[FullBlock] = await self.full_node.block_store.get_full_block(
            self.full_node.blockchain.height_to_hash[request_block.height]
        )
        if block is not None:
            if not request_block.include_transaction_block:
                block = dataclasses.replace(block, transactions_generator=None)
            msg = Message("respond_block", full_node_protocol.RespondSubBlock(block))
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
                return Message("respond_end_of_slot", full_node_protocol.RespondEndOfSubSlot(sub_slot[0]))
            else:
                self.log.warning("")
        else:
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

    @peer_required
    @api_request
    async def respond_signage_point(
        self, request: full_node_protocol.RespondSignagePoint, peer: ws.WSChiaConnection
    ) -> Optional[Message]:
        peak = self.full_node.blockchain.get_peak()
        next_sub_slot_iters = self.full_node.blockchain.get_next_slot_iters(peak.get_hash(), True)

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
            broadcast = full_node_protocol.NewSignagePointOrEndOfSubSlot(
                request.challenge_chain_vdf.challenge_hash,
                request.index_from_challenge,
                request.reward_chain_vdf.challenge_hash,
            )
            msg = Message("new_signage_point_or_end_of_sub_slot", broadcast)
            await self.server.send_to_all_except([msg], NodeType.FULL_NODE, peer.peer_node_id)

        return

    @peer_required
    @api_request
    async def respond_end_of_sub_slot(
        self, request: full_node_protocol.RespondEndOfSubSlot, peer: ws.WSChiaConnection
    ) -> Optional[Message]:

        new_infusions = self.full_node.full_node_store.new_finished_sub_slot(
            request.end_of_slot_bundle, self.full_node.blockchain.sub_blocks, self.full_node.blockchain.get_peak()
        )

        if new_infusions is not None:
            print("Added!")
            broadcast = full_node_protocol.NewSignagePointOrEndOfSubSlot(
                request.end_of_slot_bundle.challenge_chain.get_hash(),
                uint8(0),
                request.end_of_slot_bundle.reward_chain.end_of_slot_vdf.challenge_hash,
            )
            msg = Message("new_signage_point_or_end_of_sub_slot", broadcast)
            await self.server.send_to_all_except([msg], NodeType.FULL_NODE, peer.peer_node_id)

            for infusion in new_infusions:
                await self.new_infusion_point_vdf(infusion)

        return

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

        # Checks that the proof of space is a response to a recent challenge and valid SP
        pos_sub_slot: Optional[Tuple[EndOfSubSlotBundle, int]] = self.full_node.full_node_store.get_sub_slot(
            request.proof_of_space.challenge_hash
        )
        sp_vdfs: Optional[SignagePoint] = self.full_node.full_node_store.get_signage_point(request.challenge_chain_sp)

        if sp_vdfs is None or pos_sub_slot is None:
            self.log.warning(f"Received proof of space for an unknown signage point: {request}")
            return

        # Now we know that the proof of space has a signage point either:
        # 1. In the previous sub-slot of the peak (overflow)
        # 2. In the same sub-slot as the peak
        # 3. In a future sub-slot that we already know of

        # Checks that the proof of space is valid
        quality_string: Optional[bytes32] = request.proof_of_space.verify_and_get_quality_string(
            self.full_node.constants, request.challenge_hash, request.challenge_chain_sp
        )
        assert len(quality_string) == 32

        # Grab best transactions from Mempool for given tip target
        async with self.full_node.blockchain.lock:
            peak: Optional[SubBlockRecord] = self.full_node.blockchain.get_peak()
            if peak is None:
                spend_bundle: Optional[SpendBundle] = None
            else:
                spend_bundle: Optional[SpendBundle] = await self.full_node.mempool_manager.create_bundle_from_mempool(
                    peak.header_hash
                )
        if pos_sub_slot[0].challenge_chain.new_difficulty is not None:
            difficulty = pos_sub_slot[0].challenge_chain.new_difficulty
            sub_slot_iters = pos_sub_slot[0].challenge_chain.new_sub_slot_iters
        else:
            if peak is None or peak.height == 0:
                difficulty = self.full_node.constants.DIFFICULTY_STARTING
                sub_slot_iters = self.full_node.constants.SUB_SLOT_ITERS_STARTING
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
        total_iters_pos_slot: uint128 = pos_sub_slot[2]

        def get_plot_sig(to_sign, _) -> G2Element:
            if to_sign == request.challenge_chain_sp:
                return request.challenge_chain_sp_signature
            if to_sign == request.reward_chain_sp:
                return request.reward_chain_sp_signature
            return G2Element.infinity()

        finished_sub_slots: List[EndOfSubSlotBundle] = self.full_node.full_node_store.get_finished_sub_slots(
            peak, self.full_node.blockchain.sub_blocks, request.proof_of_space.challenge_hash
        )

        unfinished_block: Optional[UnfinishedBlock] = create_unfinished_block(
            self.full_node.constants,
            total_iters_pos_slot,
            sub_slot_iters,
            request.signage_point_index,
            sp_iters,
            ip_iters,
            request.proof_of_space,
            pos_sub_slot[0].challenge_chain.get_hash(),
            request.farmer_puzzle_hash,
            request.pool_target,
            get_plot_sig,
            get_plot_sig,
            sp_vdfs,
            uint64(int(time.time())),
            b"",
            spend_bundle,
            peak,
            self.full_node.blockchain.sub_blocks,
            finished_sub_slots,
        )
        self.full_node.full_node_store.add_candidate_block(quality_string, unfinished_block)

        message = farmer_protocol.RequestSignedValues(
            quality_string,
            unfinished_block.foliage_sub_block.get_hash(),
            unfinished_block.foliage_block.get_hash(),
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
        if request.reward_chain_ip_vdf.challenge_hash == self.full_node.constants.FIRST_RC_CHALLENGE:
            # Genesis
            assert unfinished_block.height == 0
        else:
            # Find the prev block
            curr: Optional[SubBlockRecord] = self.full_node.blockchain.get_peak()
            if curr is None:
                self.log.warning(f"Have no blocks in chain, so can not complete block {unfinished_block.height}")
                return
            num_sb_checked = 0
            while num_sb_checked < 10:
                if curr.reward_infusion_new_challenge == request.reward_chain_ip_vdf.challenge_hash:
                    # Found our prev block
                    prev_sb = curr
                    break
                curr = self.full_node.blockchain.sub_blocks.get(curr.prev_hash, None)
                if curr is None:
                    return
                num_sb_checked += 1

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
                unfinished_block.reward_chain_sub_block.proof_of_space.challenge_hash,
                True,
            )
        else:
            finished_sub_slots = unfinished_block.finished_sub_slots

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

    # WALLET PROTOCOL
    # @api_request
    # async def send_transaction(self, tx: wallet_protocol.SendTransaction) -> OutboundMessageGenerator:
    #     # Ignore if syncing
    #     if self.sync_store.get_sync_mode():
    #         status = MempoolInclusionStatus.FAILED
    #         error: Optional[Err] = Err.UNKNOWN
    #     else:
    #         async with self.blockchain.lock:
    #             cost, status, error = await self.mempool_manager.add_spendbundle(tx.transaction)
    #             if status == MempoolInclusionStatus.SUCCESS:
    #                 self.log.info(f"Added transaction to mempool: {tx.transaction.name()}")
    #                 # Only broadcast successful transactions, not pending ones. Otherwise it's a DOS
    #                 # vector.
    #                 fees = tx.transaction.fees()
    #                 assert fees >= 0
    #                 assert cost is not None
    #                 new_tx = full_node_protocol.NewTransaction(
    #                     tx.transaction.name(),
    #                     cost,
    #                     uint64(tx.transaction.fees()),
    #                 )
    #                 yield OutboundMessage(
    #                     NodeType.FULL_NODE,
    #                     Message("new_transaction", new_tx),
    #                     Delivery.BROADCAST_TO_OTHERS,
    #                 )
    #             else:
    #                 self.log.warning(
    #                     f"Wasn't able to add transaction with id {tx.transaction.name()}, "
    #                     f"status {status} error: {error}"
    #                 )
    #
    #     error_name = error.name if error is not None else None
    #     if status == MempoolInclusionStatus.SUCCESS:
    #         response = wallet_protocol.TransactionAck(tx.transaction.name(), status, error_name)
    #     else:
    #         # If if failed/pending, but it previously succeeded (in mempool), this is idempotence, return SUCCESS
    #         if self.mempool_manager.get_spendbundle(tx.transaction.name()) is not None:
    #             response = wallet_protocol.TransactionAck(tx.transaction.name(), MempoolInclusionStatus.SUCCESS, None)
    #         else:
    #             response = wallet_protocol.TransactionAck(tx.transaction.name(), status, error_name)
    #     yield OutboundMessage(NodeType.WALLET, Message("transaction_ack", response), Delivery.RESPOND)
    #
    # @api_request
    # async def request_header(self, request: wallet_protocol.RequestHeader) -> OutboundMessageGenerator:
    #     full_block: Optional[FullBlock] = await self.block_store.get_block(request.header_hash)
    #     if full_block is not None:
    #         header_block: Optional[HeaderBlock] = full_block.get_header_block()
    #         if header_block is not None and header_block.height == request.height:
    #             response = wallet_protocol.RespondHeader(header_block, full_block.transactions_filter)
    #             yield OutboundMessage(
    #                 NodeType.WALLET,
    #                 Message("respond_header", response),
    #                 Delivery.RESPOND,
    #             )
    #             return
    #     reject = wallet_protocol.RejectHeaderRequest(request.height, request.header_hash)
    #     yield OutboundMessage(
    #         NodeType.WALLET,
    #         Message("reject_header_request", reject),
    #         Delivery.RESPOND,
    #     )
    #
    # @api_request
    # async def request_removals(self, request: wallet_protocol.RequestRemovals) -> OutboundMessageGenerator:
    #     block: Optional[FullBlock] = await self.block_store.get_block(request.header_hash)
    #     if (
    #         block is None
    #         or block.height != request.height
    #         or block.height not in self.blockchain.height_to_hash
    #         or self.blockchain.height_to_hash[block.height] != block.header_hash
    #     ):
    #         reject = wallet_protocol.RejectRemovalsRequest(request.height, request.header_hash)
    #         yield OutboundMessage(
    #             NodeType.WALLET,
    #             Message("reject_removals_request", reject),
    #             Delivery.RESPOND,
    #         )
    #         return
    #
    #     assert block is not None
    #     all_removals, _ = await block.tx_removals_and_additions()
    #
    #     coins_map: List[Tuple[bytes32, Optional[Coin]]] = []
    #     proofs_map: List[Tuple[bytes32, bytes]] = []
    #
    #     # If there are no transactions, respond with empty lists
    #     if block.transactions_generator is None:
    #         proofs: Optional[List]
    #         if request.coin_names is None:
    #             proofs = None
    #         else:
    #             proofs = []
    #         response = wallet_protocol.RespondRemovals(block.height, block.header_hash, [], proofs)
    #     elif request.coin_names is None or len(request.coin_names) == 0:
    #         for removal in all_removals:
    #             cr = await self.coin_store.get_coin_record(removal)
    #             assert cr is not None
    #             coins_map.append((cr.coin.name(), cr.coin))
    #         response = wallet_protocol.RespondRemovals(block.height, block.header_hash, coins_map, None)
    #     else:
    #         assert block.transactions_generator
    #         removal_merkle_set = MerkleSet()
    #         for coin_name in all_removals:
    #             removal_merkle_set.add_already_hashed(coin_name)
    #         assert removal_merkle_set.get_root() == block.header.data.removals_root
    #         for coin_name in request.coin_names:
    #             result, proof = removal_merkle_set.is_included_already_hashed(coin_name)
    #             proofs_map.append((coin_name, proof))
    #             if coin_name in all_removals:
    #                 cr = await self.coin_store.get_coin_record(coin_name)
    #                 assert cr is not None
    #                 coins_map.append((coin_name, cr.coin))
    #                 assert result
    #             else:
    #                 coins_map.append((coin_name, None))
    #                 assert not result
    #         response = wallet_protocol.RespondRemovals(block.height, block.header_hash, coins_map, proofs_map)
    #
    #     yield OutboundMessage(
    #         NodeType.WALLET,
    #         Message("respond_removals", response),
    #         Delivery.RESPOND,
    #     )
    #
    # @api_request
    # async def request_additions(self, request: wallet_protocol.RequestAdditions) -> OutboundMessageGenerator:
    #     block: Optional[FullBlock] = await self.block_store.get_block(request.header_hash)
    #     if (
    #         block is None
    #         or block.height != request.height
    #         or block.height not in self.blockchain.height_to_hash
    #         or self.blockchain.height_to_hash[block.height] != block.header_hash
    #     ):
    #         reject = wallet_protocol.RejectAdditionsRequest(request.height, request.header_hash)
    #         yield OutboundMessage(
    #             NodeType.WALLET,
    #             Message("reject_additions_request", reject),
    #             Delivery.RESPOND,
    #         )
    #         return
    #
    #     assert block is not None
    #     _, additions = await block.tx_removals_and_additions()
    #     puzzlehash_coins_map: Dict[bytes32, List[Coin]] = {}
    #     for coin in additions + [block.get_coinbase(), block.get_fees_coin()]:
    #         if coin.puzzle_hash in puzzlehash_coins_map:
    #             puzzlehash_coins_map[coin.puzzle_hash].append(coin)
    #         else:
    #             puzzlehash_coins_map[coin.puzzle_hash] = [coin]
    #
    #     coins_map: List[Tuple[bytes32, List[Coin]]] = []
    #     proofs_map: List[Tuple[bytes32, bytes, Optional[bytes]]] = []
    #
    #     if request.puzzle_hashes is None:
    #         for puzzle_hash, coins in puzzlehash_coins_map.items():
    #             coins_map.append((puzzle_hash, coins))
    #         response = wallet_protocol.RespondAdditions(block.height, block.header_hash, coins_map, None)
    #     else:
    #         # Create addition Merkle set
    #         addition_merkle_set = MerkleSet()
    #         # Addition Merkle set contains puzzlehash and hash of all coins with that puzzlehash
    #         for puzzle, coins in puzzlehash_coins_map.items():
    #             addition_merkle_set.add_already_hashed(puzzle)
    #             addition_merkle_set.add_already_hashed(hash_coin_list(coins))
    #
    #         assert addition_merkle_set.get_root() == block.header.data.additions_root
    #         for puzzle_hash in request.puzzle_hashes:
    #             result, proof = addition_merkle_set.is_included_already_hashed(puzzle_hash)
    #             if puzzle_hash in puzzlehash_coins_map:
    #                 coins_map.append((puzzle_hash, puzzlehash_coins_map[puzzle_hash]))
    #                 hash_coin_str = hash_coin_list(puzzlehash_coins_map[puzzle_hash])
    #                 result_2, proof_2 = addition_merkle_set.is_included_already_hashed(hash_coin_str)
    #                 assert result
    #                 assert result_2
    #                 proofs_map.append((puzzle_hash, proof, proof_2))
    #             else:
    #                 coins_map.append((puzzle_hash, []))
    #                 assert not result
    #                 proofs_map.append((puzzle_hash, proof, None))
    #         response = wallet_protocol.RespondAdditions(block.height, block.header_hash, coins_map, proofs_map)
    #
    #     yield OutboundMessage(
    #         NodeType.WALLET,
    #         Message("respond_additions", response),
    #         Delivery.RESPOND,
    #     )
    #
    # @api_request
    # async def request_generator(self, request: wallet_protocol.RequestGenerator) -> OutboundMessageGenerator:
    #     full_block: Optional[FullBlock] = await self.block_store.get_block(request.header_hash)
    #     if full_block is not None:
    #         if full_block.transactions_generator is not None:
    #             wrapper = GeneratorResponse(
    #                 full_block.height,
    #                 full_block.header_hash,
    #                 full_block.transactions_generator,
    #             )
    #             response = wallet_protocol.RespondGenerator(wrapper)
    #             yield OutboundMessage(
    #                 NodeType.WALLET,
    #                 Message("respond_generator", response),
    #                 Delivery.RESPOND,
    #             )
    #             return
    #
    #     reject = wallet_protocol.RejectGeneratorRequest(request.height, request.header_hash)
    #     yield OutboundMessage(
    #         NodeType.WALLET,
    #         Message("reject_generator_request", reject),
    #         Delivery.RESPOND,
    #     )
