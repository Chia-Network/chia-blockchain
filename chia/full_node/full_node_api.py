from __future__ import annotations

import asyncio
import dataclasses
import functools
import logging
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from secrets import token_bytes
from typing import TYPE_CHECKING, Dict, List, Optional, Set, Tuple

from blspy import AugSchemeMPL, G1Element, G2Element
from chiabip158 import PyBIP158

from chia.consensus.block_creation import create_unfinished_block
from chia.consensus.block_record import BlockRecord
from chia.consensus.blockchain import BlockchainMutexPriority
from chia.consensus.pot_iterations import calculate_ip_iters, calculate_iterations_quality, calculate_sp_iters
from chia.full_node.bundle_tools import (
    best_solution_generator_from_template,
    simple_solution_generator,
    simple_solution_generator_backrefs,
)
from chia.full_node.fee_estimate import FeeEstimate, FeeEstimateGroup, fee_rate_v2_to_v1
from chia.full_node.fee_estimator_interface import FeeEstimatorInterface
from chia.full_node.mempool_check_conditions import get_name_puzzle_conditions, get_puzzle_and_solution_for_coin
from chia.full_node.signage_point import SignagePoint
from chia.full_node.tx_processing_queue import TransactionQueueFull
from chia.protocols import farmer_protocol, full_node_protocol, introducer_protocol, timelord_protocol, wallet_protocol
from chia.protocols.full_node_protocol import RejectBlock, RejectBlocks
from chia.protocols.protocol_message_types import ProtocolMessageTypes
from chia.protocols.wallet_protocol import (
    CoinState,
    PuzzleSolutionResponse,
    RejectBlockHeaders,
    RejectHeaderBlocks,
    RejectHeaderRequest,
    RespondFeeEstimates,
    RespondSESInfo,
)
from chia.server.outbound_message import Message, make_msg
from chia.server.server import ChiaServer
from chia.server.ws_connection import WSChiaConnection
from chia.types.block_protocol import BlockInfo
from chia.types.blockchain_format.coin import Coin, hash_coin_ids
from chia.types.blockchain_format.pool_target import PoolTarget
from chia.types.blockchain_format.proof_of_space import verify_and_get_quality_string
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.blockchain_format.sub_epoch_summary import SubEpochSummary
from chia.types.coin_record import CoinRecord
from chia.types.end_of_slot_bundle import EndOfSubSlotBundle
from chia.types.full_block import FullBlock
from chia.types.generator_types import BlockGenerator
from chia.types.mempool_inclusion_status import MempoolInclusionStatus
from chia.types.peer_info import PeerInfo
from chia.types.spend_bundle import SpendBundle
from chia.types.transaction_queue_entry import TransactionQueueEntry
from chia.types.unfinished_block import UnfinishedBlock
from chia.util.api_decorators import api_request
from chia.util.full_block_utils import header_block_from_block
from chia.util.generator_tools import get_block_header, tx_removals_and_additions
from chia.util.hash import std_hash
from chia.util.ints import uint8, uint32, uint64, uint128
from chia.util.limited_semaphore import LimitedSemaphoreFullError
from chia.util.merkle_set import MerkleSet

if TYPE_CHECKING:
    from chia.full_node.full_node import FullNode
else:
    FullNode = object


