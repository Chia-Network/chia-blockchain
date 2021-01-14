import asyncio
import dataclasses
import time

import src.server.ws_connection as ws
from typing import AsyncGenerator, List, Optional, Tuple, Callable, Dict
from chiabip158 import PyBIP158
from blspy import G2Element, AugSchemeMPL

from src.consensus.block_creation import create_unfinished_block
from src.consensus.pot_iterations import (
    calculate_ip_iters,
    calculate_sp_iters,
    calculate_iterations_quality,
)
from src.full_node.full_node import FullNode
from src.full_node.mempool_check_conditions import get_puzzle_and_solution_for_coin
from src.full_node.signage_point import SignagePoint
from src.consensus.sub_block_record import SubBlockRecord


from src.protocols import (
    farmer_protocol,
    full_node_protocol,
    timelord_protocol,
    wallet_protocol,
)
from src.protocols.full_node_protocol import RejectSubBlocks
from src.protocols.wallet_protocol import RejectHeaderRequest, PuzzleSolutionResponse, RejectHeaderBlocks
from src.server.outbound_message import Message, NodeType, OutboundMessage
from src.types.coin import Coin, hash_coin_list

from src.types.end_of_slot_bundle import EndOfSubSlotBundle
from src.types.full_block import FullBlock
from src.types.header_block import HeaderBlock