class FullNodeAPI:
    log: logging.Logger
    full_node: FullNode
    executor: ThreadPoolExecutor

    def __init__(self, full_node: FullNode) -> None:
        self.log = logging.getLogger(__name__)
        self.full_node = full_node
        self.executor = ThreadPoolExecutor(max_workers=1)

    @property
    def server(self) -> ChiaServer:
        assert self.full_node.server is not None
        return self.full_node.server

    def ready(self) -> bool:
        return self.full_node.initialized

    @api_request(peer_required=True, reply_types=[ProtocolMessageTypes.respond_peers])
    async def request_peers(
        self, _request: full_node_protocol.RequestPeers, peer: WSChiaConnection
    ) -> Optional[Message]:
        if peer.peer_server_port is None:
            return None
        peer_info = PeerInfo(peer.peer_info.host, peer.peer_server_port)
        if self.full_node.full_node_peers is not None:
            msg = await self.full_node.full_node_peers.request_peers(peer_info)
            return msg
        return None

    @api_request(peer_required=True)
    async def respond_peers(
        self, request: full_node_protocol.RespondPeers, peer: WSChiaConnection
    ) -> Optional[Message]:
        self.log.debug(f"Received {len(request.peer_list)} peers")
        if self.full_node.full_node_peers is not None:
            await self.full_node.full_node_peers.add_peers(request.peer_list, peer.get_peer_info(), True)
        return None

    @api_request(peer_required=True)
    async def respond_peers_introducer(
        self, request: introducer_protocol.RespondPeersIntroducer, peer: WSChiaConnection
    ) -> Optional[Message]:
        self.log.debug(f"Received {len(request.peer_list)} peers from introducer")
        if self.full_node.full_node_peers is not None:
            await self.full_node.full_node_peers.add_peers(request.peer_list, peer.get_peer_info(), False)

        await peer.close()
        return None

    @api_request(peer_required=True, execute_task=True)
    async def new_peak(self, request: full_node_protocol.NewPeak, peer: WSChiaConnection) -> None:
        """
        A peer notifies us that they have added a new peak to their blockchain. If we don't have it,
        we can ask for it.
        """
        # this semaphore limits the number of tasks that can call new_peak() at
        # the same time, since it can be expensive
        try:
            async with self.full_node.new_peak_sem.acquire():
                await self.full_node.new_peak(request, peer)
        except LimitedSemaphoreFullError:
            self.log.debug("Ignoring NewPeak, limited semaphore full: %s %s", peer.get_peer_logging(), request)
            return None

        return None

    @api_request(peer_required=True)
    async def new_transaction(
        self, transaction: full_node_protocol.NewTransaction, peer: WSChiaConnection
    ) -> Optional[Message]:
        """
        A peer notifies us of a new transaction.
        Requests a full transaction if we haven't seen it previously, and if the fees are enough.
        """
        # Ignore if syncing
        if self.full_node.sync_store.get_sync_mode():
            return None
        if not (await self.full_node.synced()):
            return None

        # Ignore if already seen
        if self.full_node.mempool_manager.seen(transaction.transaction_id):
            return None

        if self.full_node.mempool_manager.is_fee_enough(transaction.fees, transaction.cost):
            # If there's current pending request just add this peer to the set of peers that have this tx
            if transaction.transaction_id in self.full_node.full_node_store.pending_tx_request:
                if transaction.transaction_id in self.full_node.full_node_store.peers_with_tx:
                    current_set = self.full_node.full_node_store.peers_with_tx[transaction.transaction_id]
                    if peer.peer_node_id in current_set:
                        return None
                    current_set.add(peer.peer_node_id)
                    return None
                else:
                    new_set = set()
                    new_set.add(peer.peer_node_id)
                    self.full_node.full_node_store.peers_with_tx[transaction.transaction_id] = new_set
                    return None

            self.full_node.full_node_store.pending_tx_request[transaction.transaction_id] = peer.peer_node_id
            new_set = set()
            new_set.add(peer.peer_node_id)
            self.full_node.full_node_store.peers_with_tx[transaction.transaction_id] = new_set

            async def tx_request_and_timeout(full_node: FullNode, transaction_id: bytes32, task_id: bytes32) -> None:
                counter = 0
                try:
                    while True:
                        # Limit to asking a few peers, it's possible that this tx got included on chain already
                        # Highly unlikely that the peers that advertised a tx don't respond to a request. Also, if we
                        # drop some transactions, we don't want to re-fetch too many times
                        if counter == 5:
                            break
                        if transaction_id not in full_node.full_node_store.peers_with_tx:
                            break
                        peers_with_tx: Set[bytes32] = full_node.full_node_store.peers_with_tx[transaction_id]
                        if len(peers_with_tx) == 0:
                            break
                        peer_id = peers_with_tx.pop()
                        assert full_node.server is not None
                        if peer_id not in full_node.server.all_connections:
                            continue
                        random_peer = full_node.server.all_connections[peer_id]
                        request_tx = full_node_protocol.RequestTransaction(transaction.transaction_id)
                        msg = make_msg(ProtocolMessageTypes.request_transaction, request_tx)
                        await random_peer.send_message(msg)
                        await asyncio.sleep(5)
                        counter += 1
                        if full_node.mempool_manager.seen(transaction_id):
                            break
                except asyncio.CancelledError:
                    pass
                finally:
                    # Always Cleanup
                    if transaction_id in full_node.full_node_store.peers_with_tx:
                        full_node.full_node_store.peers_with_tx.pop(transaction_id)
                    if transaction_id in full_node.full_node_store.pending_tx_request:
                        full_node.full_node_store.pending_tx_request.pop(transaction_id)
                    if task_id in full_node.full_node_store.tx_fetch_tasks:
                        full_node.full_node_store.tx_fetch_tasks.pop(task_id)

            task_id: bytes32 = bytes32(token_bytes(32))
            fetch_task = asyncio.create_task(
                tx_request_and_timeout(self.full_node, transaction.transaction_id, task_id)
            )
            self.full_node.full_node_store.tx_fetch_tasks[task_id] = fetch_task
            return None
        return None

    @api_request(reply_types=[ProtocolMessageTypes.respond_transaction])
    async def request_transaction(self, request: full_node_protocol.RequestTransaction) -> Optional[Message]:
        """Peer has requested a full transaction from us."""
        # Ignore if syncing
        if self.full_node.sync_store.get_sync_mode():
            return None
        spend_bundle = self.full_node.mempool_manager.get_spendbundle(request.transaction_id)
        if spend_bundle is None:
            return None

        transaction = full_node_protocol.RespondTransaction(spend_bundle)

        msg = make_msg(ProtocolMessageTypes.respond_transaction, transaction)
        return msg

    @api_request(peer_required=True, bytes_required=True)
    async def respond_transaction(
        self,
        tx: full_node_protocol.RespondTransaction,
        peer: WSChiaConnection,
        tx_bytes: bytes = b"",
        test: bool = False,
    ) -> Optional[Message]:
        """
        Receives a full transaction from peer.
        If tx is added to mempool, send tx_id to others. (new_transaction)
        """
        assert tx_bytes != b""
        spend_name = std_hash(tx_bytes)
        if spend_name in self.full_node.full_node_store.pending_tx_request:
            self.full_node.full_node_store.pending_tx_request.pop(spend_name)
        if spend_name in self.full_node.full_node_store.peers_with_tx:
            self.full_node.full_node_store.peers_with_tx.pop(spend_name)

        # TODO: Use fee in priority calculation, to prioritize high fee TXs
        try:
            await self.full_node.transaction_queue.put(
                TransactionQueueEntry(tx.transaction, tx_bytes, spend_name, peer, test), peer.peer_node_id
            )
        except TransactionQueueFull:
            pass  # we can't do anything here, the tx will be dropped. We might do something in the future.
        return None

    @api_request(reply_types=[ProtocolMessageTypes.respond_proof_of_weight])
    async def request_proof_of_weight(self, request: full_node_protocol.RequestProofOfWeight) -> Optional[Message]:
        if self.full_node.weight_proof_handler is None:
            return None
        if not self.full_node.blockchain.contains_block(request.tip):
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

        # Serialization of wp is slow
        if (
            self.full_node.full_node_store.serialized_wp_message_tip is not None
            and self.full_node.full_node_store.serialized_wp_message_tip == request.tip
        ):
            return self.full_node.full_node_store.serialized_wp_message
        message = make_msg(
            ProtocolMessageTypes.respond_proof_of_weight, full_node_protocol.RespondProofOfWeight(wp, request.tip)
        )
        self.full_node.full_node_store.serialized_wp_message_tip = request.tip
        self.full_node.full_node_store.serialized_wp_message = message
        return message

    @api_request()
    async def respond_proof_of_weight(self, request: full_node_protocol.RespondProofOfWeight) -> Optional[Message]:
        self.log.warning("Received proof of weight too late.")
        return None

    @api_request(reply_types=[ProtocolMessageTypes.respond_block, ProtocolMessageTypes.reject_block])
    async def request_block(self, request: full_node_protocol.RequestBlock) -> Optional[Message]:
        if not self.full_node.blockchain.contains_height(request.height):
            reject = RejectBlock(request.height)
            msg = make_msg(ProtocolMessageTypes.reject_block, reject)
            return msg
        header_hash: Optional[bytes32] = self.full_node.blockchain.height_to_hash(request.height)
        if header_hash is None:
            return make_msg(ProtocolMessageTypes.reject_block, RejectBlock(request.height))

        block: Optional[FullBlock] = await self.full_node.block_store.get_full_block(header_hash)
        if block is not None:
            if not request.include_transaction_block and block.transactions_generator is not None:
                block = dataclasses.replace(block, transactions_generator=None)
            return make_msg(ProtocolMessageTypes.respond_block, full_node_protocol.RespondBlock(block))
        return make_msg(ProtocolMessageTypes.reject_block, RejectBlock(request.height))

    @api_request(reply_types=[ProtocolMessageTypes.respond_blocks, ProtocolMessageTypes.reject_blocks])
    async def request_blocks(self, request: full_node_protocol.RequestBlocks) -> Optional[Message]:
        if (
            request.end_height < request.start_height
            or request.end_height - request.start_height > self.full_node.constants.MAX_BLOCK_COUNT_PER_REQUESTS
        ):
            reject = RejectBlocks(request.start_height, request.end_height)
            msg: Message = make_msg(ProtocolMessageTypes.reject_blocks, reject)
            return msg
        for i in range(request.start_height, request.end_height + 1):
            if not self.full_node.blockchain.contains_height(uint32(i)):
                reject = RejectBlocks(request.start_height, request.end_height)
                msg = make_msg(ProtocolMessageTypes.reject_blocks, reject)
                return msg

        if not request.include_transaction_block:
            blocks: List[FullBlock] = []
            for i in range(request.start_height, request.end_height + 1):
                header_hash_i: Optional[bytes32] = self.full_node.blockchain.height_to_hash(uint32(i))
                if header_hash_i is None:
                    reject = RejectBlocks(request.start_height, request.end_height)
                    return make_msg(ProtocolMessageTypes.reject_blocks, reject)

                block: Optional[FullBlock] = await self.full_node.block_store.get_full_block(header_hash_i)
                if block is None:
                    reject = RejectBlocks(request.start_height, request.end_height)
                    return make_msg(ProtocolMessageTypes.reject_blocks, reject)
                block = dataclasses.replace(block, transactions_generator=None)
                blocks.append(block)
            msg = make_msg(
                ProtocolMessageTypes.respond_blocks,
                full_node_protocol.RespondBlocks(request.start_height, request.end_height, blocks),
            )
        else:
            blocks_bytes: List[bytes] = []
            for i in range(request.start_height, request.end_height + 1):
                header_hash_i = self.full_node.blockchain.height_to_hash(uint32(i))
                if header_hash_i is None:
                    reject = RejectBlocks(request.start_height, request.end_height)
                    return make_msg(ProtocolMessageTypes.reject_blocks, reject)
                block_bytes: Optional[bytes] = await self.full_node.block_store.get_full_block_bytes(header_hash_i)
                if block_bytes is None:
                    reject = RejectBlocks(request.start_height, request.end_height)
                    msg = make_msg(ProtocolMessageTypes.reject_blocks, reject)
                    return msg

                blocks_bytes.append(block_bytes)

            respond_blocks_manually_streamed: bytes = (
                bytes(uint32(request.start_height))
                + bytes(uint32(request.end_height))
                + len(blocks_bytes).to_bytes(4, "big", signed=False)
            )
            for block_bytes in blocks_bytes:
                respond_blocks_manually_streamed += block_bytes
            msg = make_msg(ProtocolMessageTypes.respond_blocks, respond_blocks_manually_streamed)

        return msg

    @api_request()
    async def reject_block(self, request: full_node_protocol.RejectBlock) -> None:
        self.log.debug(f"reject_block {request.height}")

    @api_request()
    async def reject_blocks(self, request: full_node_protocol.RejectBlocks) -> None:
        self.log.debug(f"reject_blocks {request.start_height} {request.end_height}")

    @api_request()
    async def respond_blocks(self, request: full_node_protocol.RespondBlocks) -> None:
        self.log.warning("Received unsolicited/late blocks")
        return None

    @api_request(peer_required=True)
    async def respond_block(
        self,
        respond_block: full_node_protocol.RespondBlock,
        peer: WSChiaConnection,
    ) -> Optional[Message]:
        """
        Receive a full block from a peer full node (or ourselves).
        """

        self.log.warning(f"Received unsolicited/late block from peer {peer.get_peer_logging()}")
        return None

    @api_request()
    async def new_unfinished_block(
        self, new_unfinished_block: full_node_protocol.NewUnfinishedBlock
    ) -> Optional[Message]:
        # Ignore if syncing
        if self.full_node.sync_store.get_sync_mode():
            return None
        block_hash = new_unfinished_block.unfinished_reward_hash
        if self.full_node.full_node_store.get_unfinished_block(block_hash) is not None:
            return None

        # This prevents us from downloading the same block from many peers
        if block_hash in self.full_node.full_node_store.requesting_unfinished_blocks:
            return None

        msg = make_msg(
            ProtocolMessageTypes.request_unfinished_block,
            full_node_protocol.RequestUnfinishedBlock(block_hash),
        )
        self.full_node.full_node_store.requesting_unfinished_blocks.add(block_hash)

        # However, we want to eventually download from other peers, if this peer does not respond
        # Todo: keep track of who it was
        async def eventually_clear() -> None:
            await asyncio.sleep(5)
            if block_hash in self.full_node.full_node_store.requesting_unfinished_blocks:
                self.full_node.full_node_store.requesting_unfinished_blocks.remove(block_hash)

        asyncio.create_task(eventually_clear())

        return msg

    @api_request(reply_types=[ProtocolMessageTypes.respond_unfinished_block])
    async def request_unfinished_block(
        self, request_unfinished_block: full_node_protocol.RequestUnfinishedBlock
    ) -> Optional[Message]:
        unfinished_block: Optional[UnfinishedBlock] = self.full_node.full_node_store.get_unfinished_block(
            request_unfinished_block.unfinished_reward_hash
        )
        if unfinished_block is not None:
            msg = make_msg(
                ProtocolMessageTypes.respond_unfinished_block,
                full_node_protocol.RespondUnfinishedBlock(unfinished_block),
            )
            return msg
        return None

    @api_request(peer_required=True, bytes_required=True)
    async def respond_unfinished_block(
        self,
        respond_unfinished_block: full_node_protocol.RespondUnfinishedBlock,
        peer: WSChiaConnection,
        respond_unfinished_block_bytes: bytes = b"",
    ) -> Optional[Message]:
        if self.full_node.sync_store.get_sync_mode():
            return None
        await self.full_node.add_unfinished_block(
            respond_unfinished_block.unfinished_block, peer, block_bytes=respond_unfinished_block_bytes
        )
        return None

    @api_request(peer_required=True)
    async def new_signage_point_or_end_of_sub_slot(
        self, new_sp: full_node_protocol.NewSignagePointOrEndOfSubSlot, peer: WSChiaConnection
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
                collected_eos = []
                challenge_hash_to_request = new_sp.challenge_hash
                last_rc = new_sp.last_rc_infusion
                num_non_empty_sub_slots_seen = 0
                for _ in range(30):
                    if num_non_empty_sub_slots_seen >= 3:
                        self.log.debug("Diverged from peer. Don't have the same blocks")
                        return None
                    # If this is an end of sub slot, and we don't have the prev, request the prev instead
                    # We want to catch up to the latest slot so we can receive signage points
                    full_node_request = full_node_protocol.RequestSignagePointOrEndOfSubSlot(
                        challenge_hash_to_request, uint8(0), last_rc
                    )
                    response = await peer.call_api(
                        FullNodeAPI.request_signage_point_or_end_of_sub_slot, full_node_request, timeout=10
                    )
                    if not isinstance(response, full_node_protocol.RespondEndOfSubSlot):
                        self.full_node.log.debug(f"Invalid response for slot {response}")
                        return None
                    collected_eos.append(response)
                    if (
                        self.full_node.full_node_store.get_sub_slot(
                            response.end_of_slot_bundle.challenge_chain.challenge_chain_end_of_slot_vdf.challenge
                        )
                        is not None
                        or response.end_of_slot_bundle.challenge_chain.challenge_chain_end_of_slot_vdf.challenge
                        == self.full_node.constants.GENESIS_CHALLENGE
                    ):
                        for eos in reversed(collected_eos):
                            await self.respond_end_of_sub_slot(eos, peer)
                        return None
                    if (
                        response.end_of_slot_bundle.challenge_chain.challenge_chain_end_of_slot_vdf.number_of_iterations
                        != response.end_of_slot_bundle.reward_chain.end_of_slot_vdf.number_of_iterations
                    ):
                        num_non_empty_sub_slots_seen += 1
                    challenge_hash_to_request = (
                        response.end_of_slot_bundle.challenge_chain.challenge_chain_end_of_slot_vdf.challenge
                    )
                    last_rc = response.end_of_slot_bundle.reward_chain.end_of_slot_vdf.challenge
                self.full_node.log.warning("Failed to catch up in sub-slots")
                return None

        if new_sp.index_from_challenge > 0:
            if (
                new_sp.challenge_hash != self.full_node.constants.GENESIS_CHALLENGE
                and self.full_node.full_node_store.get_sub_slot(new_sp.challenge_hash) is None
            ):
                # If this is a normal signage point,, and we don't have the end of sub slot, request the end of sub slot
                full_node_request = full_node_protocol.RequestSignagePointOrEndOfSubSlot(
                    new_sp.challenge_hash, uint8(0), new_sp.last_rc_infusion
                )
                return make_msg(ProtocolMessageTypes.request_signage_point_or_end_of_sub_slot, full_node_request)

        # Otherwise (we have the prev or the end of sub slot), request it normally
        full_node_request = full_node_protocol.RequestSignagePointOrEndOfSubSlot(
            new_sp.challenge_hash, new_sp.index_from_challenge, new_sp.last_rc_infusion
        )

        return make_msg(ProtocolMessageTypes.request_signage_point_or_end_of_sub_slot, full_node_request)

    @api_request(reply_types=[ProtocolMessageTypes.respond_signage_point, ProtocolMessageTypes.respond_end_of_sub_slot])
    async def request_signage_point_or_end_of_sub_slot(
        self, request: full_node_protocol.RequestSignagePointOrEndOfSubSlot
    ) -> Optional[Message]:
        if request.index_from_challenge == 0:
            sub_slot: Optional[Tuple[EndOfSubSlotBundle, int, uint128]] = self.full_node.full_node_store.get_sub_slot(
                request.challenge_hash
            )
            if sub_slot is not None:
                return make_msg(
                    ProtocolMessageTypes.respond_end_of_sub_slot,
                    full_node_protocol.RespondEndOfSubSlot(sub_slot[0]),
                )
        else:
            if self.full_node.full_node_store.get_sub_slot(request.challenge_hash) is None:
                if request.challenge_hash != self.full_node.constants.GENESIS_CHALLENGE:
                    self.log.info(f"Don't have challenge hash {request.challenge_hash}")

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
                return make_msg(ProtocolMessageTypes.respond_signage_point, full_node_response)
            else:
                self.log.info(f"Don't have signage point {request}")
        return None

    @api_request(peer_required=True)
    async def respond_signage_point(
        self, request: full_node_protocol.RespondSignagePoint, peer: WSChiaConnection
    ) -> Optional[Message]:
        if self.full_node.sync_store.get_sync_mode():
            return None
        async with self.full_node.timelord_lock:
            # Already have signage point

            if self.full_node.full_node_store.have_newer_signage_point(
                request.challenge_chain_vdf.challenge,
                request.index_from_challenge,
                request.reward_chain_vdf.challenge,
            ):
                return None
            existing_sp = self.full_node.full_node_store.get_signage_point(
                request.challenge_chain_vdf.output.get_hash()
            )
            if existing_sp is not None and existing_sp.rc_vdf == request.reward_chain_vdf:
                return None
            peak = self.full_node.blockchain.get_peak()
            if peak is not None and peak.height > self.full_node.constants.MAX_SUB_SLOT_BLOCKS:
                next_sub_slot_iters = self.full_node.blockchain.get_next_slot_iters(peak.header_hash, True)
                sub_slots_for_peak = await self.full_node.blockchain.get_sp_and_ip_sub_slots(peak.header_hash)
                assert sub_slots_for_peak is not None
                ip_sub_slot: Optional[EndOfSubSlotBundle] = sub_slots_for_peak[1]
            else:
                sub_slot_iters = self.full_node.constants.SUB_SLOT_ITERS_STARTING
                next_sub_slot_iters = sub_slot_iters
                ip_sub_slot = None

            added = self.full_node.full_node_store.new_signage_point(
                request.index_from_challenge,
                self.full_node.blockchain,
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
                await self.full_node.signage_point_post_processing(request, peer, ip_sub_slot)
            else:
                self.log.debug(
                    f"Signage point {request.index_from_challenge} not added, CC challenge: "
                    f"{request.challenge_chain_vdf.challenge}, RC challenge: {request.reward_chain_vdf.challenge}"
                )

            return None

    @api_request(peer_required=True)
    async def respond_end_of_sub_slot(
        self, request: full_node_protocol.RespondEndOfSubSlot, peer: WSChiaConnection
    ) -> Optional[Message]:
        if self.full_node.sync_store.get_sync_mode():
            return None
        msg, _ = await self.full_node.add_end_of_sub_slot(request.end_of_slot_bundle, peer)
        return msg

    @api_request(peer_required=True)
    async def request_mempool_transactions(
        self,
        request: full_node_protocol.RequestMempoolTransactions,
        peer: WSChiaConnection,
    ) -> Optional[Message]:
        received_filter = PyBIP158(bytearray(request.filter))

        items: List[SpendBundle] = self.full_node.mempool_manager.get_items_not_in_filter(received_filter)

        for item in items:
            transaction = full_node_protocol.RespondTransaction(item)
            msg = make_msg(ProtocolMessageTypes.respond_transaction, transaction)
            await peer.send_message(msg)
        return None

    # FARMER PROTOCOL
    @api_request(peer_required=True)
    async def declare_proof_of_space(
        self, request: farmer_protocol.DeclareProofOfSpace, peer: WSChiaConnection
    ) -> Optional[Message]:
        """
        Creates a block body and header, with the proof of space, coinbase, and fee targets provided
        by the farmer, and sends the hash of the header data back to the farmer.
        """
        if self.full_node.sync_store.get_sync_mode():
            return None

        async with self.full_node.timelord_lock:
            sp_vdfs: Optional[SignagePoint] = self.full_node.full_node_store.get_signage_point(
                request.challenge_chain_sp
            )

            if sp_vdfs is None:
                self.log.warning(f"Received proof of space for an unknown signage point {request.challenge_chain_sp}")
                return None
            if request.signage_point_index > 0:
                assert sp_vdfs.rc_vdf is not None
                if sp_vdfs.rc_vdf.output.get_hash() != request.reward_chain_sp:
                    self.log.debug(
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
            if request.challenge_hash != self.full_node.constants.GENESIS_CHALLENGE:
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

            # Grab best transactions from Mempool for given tip target
            aggregate_signature: G2Element = G2Element()
            block_generator: Optional[BlockGenerator] = None
            additions: Optional[List[Coin]] = []
            removals: Optional[List[Coin]] = []
            async with self.full_node.blockchain.priority_mutex.acquire(priority=BlockchainMutexPriority.high):
                peak: Optional[BlockRecord] = self.full_node.blockchain.get_peak()

                # Checks that the proof of space is valid
                height: uint32
                if peak is None:
                    height = uint32(0)
                else:
                    height = peak.height
                quality_string: Optional[bytes32] = verify_and_get_quality_string(
                    request.proof_of_space,
                    self.full_node.constants,
                    cc_challenge_hash,
                    request.challenge_chain_sp,
                    height=height,
                )
                assert quality_string is not None and len(quality_string) == 32

                if peak is not None:
                    # Finds the last transaction block before this one
                    curr_l_tb: BlockRecord = peak
                    while not curr_l_tb.is_transaction_block:
                        curr_l_tb = self.full_node.blockchain.block_record(curr_l_tb.prev_hash)
                    try:
                        mempool_bundle = self.full_node.mempool_manager.create_bundle_from_mempool(
                            curr_l_tb.header_hash
                        )
                    except Exception as e:
                        self.log.error(f"Traceback: {traceback.format_exc()}")
                        self.full_node.log.error(f"Error making spend bundle {e} peak: {peak}")
                        mempool_bundle = None
                    if mempool_bundle is not None:
                        spend_bundle, additions = mempool_bundle
                        removals = spend_bundle.removals()
                        self.full_node.log.info(f"Add rem: {len(additions)} {len(removals)}")
                        aggregate_signature = spend_bundle.aggregated_signature
                        # when the hard fork activates, block generators are
                        # allowed to be serialized with the improved CLVM
                        # serialization format, supporting back-references
                        if peak.height >= self.full_node.constants.HARD_FORK_HEIGHT:
                            block_generator = simple_solution_generator_backrefs(spend_bundle)
                        else:
                            if self.full_node.full_node_store.previous_generator is not None:
                                self.log.info(
                                    f"Using previous generator for height "
                                    f"{self.full_node.full_node_store.previous_generator}"
                                )
                                block_generator = best_solution_generator_from_template(
                                    self.full_node.full_node_store.previous_generator, spend_bundle
                                )
                            else:
                                block_generator = simple_solution_generator(spend_bundle)

            def get_plot_sig(to_sign: bytes32, _extra: G1Element) -> G2Element:
                if to_sign == request.challenge_chain_sp:
                    return request.challenge_chain_sp_signature
                elif to_sign == request.reward_chain_sp:
                    return request.reward_chain_sp_signature
                return G2Element()

            def get_pool_sig(_1: PoolTarget, _2: Optional[G1Element]) -> Optional[G2Element]:
                return request.pool_signature

            prev_b: Optional[BlockRecord] = peak

            # Finds the previous block from the signage point, ensuring that the reward chain VDF is correct
            if prev_b is not None:
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
                while prev_b is not None and attempts < 10:
                    if prev_b.reward_infusion_new_challenge == rc_challenge:
                        found = True
                        break
                    if prev_b.finished_reward_slot_hashes is not None and len(prev_b.finished_reward_slot_hashes) > 0:
                        if prev_b.finished_reward_slot_hashes[-1] == rc_challenge:
                            # This block includes a sub-slot which is where our SP vdf starts. Go back one more
                            # to find the prev block
                            prev_b = self.full_node.blockchain.try_block_record(prev_b.prev_hash)
                            found = True
                            break
                    prev_b = self.full_node.blockchain.try_block_record(prev_b.prev_hash)
                    attempts += 1
                if not found:
                    self.log.warning("Did not find a previous block with the correct reward chain hash")
                    return None

            try:
                finished_sub_slots: Optional[
                    List[EndOfSubSlotBundle]
                ] = self.full_node.full_node_store.get_finished_sub_slots(
                    self.full_node.blockchain, prev_b, cc_challenge_hash
                )
                if finished_sub_slots is None:
                    return None

                if (
                    len(finished_sub_slots) > 0
                    and pos_sub_slot is not None
                    and finished_sub_slots[-1] != pos_sub_slot[0]
                ):
                    self.log.error("Have different sub-slots than is required to farm this block")
                    return None
            except ValueError as e:
                self.log.warning(f"Value Error: {e}")
                return None
            if prev_b is None:
                pool_target = PoolTarget(
                    self.full_node.constants.GENESIS_PRE_FARM_POOL_PUZZLE_HASH,
                    uint32(0),
                )
                farmer_ph = self.full_node.constants.GENESIS_PRE_FARM_FARMER_PUZZLE_HASH
            else:
                farmer_ph = request.farmer_puzzle_hash
                if request.proof_of_space.pool_contract_puzzle_hash is not None:
                    pool_target = PoolTarget(request.proof_of_space.pool_contract_puzzle_hash, uint32(0))
                else:
                    assert request.pool_target is not None
                    pool_target = request.pool_target

            if peak is None or peak.height <= self.full_node.constants.MAX_SUB_SLOT_BLOCKS:
                difficulty = self.full_node.constants.DIFFICULTY_STARTING
                sub_slot_iters = self.full_node.constants.SUB_SLOT_ITERS_STARTING
            else:
                difficulty = uint64(peak.weight - self.full_node.blockchain.block_record(peak.prev_hash).weight)
                sub_slot_iters = peak.sub_slot_iters
                for sub_slot in finished_sub_slots:
                    if sub_slot.challenge_chain.new_difficulty is not None:
                        difficulty = sub_slot.challenge_chain.new_difficulty
                    if sub_slot.challenge_chain.new_sub_slot_iters is not None:
                        sub_slot_iters = sub_slot.challenge_chain.new_sub_slot_iters

            required_iters: uint64 = calculate_iterations_quality(
                self.full_node.constants.DIFFICULTY_CONSTANT_FACTOR,
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

            # The block's timestamp must be greater than the previous transaction block's timestamp
            timestamp = uint64(int(time.time()))
            curr: Optional[BlockRecord] = prev_b
            while curr is not None and not curr.is_transaction_block and curr.height != 0:
                curr = self.full_node.blockchain.try_block_record(curr.prev_hash)
            if curr is not None:
                assert curr.timestamp is not None
                if timestamp <= curr.timestamp:
                    timestamp = uint64(int(curr.timestamp + 1))

            self.log.info("Starting to make the unfinished block")
            unfinished_block: UnfinishedBlock = create_unfinished_block(
                self.full_node.constants,
                total_iters_pos_slot,
                sub_slot_iters,
                request.signage_point_index,
                sp_iters,
                ip_iters,
                request.proof_of_space,
                cc_challenge_hash,
                farmer_ph,
                pool_target,
                get_plot_sig,
                get_pool_sig,
                sp_vdfs,
                timestamp,
                self.full_node.blockchain,
                b"",
                block_generator,
                aggregate_signature,
                additions,
                removals,
                prev_b,
                finished_sub_slots,
            )
            self.log.info("Made the unfinished block")
            if prev_b is not None:
                height = uint32(prev_b.height + 1)
            else:
                height = uint32(0)
            self.full_node.full_node_store.add_candidate_block(quality_string, height, unfinished_block)

            foliage_sb_data_hash = unfinished_block.foliage.foliage_block_data.get_hash()
            if unfinished_block.is_transaction_block():
                foliage_transaction_block_hash = unfinished_block.foliage.foliage_transaction_block_hash
            else:
                foliage_transaction_block_hash = bytes32([0] * 32)
            assert foliage_transaction_block_hash is not None

            message = farmer_protocol.RequestSignedValues(
                quality_string,
                foliage_sb_data_hash,
                foliage_transaction_block_hash,
            )
            await peer.send_message(make_msg(ProtocolMessageTypes.request_signed_values, message))

            # Adds backup in case the first one fails
            if unfinished_block.is_transaction_block() and unfinished_block.transactions_generator is not None:
                unfinished_block_backup = create_unfinished_block(
                    self.full_node.constants,
                    total_iters_pos_slot,
                    sub_slot_iters,
                    request.signage_point_index,
                    sp_iters,
                    ip_iters,
                    request.proof_of_space,
                    cc_challenge_hash,
                    farmer_ph,
                    pool_target,
                    get_plot_sig,
                    get_pool_sig,
                    sp_vdfs,
                    timestamp,
                    self.full_node.blockchain,
                    b"",
                    None,
                    G2Element(),
                    None,
                    None,
                    prev_b,
                    finished_sub_slots,
                )

                self.full_node.full_node_store.add_candidate_block(
                    quality_string, height, unfinished_block_backup, backup=True
                )
        return None

    @api_request(peer_required=True)
    async def signed_values(
        self, farmer_request: farmer_protocol.SignedValues, peer: WSChiaConnection
    ) -> Optional[Message]:
        """
        Signature of header hash, by the harvester. This is enough to create an unfinished
        block, which only needs a Proof of Time to be finished. If the signature is valid,
        we call the unfinished_block routine.
        """
        candidate_tuple: Optional[Tuple[uint32, UnfinishedBlock]] = self.full_node.full_node_store.get_candidate_block(
            farmer_request.quality_string
        )

        if candidate_tuple is None:
            self.log.warning(f"Quality string {farmer_request.quality_string} not found in database")
            return None
        height, candidate = candidate_tuple

        if not AugSchemeMPL.verify(
            candidate.reward_chain_block.proof_of_space.plot_public_key,
            candidate.foliage.foliage_block_data.get_hash(),
            farmer_request.foliage_block_data_signature,
        ):
            self.log.warning("Signature not valid. There might be a collision in plots. Ignore this during tests.")
            return None

        fsb2 = dataclasses.replace(
            candidate.foliage,
            foliage_block_data_signature=farmer_request.foliage_block_data_signature,
        )
        if candidate.is_transaction_block():
            fsb2 = dataclasses.replace(
                fsb2, foliage_transaction_block_signature=farmer_request.foliage_transaction_block_signature
            )

        new_candidate = dataclasses.replace(candidate, foliage=fsb2)
        if not self.full_node.has_valid_pool_sig(new_candidate):
            self.log.warning("Trying to make a pre-farm block but height is not 0")
            return None

        # Propagate to ourselves (which validates and does further propagations)
        try:
            await self.full_node.add_unfinished_block(new_candidate, None, True)
        except Exception as e:
            # If we have an error with this block, try making an empty block
            self.full_node.log.error(f"Error farming block {e} {new_candidate}")
            candidate_tuple = self.full_node.full_node_store.get_candidate_block(
                farmer_request.quality_string, backup=True
            )
            if candidate_tuple is not None:
                height, unfinished_block = candidate_tuple
                self.full_node.full_node_store.add_candidate_block(
                    farmer_request.quality_string, height, unfinished_block, False
                )
                # All unfinished blocks that we create will have the foliage transaction block and hash
                assert unfinished_block.foliage.foliage_transaction_block_hash is not None
                message = farmer_protocol.RequestSignedValues(
                    farmer_request.quality_string,
                    unfinished_block.foliage.foliage_block_data.get_hash(),
                    unfinished_block.foliage.foliage_transaction_block_hash,
                )
                await peer.send_message(make_msg(ProtocolMessageTypes.request_signed_values, message))
        return None

    # TIMELORD PROTOCOL
    @api_request(peer_required=True)
    async def new_infusion_point_vdf(
        self, request: timelord_protocol.NewInfusionPointVDF, peer: WSChiaConnection
    ) -> Optional[Message]:
        if self.full_node.sync_store.get_sync_mode():
            return None
        # Lookup unfinished blocks
        async with self.full_node.timelord_lock:
            return await self.full_node.new_infusion_point_vdf(request, peer)

    @api_request(peer_required=True)
    async def new_signage_point_vdf(
        self, request: timelord_protocol.NewSignagePointVDF, peer: WSChiaConnection
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

    @api_request(peer_required=True)
    async def new_end_of_sub_slot_vdf(
        self, request: timelord_protocol.NewEndOfSubSlotVDF, peer: WSChiaConnection
    ) -> Optional[Message]:
        if self.full_node.sync_store.get_sync_mode():
            return None
        if (
            self.full_node.full_node_store.get_sub_slot(request.end_of_sub_slot_bundle.challenge_chain.get_hash())
            is not None
        ):
            return None
        # Calls our own internal message to handle the end of sub slot, and potentially broadcasts to other peers.
        msg, added = await self.full_node.add_end_of_sub_slot(request.end_of_sub_slot_bundle, peer)
        if not added:
            self.log.error(
                f"Was not able to add end of sub-slot: "
                f"{request.end_of_sub_slot_bundle.challenge_chain.challenge_chain_end_of_slot_vdf.challenge}. "
                f"Re-sending new-peak to timelord"
            )
            await self.full_node.send_peak_to_timelords(peer=peer)
            return None
        else:
            return msg

    @api_request()
    async def request_block_header(self, request: wallet_protocol.RequestBlockHeader) -> Optional[Message]:
        header_hash = self.full_node.blockchain.height_to_hash(request.height)
        if header_hash is None:
            msg = make_msg(ProtocolMessageTypes.reject_header_request, RejectHeaderRequest(request.height))
            return msg
        block: Optional[FullBlock] = await self.full_node.block_store.get_full_block(header_hash)
        if block is None:
            return None

        tx_removals: List[bytes32] = []
        tx_additions: List[Coin] = []

        if block.transactions_generator is not None:
            block_generator: Optional[BlockGenerator] = await self.full_node.blockchain.get_block_generator(block)
            # get_block_generator() returns None in case the block we specify
            # does not have a generator (i.e. is not a transaction block).
            # in this case we've already made sure `block` does have a
            # transactions_generator, so the block_generator should always be set
            assert block_generator is not None, "failed to get block_generator for tx-block"

            npc_result = await asyncio.get_running_loop().run_in_executor(
                self.executor,
                functools.partial(
                    get_name_puzzle_conditions,
                    block_generator,
                    self.full_node.constants.MAX_BLOCK_COST_CLVM,
                    mempool_mode=False,
                    height=request.height,
                    constants=self.full_node.constants,
                ),
            )

            tx_removals, tx_additions = tx_removals_and_additions(npc_result.conds)
        header_block = get_block_header(block, tx_additions, tx_removals)
        msg = make_msg(
            ProtocolMessageTypes.respond_block_header,
            wallet_protocol.RespondBlockHeader(header_block),
        )
        return msg

    @api_request()
    async def request_additions(self, request: wallet_protocol.RequestAdditions) -> Optional[Message]:
        if request.header_hash is None:
            header_hash: Optional[bytes32] = self.full_node.blockchain.height_to_hash(request.height)
        else:
            header_hash = request.header_hash
        if header_hash is None:
            raise ValueError(f"Block at height {request.height} not found")

        # Note: this might return bad data if there is a reorg in this time
        additions = await self.full_node.coin_store.get_coins_added_at_height(request.height)

        if self.full_node.blockchain.height_to_hash(request.height) != header_hash:
            raise ValueError(f"Block {header_hash} no longer in chain, or invalid header_hash")

        puzzlehash_coins_map: Dict[bytes32, List[Coin]] = {}
        for coin_record in additions:
            if coin_record.coin.puzzle_hash in puzzlehash_coins_map:
                puzzlehash_coins_map[coin_record.coin.puzzle_hash].append(coin_record.coin)
            else:
                puzzlehash_coins_map[coin_record.coin.puzzle_hash] = [coin_record.coin]

        coins_map: List[Tuple[bytes32, List[Coin]]] = []
        proofs_map: List[Tuple[bytes32, bytes, Optional[bytes]]] = []

        if request.puzzle_hashes is None:
            for puzzle_hash, coins in puzzlehash_coins_map.items():
                coins_map.append((puzzle_hash, coins))
            response = wallet_protocol.RespondAdditions(request.height, header_hash, coins_map, None)
        else:
            # Create addition Merkle set
            addition_merkle_set = MerkleSet()
            # Addition Merkle set contains puzzlehash and hash of all coins with that puzzlehash
            for puzzle, coins in puzzlehash_coins_map.items():
                addition_merkle_set.add_already_hashed(puzzle)
                addition_merkle_set.add_already_hashed(hash_coin_ids([c.name() for c in coins]))

            for puzzle_hash in request.puzzle_hashes:
                # This is a proof of inclusion if it's in (result==True), or exclusion of it's not in
                result, proof = addition_merkle_set.is_included_already_hashed(puzzle_hash)
                if puzzle_hash in puzzlehash_coins_map:
                    coins_map.append((puzzle_hash, puzzlehash_coins_map[puzzle_hash]))
                    hash_coin_str = hash_coin_ids([c.name() for c in puzzlehash_coins_map[puzzle_hash]])
                    # This is a proof of inclusion of all coin ids that have this ph
                    result_2, proof_2 = addition_merkle_set.is_included_already_hashed(hash_coin_str)
                    assert result
                    assert result_2
                    proofs_map.append((puzzle_hash, proof, proof_2))
                else:
                    coins_map.append((puzzle_hash, []))
                    assert not result
                    proofs_map.append((puzzle_hash, proof, None))
            response = wallet_protocol.RespondAdditions(request.height, header_hash, coins_map, proofs_map)
        return make_msg(ProtocolMessageTypes.respond_additions, response)

    @api_request()
    async def request_removals(self, request: wallet_protocol.RequestRemovals) -> Optional[Message]:
        block: Optional[FullBlock] = await self.full_node.block_store.get_full_block(request.header_hash)

        # We lock so that the coin store does not get modified
        peak_height = self.full_node.blockchain.get_peak_height()
        if (
            block is None
            or block.is_transaction_block() is False
            or block.height != request.height
            or (peak_height is not None and block.height > peak_height)
            or self.full_node.blockchain.height_to_hash(block.height) != request.header_hash
        ):
            reject = wallet_protocol.RejectRemovalsRequest(request.height, request.header_hash)
            msg = make_msg(ProtocolMessageTypes.reject_removals_request, reject)
            return msg

        assert block is not None and block.foliage_transaction_block is not None

        # Note: this might return bad data if there is a reorg in this time
        all_removals: List[CoinRecord] = await self.full_node.coin_store.get_coins_removed_at_height(block.height)

        if self.full_node.blockchain.height_to_hash(block.height) != request.header_hash:
            raise ValueError(f"Block {block.header_hash} no longer in chain")

        all_removals_dict: Dict[bytes32, Coin] = {}
        for coin_record in all_removals:
            all_removals_dict[coin_record.coin.name()] = coin_record.coin

        coins_map: List[Tuple[bytes32, Optional[Coin]]] = []
        proofs_map: List[Tuple[bytes32, bytes]] = []

        # If there are no transactions, respond with empty lists
        if block.transactions_generator is None:
            proofs: Optional[List[Tuple[bytes32, bytes]]]
            if request.coin_names is None:
                proofs = None
            else:
                proofs = []
            response = wallet_protocol.RespondRemovals(block.height, block.header_hash, [], proofs)
        elif request.coin_names is None or len(request.coin_names) == 0:
            for removed_name, removed_coin in all_removals_dict.items():
                coins_map.append((removed_name, removed_coin))
            response = wallet_protocol.RespondRemovals(block.height, block.header_hash, coins_map, None)
        else:
            assert block.transactions_generator
            removal_merkle_set = MerkleSet()
            for removed_name, removed_coin in all_removals_dict.items():
                removal_merkle_set.add_already_hashed(removed_name)
            assert removal_merkle_set.get_root() == block.foliage_transaction_block.removals_root
            for coin_name in request.coin_names:
                result, proof = removal_merkle_set.is_included_already_hashed(coin_name)
                proofs_map.append((coin_name, proof))
                if coin_name in all_removals_dict:
                    removed_coin = all_removals_dict[coin_name]
                    coins_map.append((coin_name, removed_coin))
                    assert result
                else:
                    coins_map.append((coin_name, None))
                    assert not result
            response = wallet_protocol.RespondRemovals(block.height, block.header_hash, coins_map, proofs_map)

        msg = make_msg(ProtocolMessageTypes.respond_removals, response)
        return msg

    @api_request()
    async def send_transaction(
        self, request: wallet_protocol.SendTransaction, *, test: bool = False
    ) -> Optional[Message]:
        spend_name = request.transaction.name()
        if self.full_node.mempool_manager.get_spendbundle(spend_name) is not None:
            self.full_node.mempool_manager.remove_seen(spend_name)
            response = wallet_protocol.TransactionAck(spend_name, uint8(MempoolInclusionStatus.SUCCESS), None)
            return make_msg(ProtocolMessageTypes.transaction_ack, response)

        await self.full_node.transaction_queue.put(
            TransactionQueueEntry(request.transaction, None, spend_name, None, test), peer_id=None, high_priority=True
        )
        # Waits for the transaction to go into the mempool, times out after 45 seconds.
        status, error = None, None
        sleep_time = 0.01
        for i in range(int(45 / sleep_time)):
            await asyncio.sleep(sleep_time)
            for potential_name, potential_status, potential_error in self.full_node.transaction_responses:
                if spend_name == potential_name:
                    status = potential_status
                    error = potential_error
                    break
            if status is not None:
                break
        if status is None:
            response = wallet_protocol.TransactionAck(spend_name, uint8(MempoolInclusionStatus.PENDING), None)
        else:
            error_name = error.name if error is not None else None
            if status == MempoolInclusionStatus.SUCCESS:
                response = wallet_protocol.TransactionAck(spend_name, uint8(status.value), error_name)
            else:
                # If if failed/pending, but it previously succeeded (in mempool), this is idempotence, return SUCCESS
                if self.full_node.mempool_manager.get_spendbundle(spend_name) is not None:
                    response = wallet_protocol.TransactionAck(
                        spend_name, uint8(MempoolInclusionStatus.SUCCESS.value), None
                    )
                else:
                    response = wallet_protocol.TransactionAck(spend_name, uint8(status.value), error_name)
        return make_msg(ProtocolMessageTypes.transaction_ack, response)

    @api_request()
    async def request_puzzle_solution(self, request: wallet_protocol.RequestPuzzleSolution) -> Optional[Message]:
        coin_name = request.coin_name
        height = request.height
        coin_record = await self.full_node.coin_store.get_coin_record(coin_name)
        reject = wallet_protocol.RejectPuzzleSolution(coin_name, height)
        reject_msg = make_msg(ProtocolMessageTypes.reject_puzzle_solution, reject)
        if coin_record is None or coin_record.spent_block_index != height:
            return reject_msg

        header_hash: Optional[bytes32] = self.full_node.blockchain.height_to_hash(height)
        if header_hash is None:
            return reject_msg

        block: Optional[BlockInfo] = await self.full_node.block_store.get_block_info(header_hash)

        if block is None or block.transactions_generator is None:
            return reject_msg

        block_generator: Optional[BlockGenerator] = await self.full_node.blockchain.get_block_generator(block)
        assert block_generator is not None
        try:
            spend_info = await asyncio.get_running_loop().run_in_executor(
                self.executor, get_puzzle_and_solution_for_coin, block_generator, coin_record.coin, 0
            )
        except ValueError:
            return reject_msg
        wrapper = PuzzleSolutionResponse(coin_name, height, spend_info.puzzle, spend_info.solution)
        response = wallet_protocol.RespondPuzzleSolution(wrapper)
        response_msg = make_msg(ProtocolMessageTypes.respond_puzzle_solution, response)
        return response_msg

    @api_request()
    async def request_block_headers(self, request: wallet_protocol.RequestBlockHeaders) -> Optional[Message]:
        """Returns header blocks by directly streaming bytes into Message

        This method should be used instead of RequestHeaderBlocks
        """
        reject = RejectBlockHeaders(request.start_height, request.end_height)

        if request.end_height < request.start_height or request.end_height - request.start_height > 128:
            return make_msg(ProtocolMessageTypes.reject_block_headers, reject)
        if self.full_node.block_store.db_wrapper.db_version == 2:
            try:
                blocks_bytes = await self.full_node.block_store.get_block_bytes_in_range(
                    request.start_height, request.end_height
                )
            except ValueError:
                return make_msg(ProtocolMessageTypes.reject_block_headers, reject)

        else:
            height_to_hash = self.full_node.blockchain.height_to_hash
            header_hashes: List[bytes32] = []
            for i in range(request.start_height, request.end_height + 1):
                header_hash: Optional[bytes32] = height_to_hash(uint32(i))
                if header_hash is None:
                    return make_msg(ProtocolMessageTypes.reject_header_blocks, reject)
                header_hashes.append(header_hash)

            blocks_bytes = await self.full_node.block_store.get_block_bytes_by_hash(header_hashes)
        if len(blocks_bytes) != (request.end_height - request.start_height + 1):  # +1 because interval is inclusive
            return make_msg(ProtocolMessageTypes.reject_block_headers, reject)
        return_filter = request.return_filter
        header_blocks_bytes: List[bytes] = [header_block_from_block(memoryview(b), return_filter) for b in blocks_bytes]

        # we're building the RespondHeaderBlocks manually to avoid cost of
        # dynamic serialization
        # ---
        # we start building RespondBlockHeaders response (start_height, end_height)
        # and then need to define size of list object
        respond_header_blocks_manually_streamed: bytes = (
            bytes(uint32(request.start_height))
            + bytes(uint32(request.end_height))
            + len(header_blocks_bytes).to_bytes(4, "big", signed=False)
        )
        # and now stream the whole list in bytes
        respond_header_blocks_manually_streamed += b"".join(header_blocks_bytes)
        return make_msg(ProtocolMessageTypes.respond_block_headers, respond_header_blocks_manually_streamed)

    @api_request()
    async def request_header_blocks(self, request: wallet_protocol.RequestHeaderBlocks) -> Optional[Message]:
        """DEPRECATED: please use RequestBlockHeaders"""
        if (
            request.end_height < request.start_height
            or request.end_height - request.start_height > self.full_node.constants.MAX_BLOCK_COUNT_PER_REQUESTS
        ):
            return None
        height_to_hash = self.full_node.blockchain.height_to_hash
        header_hashes: List[bytes32] = []
        for i in range(request.start_height, request.end_height + 1):
            header_hash: Optional[bytes32] = height_to_hash(uint32(i))
            if header_hash is None:
                reject = RejectHeaderBlocks(request.start_height, request.end_height)
                msg = make_msg(ProtocolMessageTypes.reject_header_blocks, reject)
                return msg
            header_hashes.append(header_hash)

        blocks: List[FullBlock] = await self.full_node.block_store.get_blocks_by_hash(header_hashes)
        header_blocks = []
        for block in blocks:
            added_coins_records_coroutine = self.full_node.coin_store.get_coins_added_at_height(block.height)
            removed_coins_records_coroutine = self.full_node.coin_store.get_coins_removed_at_height(block.height)
            added_coins_records, removed_coins_records = await asyncio.gather(
                added_coins_records_coroutine, removed_coins_records_coroutine
            )
            added_coins = [record.coin for record in added_coins_records if not record.coinbase]
            removal_names = [record.coin.name() for record in removed_coins_records]
            header_block = get_block_header(block, added_coins, removal_names)
            header_blocks.append(header_block)

        msg = make_msg(
            ProtocolMessageTypes.respond_header_blocks,
            wallet_protocol.RespondHeaderBlocks(request.start_height, request.end_height, header_blocks),
        )
        return msg

    @api_request(bytes_required=True, execute_task=True)
    async def respond_compact_proof_of_time(
        self, request: timelord_protocol.RespondCompactProofOfTime, request_bytes: bytes = b""
    ) -> None:
        if self.full_node.sync_store.get_sync_mode():
            return None
        name = std_hash(request_bytes)
        if name in self.full_node.compact_vdf_requests:
            self.log.debug(f"Ignoring CompactProofOfTime: {request}, already requested")
            return None

        self.full_node.compact_vdf_requests.add(name)

        # this semaphore will only allow a limited number of tasks call
        # new_compact_vdf() at a time, since it can be expensive
        try:
            async with self.full_node.compact_vdf_sem.acquire():
                try:
                    await self.full_node.add_compact_proof_of_time(request)
                finally:
                    self.full_node.compact_vdf_requests.remove(name)
        except LimitedSemaphoreFullError:
            self.log.debug(f"Ignoring CompactProofOfTime: {request}, _waiters")

        return None

    @api_request(peer_required=True, bytes_required=True, execute_task=True)
    async def new_compact_vdf(
        self, request: full_node_protocol.NewCompactVDF, peer: WSChiaConnection, request_bytes: bytes = b""
    ) -> None:
        if self.full_node.sync_store.get_sync_mode():
            return None

        name = std_hash(request_bytes)
        if name in self.full_node.compact_vdf_requests:
            self.log.debug("Ignoring NewCompactVDF, already requested: %s %s", peer.get_peer_logging(), request)
            return None
        self.full_node.compact_vdf_requests.add(name)

        # this semaphore will only allow a limited number of tasks call
        # new_compact_vdf() at a time, since it can be expensive
        try:
            async with self.full_node.compact_vdf_sem.acquire():
                try:
                    await self.full_node.new_compact_vdf(request, peer)
                finally:
                    self.full_node.compact_vdf_requests.remove(name)
        except LimitedSemaphoreFullError:
            self.log.debug("Ignoring NewCompactVDF, limited semaphore full: %s %s", peer.get_peer_logging(), request)
            return None

        return None

    @api_request(peer_required=True, reply_types=[ProtocolMessageTypes.respond_compact_vdf])
    async def request_compact_vdf(self, request: full_node_protocol.RequestCompactVDF, peer: WSChiaConnection) -> None:
        if self.full_node.sync_store.get_sync_mode():
            return None
        await self.full_node.request_compact_vdf(request, peer)
        return None

    @api_request(peer_required=True)
    async def respond_compact_vdf(self, request: full_node_protocol.RespondCompactVDF, peer: WSChiaConnection) -> None:
        if self.full_node.sync_store.get_sync_mode():
            return None
        await self.full_node.add_compact_vdf(request, peer)
        return None

    @api_request(peer_required=True)
    async def register_interest_in_puzzle_hash(
        self, request: wallet_protocol.RegisterForPhUpdates, peer: WSChiaConnection
    ) -> Message:
        trusted = self.is_trusted(peer)
        if trusted:
            max_subscriptions = self.full_node.config.get("trusted_max_subscribe_items", 2000000)
            max_items = self.full_node.config.get("trusted_max_subscribe_response_items", 500000)
        else:
            max_subscriptions = self.full_node.config.get("max_subscribe_items", 200000)
            max_items = self.full_node.config.get("max_subscribe_response_items", 100000)

        # the returned puzzle hashes are the ones we ended up subscribing to.
        # It will have filtered duplicates and ones exceeding the subscription
        # limit.
        puzzle_hashes = self.full_node.subscriptions.add_ph_subscriptions(
            peer.peer_node_id, request.puzzle_hashes, max_subscriptions
        )

        start_time = time.monotonic()

        # Note that coin state updates may arrive out-of-order on the client side.
        # We add the subscription before we're done collecting all the coin
        # state that goes into the response. CoinState updates may be sent
        # before we send the response

        # Send all coins with requested puzzle hash that have been created after the specified height
        states: Set[CoinState] = await self.full_node.coin_store.get_coin_states_by_puzzle_hashes(
            include_spent_coins=True, puzzle_hashes=puzzle_hashes, min_height=request.min_height, max_items=max_items
        )
        max_items -= len(states)

        hint_coin_ids: Set[bytes32] = set()
        if max_items > 0:
            for puzzle_hash in puzzle_hashes:
                ph_hint_coins = await self.full_node.hint_store.get_coin_ids(puzzle_hash, max_items=max_items)
                hint_coin_ids.update(ph_hint_coins)
                max_items -= len(ph_hint_coins)
                if max_items <= 0:
                    break

        hint_states: List[CoinState] = []
        if len(hint_coin_ids) > 0:
            hint_states = await self.full_node.coin_store.get_coin_states_by_ids(
                include_spent_coins=True,
                coin_ids=hint_coin_ids,
                min_height=request.min_height,
                max_items=len(hint_coin_ids),
            )
            states.update(hint_states)

        end_time = time.monotonic()

        truncated = max_items <= 0

        if truncated or end_time - start_time > 5:
            self.log.log(
                logging.WARNING if trusted and truncated else logging.INFO,
                "RegisterForPhUpdates resulted in %d coin states. "
                "Request had %d (unique) puzzle hashes and matched %d hints. %s"
                "The request took %0.2fs",
                len(states),
                len(puzzle_hashes),
                len(hint_states),
                "The response was truncated. " if truncated else "",
                end_time - start_time,
            )

        response = wallet_protocol.RespondToPhUpdates(request.puzzle_hashes, request.min_height, list(states))
        msg = make_msg(ProtocolMessageTypes.respond_to_ph_update, response)
        return msg

    @api_request(peer_required=True)
    async def register_interest_in_coin(
        self, request: wallet_protocol.RegisterForCoinUpdates, peer: WSChiaConnection
    ) -> Message:
        if self.is_trusted(peer):
            max_subscriptions = self.full_node.config.get("trusted_max_subscribe_items", 2000000)
            max_items = self.full_node.config.get("trusted_max_subscribe_response_items", 500000)
        else:
            max_subscriptions = self.full_node.config.get("max_subscribe_items", 200000)
            max_items = self.full_node.config.get("max_subscribe_response_items", 100000)

        # TODO: apparently we have tests that expect to receive a
        # RespondToCoinUpdates even when subscribing to the same coin multiple
        # times, so we can't optimize away such DB lookups (yet)
        self.full_node.subscriptions.add_coin_subscriptions(peer.peer_node_id, request.coin_ids, max_subscriptions)

        states: List[CoinState] = await self.full_node.coin_store.get_coin_states_by_ids(
            include_spent_coins=True, coin_ids=set(request.coin_ids), min_height=request.min_height, max_items=max_items
        )

        response = wallet_protocol.RespondToCoinUpdates(request.coin_ids, request.min_height, states)
        msg = make_msg(ProtocolMessageTypes.respond_to_coin_update, response)
        return msg

    @api_request()
    async def request_children(self, request: wallet_protocol.RequestChildren) -> Optional[Message]:
        coin_records: List[CoinRecord] = await self.full_node.coin_store.get_coin_records_by_parent_ids(
            True, [request.coin_name]
        )
        states = [record.coin_state for record in coin_records]
        response = wallet_protocol.RespondChildren(states)
        msg = make_msg(ProtocolMessageTypes.respond_children, response)
        return msg

    @api_request()
    async def request_ses_hashes(self, request: wallet_protocol.RequestSESInfo) -> Message:
        """Returns the start and end height of a sub-epoch for the height specified in request"""

        ses_height = self.full_node.blockchain.get_ses_heights()
        start_height = request.start_height
        end_height = request.end_height
        ses_hash_heights = []
        ses_reward_hashes = []

        for idx, ses_start_height in enumerate(ses_height):
            if idx == len(ses_height) - 1:
                break

            next_ses_height = ses_height[idx + 1]
            # start_ses_hash
            if ses_start_height <= start_height < next_ses_height:
                ses_hash_heights.append([ses_start_height, next_ses_height])
                ses: SubEpochSummary = self.full_node.blockchain.get_ses(ses_start_height)
                ses_reward_hashes.append(ses.reward_chain_hash)
                if ses_start_height < end_height < next_ses_height:
                    break
                else:
                    if idx == len(ses_height) - 2:
                        break
                    # else add extra ses as request start <-> end spans two ses
                    next_next_height = ses_height[idx + 2]
                    ses_hash_heights.append([next_ses_height, next_next_height])
                    nex_ses: SubEpochSummary = self.full_node.blockchain.get_ses(next_ses_height)
                    ses_reward_hashes.append(nex_ses.reward_chain_hash)
                    break

        response = RespondSESInfo(ses_reward_hashes, ses_hash_heights)
        msg = make_msg(ProtocolMessageTypes.respond_ses_hashes, response)
        return msg

    @api_request(peer_required=True, reply_types=[ProtocolMessageTypes.respond_fee_estimates])
    async def request_fee_estimates(self, request: wallet_protocol.RequestFeeEstimates) -> Message:
        def get_fee_estimates(est: FeeEstimatorInterface, req_times: List[uint64]) -> List[FeeEstimate]:
            now = datetime.now(timezone.utc)
            utc_time = now.replace(tzinfo=timezone.utc)
            utc_now = int(utc_time.timestamp())
            deltas = [max(0, req_ts - utc_now) for req_ts in req_times]
            fee_rates = [est.estimate_fee_rate(time_offset_seconds=d) for d in deltas]
            v1_fee_rates = [fee_rate_v2_to_v1(est) for est in fee_rates]
            return [FeeEstimate(None, req_ts, fee_rate) for req_ts, fee_rate in zip(req_times, v1_fee_rates)]

        fee_estimates: List[FeeEstimate] = get_fee_estimates(
            self.full_node.mempool_manager.mempool.fee_estimator, request.time_targets
        )
        response = RespondFeeEstimates(FeeEstimateGroup(error=None, estimates=fee_estimates))
        msg = make_msg(ProtocolMessageTypes.respond_fee_estimates, response)
        return msg

    def is_trusted(self, peer: WSChiaConnection) -> bool:
        return self.server.is_trusted_peer(peer, self.full_node.config.get("trusted_peers", {}))