from src.types.mempool_inclusion_status import MempoolInclusionStatus
from src.types.mempool_item import MempoolItem
from src.types.pool_target import PoolTarget
from src.types.program import Program
from src.types.sized_bytes import bytes32
from src.types.spend_bundle import SpendBundle
from src.types.unfinished_block import UnfinishedBlock
from src.util.api_decorators import api_request, peer_required
from src.util.errors import Err
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
        self, request: full_node_protocol.RespondPeers, peer: ws.WSChiaConnection
    ) -> Optional[Message]:
        if self.full_node.full_node_peers is not None:
            if peer.connection_type is NodeType.INTRODUCER:
                is_full_node = False
            else:
                is_full_node = True
            await self.full_node.full_node_peers.respond_peers(request, peer.get_peer_info(), is_full_node)

        if peer.connection_type is NodeType.INTRODUCER:
            await peer.close()
        return None

    @peer_required
    @api_request
    async def new_peak(self, request: full_node_protocol.NewPeak, peer: ws.WSChiaConnection) -> Optional[Message]:
        """
        A peer notifies us that they have added a new peak to their blockchain. If we don't have it,
        we can ask for it.
        """
        return await self.full_node.new_peak(request, peer)

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
        if request.tip not in self.full_node.blockchain.sub_blocks:
            self.log.error(f"got weight proof request for unknown peak {request.tip}")
            return None
        if request.tip in self.full_node.pow_creation:
            event = self.full_node.pow_creation[request.tip]
            await event.wait()
            wp = await self.full_node.weight_proof_handler.get_proof_of_weight(request.tip)
        else:
            event = asyncio.Event()
            self.full_node.pow_creation[request.tip] = event
            wp = await self.full_node.weight_proof_handler.get_proof_of_weight(request.tip)
            event.set()
        tips = list(self.full_node.pow_creation.keys())

        if len(tips) > 4:
            # Remove old from cache
            for i in range(0, 4):
                self.full_node.pow_creation.pop(tips[i])

        if wp is None:
            self.log.error(f"failed creating weight proof for peak {request.tip}")
            return None
        return Message("respond_proof_of_weight", full_node_protocol.RespondProofOfWeight(wp, request.tip))

    @api_request
    async def respond_proof_of_weight(self, response: full_node_protocol.RespondProofOfWeight) -> Optional[Message]:
        validated, fork_point = self.full_node.weight_proof_handler.validate_weight_proof(response.wp)
        if validated is True:
            # get tip params
            tip_weight = response.wp.recent_chain_data[-1].reward_chain_sub_block.weight
            tip_height = response.wp.recent_chain_data[-1].reward_chain_sub_block.sub_block_height
            self.full_node.sync_store.add_potential_peak(response.tip, tip_height, tip_weight)
            self.full_node.sync_store.add_potential_fork_point(response.tip, fork_point)
            return Message(
                "request_sub_block",
                full_node_protocol.RequestSubBlock(uint32(tip_height), True),
            )
        return None

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
    async def request_sub_blocks(self, request: full_node_protocol.RequestSubBlocks) -> Optional[Message]:
        if request.end_sub_height < request.start_sub_height or request.end_sub_height - request.start_sub_height > 32:
            return None
        for i in range(request.start_sub_height, request.end_sub_height + 1):
            if i not in self.full_node.blockchain.sub_height_to_hash:
                reject = RejectSubBlocks(request.start_sub_height, request.end_sub_height)
                msg = Message("reject_sub_blocks", reject)
                return msg

        blocks = []

        for i in range(request.start_sub_height, request.end_sub_height + 1):
            block: Optional[FullBlock] = await self.full_node.block_store.get_full_block(
                self.full_node.blockchain.sub_height_to_hash[uint32(i)]
            )
            if block is None:
                reject = RejectSubBlocks(request.start_sub_height, request.end_sub_height)
                msg = Message("reject_sub_blocks", reject)
                return msg
            if not request.include_transaction_block:
                block = dataclasses.replace(block, transactions_generator=None)
            blocks.append(block)

        msg = Message(
            "respond_sub_blocks",
            full_node_protocol.RespondSubBlocks(request.start_sub_height, request.end_sub_height, blocks),
        )
        return msg

    @api_request
    async def reject_sub_blocks(self, request: full_node_protocol.RequestSubBlocks):
        self.log.info(f"reject_sub_blocks {request.start_sub_height} {request.end_sub_height}")
        pass

    @api_request
    async def respond_sub_blocks(self, request: full_node_protocol.RespondSubBlocks):
        pass

    @api_request
    @peer_required
    async def respond_sub_block(
        self,
        respond_sub_block: full_node_protocol.RespondSubBlock,
        peer: ws.WSChiaConnection,
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
        self,
        respond_unfinished_sub_block: full_node_protocol.RespondUnfinishedSubBlock,
        peer: ws.WSChiaConnection,
    ) -> Optional[Message]:
        if self.full_node.sync_store.get_sync_mode():
            return None
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
                new_sp.challenge_hash,
                new_sp.index_from_challenge,
                new_sp.last_rc_infusion,
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
                return Message(
                    "respond_end_of_sub_slot",
                    full_node_protocol.RespondEndOfSubSlot(sub_slot[0]),
                )
        else:
            if self.full_node.full_node_store.get_sub_slot(request.challenge_hash) is None:
                if request.challenge_hash != self.full_node.constants.FIRST_CC_CHALLENGE:
                    self.log.warning(f"Don't have challenge hash {request.challenge_hash}")

            sp: Optional[SignagePoint] = self.full_node.full_node_store.get_signage_point_by_index(
                request.challenge_hash,
                request.index_from_challenge,
                request.last_rc_infusion,
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
        if self.full_node.sync_store.get_sync_mode():
            return None
        async with self.full_node.timelord_lock:
            # Already have signage point
            if (
                self.full_node.full_node_store.get_signage_point(request.challenge_chain_vdf.output.get_hash())
                is not None
            ):
                return None
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
                self.log.warning(
                    f"Signage point {request.index_from_challenge} not added, CC challenge: "
                    f"{request.challenge_chain_vdf.challenge}, RC challenge: {request.reward_chain_vdf.challenge}"
                )

            return None

    @peer_required
    @api_request
    async def respond_end_of_sub_slot(
        self, request: full_node_protocol.RespondEndOfSubSlot, peer: ws.WSChiaConnection
    ) -> Optional[Message]:
        if self.full_node.sync_store.get_sync_mode():
            return None
        msg, _ = await self.full_node.respond_end_of_sub_slot(request, peer)
        return msg

    @peer_required
    @api_request
    async def request_mempool_transactions(
        self,
        request: full_node_protocol.RequestMempoolTransactions,
        peer: ws.WSChiaConnection,
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

            def get_plot_sig(to_sign, _) -> G2Element:
                if to_sign == request.challenge_chain_sp:
                    return request.challenge_chain_sp_signature
                elif to_sign == request.reward_chain_sp:
                    return request.reward_chain_sp_signature
                return G2Element.infinity()

            def get_pool_sig(_1, _2) -> G2Element:
                return request.pool_signature

            prev_sb: Optional[SubBlockRecord] = self.full_node.blockchain.get_peak()

            # Finds the previous sub block from the signage point, ensuring that the reward chain VDF is correct
            if prev_sb is not None:
                if request.signage_point_index == 0:
                    if pos_sub_slot is None:
                        self.log.warning("Pos sub slot is None")
                        return None
                    rc_challenge = pos_sub_slot[0].reward_chain.end_of_slot_vdf.challenge
                else:
                    assert sp_vdfs.rc_vdf is not None
                    rc_challenge = sp_vdfs.rc_vdf.challenge

                # Backtrack through empty sub-slots
                for eos, _, _ in reversed(self.full_node.full_node_store.finished_sub_slots):
                    if eos is not None and eos.reward_chain.get_hash() == rc_challenge:
                        rc_challenge = eos.reward_chain.end_of_slot_vdf.challenge

                found = False
                attempts = 0
                while prev_sb is not None and attempts < 10:
                    if prev_sb.reward_infusion_new_challenge == rc_challenge:
                        found = True
                        break
                    if prev_sb.finished_reward_slot_hashes is not None and len(prev_sb.finished_reward_slot_hashes) > 0:
                        if prev_sb.finished_reward_slot_hashes[-1] == rc_challenge:
                            # This sub-block includes a sub-slot which is where our SP vdf starts. Go back one more
                            # to find the prev sub block
                            prev_sb = self.full_node.blockchain.sub_blocks.get(prev_sb.prev_hash, None)
                            found = True
                            break
                    prev_sb = self.full_node.blockchain.sub_blocks.get(prev_sb.prev_hash, None)
                    attempts += 1
                if not found:
                    self.log.warning("Did not find a previous block with the correct reward chain hash")
                    return None

            try:
                finished_sub_slots: List[EndOfSubSlotBundle] = self.full_node.full_node_store.get_finished_sub_slots(
                    prev_sb, self.full_node.blockchain.sub_blocks, cc_challenge_hash
                )
                if (
                    len(finished_sub_slots) > 0
                    and pos_sub_slot is not None
                    and finished_sub_slots[-1] != pos_sub_slot[0]
                ):
                    self.log.error("Have different sub-slots than is required to farm this sub-block")
                    return None
            except ValueError as e:
                self.log.warning(f"Value Error: {e}")
                return None
            if prev_sb is None:
                pool_target = PoolTarget(
                    self.full_node.constants.GENESIS_PRE_FARM_POOL_PUZZLE_HASH,
                    uint32(0),
                )
            else:
                pool_target = request.pool_target

            if peak is None or peak.sub_block_height <= self.full_node.constants.MAX_SUB_SLOT_SUB_BLOCKS:
                difficulty = self.full_node.constants.DIFFICULTY_STARTING
                sub_slot_iters = self.full_node.constants.SUB_SLOT_ITERS_STARTING
            else:
                difficulty = uint64(peak.weight - self.full_node.blockchain.sub_blocks[peak.prev_hash].weight)
                sub_slot_iters = peak.sub_slot_iters
                for sub_slot in finished_sub_slots:
                    if sub_slot.challenge_chain.new_difficulty is not None:
                        difficulty = sub_slot.challenge_chain.new_difficulty
                    if sub_slot.challenge_chain.new_sub_slot_iters is not None:
                        sub_slot_iters = sub_slot.challenge_chain.new_sub_slot_iters

            required_iters: uint64 = calculate_iterations_quality(
                quality_string,
                request.proof_of_space.size,
                difficulty,
                request.challenge_chain_sp,
            )
            sp_iters: uint64 = calculate_sp_iters(self.full_node.constants, sub_slot_iters, request.signage_point_index)
            ip_iters: uint64 = calculate_ip_iters(
                self.full_node.constants,
                sub_slot_iters,
                request.signage_point_index,
                required_iters,
            )

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

        await self.full_node.respond_unfinished_sub_block(request, None, True)
        return None

    # TIMELORD PROTOCOL
    @api_request
    async def new_infusion_point_vdf(self, request: timelord_protocol.NewInfusionPointVDF) -> Optional[Message]:
        if self.full_node.sync_store.get_sync_mode():
            return None
        # Lookup unfinished blocks
        return await self.full_node.new_infusion_point_vdf(request)

    @peer_required
    @api_request
    async def new_signage_point_vdf(
        self, request: timelord_protocol.NewSignagePointVDF, peer: ws.WSChiaConnection
    ) -> None:
        if self.full_node.sync_store.get_sync_mode():
            return None

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
        if self.full_node.sync_store.get_sync_mode():
            return None
        if (
            self.full_node.full_node_store.get_sub_slot(request.end_of_sub_slot_bundle.challenge_chain.get_hash())
            is not None
        ):
            return None
        # Calls our own internal message to handle the end of sub slot, and potentially broadcasts to other peers.
        full_node_message = full_node_protocol.RespondEndOfSubSlot(request.end_of_sub_slot_bundle)
        msg, added = await self.full_node.respond_end_of_sub_slot(full_node_message, peer)
        if not added:
            self.log.error(
                f"Was not able to add end of sub-slot: "
                f"{request.end_of_sub_slot_bundle.challenge_chain.challenge_chain_end_of_slot_vdf.challenge}. "
                f"Re-sending new-peak to timelord"
            )
            await self.full_node.send_peak_to_timelords()
            return None
        else:
            return msg

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
            msg = Message(
                "respond_sub_block_header",
                wallet_protocol.RespondSubBlockHeader(header_block),
            )
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
            assert removal_merkle_set.get_root() == block.foliage_block.removals_root
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

    @api_request
    async def send_transaction(self, request: wallet_protocol.SendTransaction) -> Optional[Message]:
        # Ignore if syncing
        if self.full_node.sync_store.get_sync_mode():
            return None
        # Ignore if syncing
        if self.full_node.sync_store.get_sync_mode():
            status = MempoolInclusionStatus.FAILED
            error: Optional[Err] = Err.UNKNOWN
        else:
            async with self.full_node.blockchain.lock:
                cost, status, error = await self.full_node.mempool_manager.add_spendbundle(request.transaction)
                if status == MempoolInclusionStatus.SUCCESS:
                    self.log.info(f"Added transaction to mempool: {request.transaction.name()}")
                    # Only broadcast successful transactions, not pending ones. Otherwise it's a DOS
                    # vector.
                    fees = request.transaction.fees()
                    assert fees >= 0
                    assert cost is not None
                    new_tx = full_node_protocol.NewTransaction(
                        request.transaction.name(),
                        cost,
                        uint64(request.transaction.fees()),
                    )
                    msg = Message("new_transaction", new_tx)
                    await self.full_node.server.send_to_all([msg], NodeType.FULL_NODE)
                else:
                    self.log.warning(
                        f"Wasn't able to add transaction with id {request.transaction.name()}, "
                        f"status {status} error: {error}"
                    )

        error_name = error.name if error is not None else None
        if status == MempoolInclusionStatus.SUCCESS:
            response = wallet_protocol.TransactionAck(request.transaction.name(), status, error_name)
        else:
            # If if failed/pending, but it previously succeeded (in mempool), this is idempotence, return SUCCESS
            if self.full_node.mempool_manager.get_spendbundle(request.transaction.name()) is not None:
                response = wallet_protocol.TransactionAck(
                    request.transaction.name(), MempoolInclusionStatus.SUCCESS, None
                )
            else:
                response = wallet_protocol.TransactionAck(request.transaction.name(), status, error_name)
        msg = Message("transaction_ack", response)
        return msg

    @api_request
    async def request_puzzle_solution(self, request: wallet_protocol.RequestPuzzleSolution) -> Optional[Message]:
        coin_name = request.coin_name
        sub_height = request.sub_height
        coin_record = await self.full_node.coin_store.get_coin_record(coin_name)
        reject = wallet_protocol.RejectPuzzleSolution(coin_name, sub_height)
        reject_msg = Message("reject_puzzle_solution", reject)
        if coin_record is None or coin_record.spent_block_index != sub_height:
            return reject_msg

        header_hash = self.full_node.blockchain.sub_height_to_hash[sub_height]
        block: Optional[FullBlock] = await self.full_node.block_store.get_full_block(header_hash)

        if block is None or block.transactions_generator is None:
            return reject_msg

        error, puzzle, solution = get_puzzle_and_solution_for_coin(block.transactions_generator, coin_name)

        if error is not None:
            return reject_msg

        pz = Program.to(puzzle)
        sol = Program.to(solution)

        wrapper = PuzzleSolutionResponse(coin_name, sub_height, pz, sol)
        response = wallet_protocol.RespondPuzzleSolution(wrapper)
        response_msg = Message("respond_puzzle_solution", response)
        return response_msg

    @api_request
    async def request_header_blocks(self, request: wallet_protocol.RequestHeaderBlocks) -> Optional[Message]:
        if request.end_sub_height < request.start_sub_height or request.end_sub_height - request.start_sub_height > 32:
            return None
        for i in range(request.start_sub_height, request.end_sub_height + 1):
            if i not in self.full_node.blockchain.sub_height_to_hash:
                reject = RejectHeaderBlocks(request.start_sub_height, request.end_sub_height)
                msg = Message("reject_header_blocks_request", reject)
                return msg

        blocks: List[HeaderBlock] = []

        for i in range(request.start_sub_height, request.end_sub_height + 1):
            block: Optional[FullBlock] = await self.full_node.block_store.get_full_block(
                self.full_node.blockchain.sub_height_to_hash[uint32(i)]
            )
            if block is None:
                reject = RejectHeaderBlocks(request.start_sub_height, request.end_sub_height)
                msg = Message("reject_header_blocks_request", reject)
                return msg

            blocks.append(await block.get_block_header())

        msg = Message(
            "respond_header_blocks",
            wallet_protocol.RespondHeaderBlocks(request.start_sub_height, request.end_sub_height, blocks),
        )
        return msg
