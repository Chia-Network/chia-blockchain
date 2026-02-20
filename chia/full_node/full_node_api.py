from __future__ import annotations

import asyncio
import logging
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING, ClassVar

from chia_rs import (
    AugSchemeMPL,
    BlockRecord,
    EndOfSubSlotBundle,
    FoliageBlockData,
    FoliageTransactionBlock,
    FullBlock,
    G1Element,
    G2Element,
    PoolTarget,
    RewardChainBlockUnfinished,
    UnfinishedBlock,
)
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint8, uint32, uint64, uint128
from chiabip158 import PyBIP158

from chia.consensus.block_creation import create_unfinished_block
from chia.consensus.blockchain import BlockchainMutexPriority
from chia.consensus.pot_iterations import calculate_ip_iters, calculate_iterations_quality, calculate_sp_iters
from chia.consensus.signage_point import SignagePoint
from chia.full_node._full_node_api_wallet import _FullNodeApiWalletMixin, full_node_metadata
from chia.full_node.tx_processing_queue import PeerWithTx, TransactionQueueEntry, TransactionQueueFull
from chia.protocols import farmer_protocol, full_node_protocol, introducer_protocol, timelord_protocol
from chia.protocols.full_node_protocol import RejectBlock, RejectBlocks
from chia.protocols.outbound_message import Message, make_msg
from chia.protocols.protocol_message_types import ProtocolMessageTypes
from chia.protocols.protocol_timing import CONSENSUS_ERROR_BAN_SECONDS, RATE_LIMITER_BAN_SECONDS
from chia.server.api_protocol import ApiMetadata
from chia.server.server import ChiaServer
from chia.server.ws_connection import WSChiaConnection
from chia.types.blockchain_format.proof_of_space import verify_and_get_quality_string
from chia.types.clvm_cost import QUOTE_BYTES, QUOTE_EXECUTION_COST
from chia.types.generator_types import NewBlockGenerator
from chia.types.peer_info import PeerInfo
from chia.util.errors import Err, ValidationError
from chia.util.hash import std_hash
from chia.util.limited_semaphore import LimitedSemaphoreFullError
from chia.util.task_referencer import create_referenced_task

if TYPE_CHECKING:
    from chia.full_node.full_node import FullNode
else:
    FullNode = object


async def tx_request_and_timeout(full_node: FullNode, transaction_id: bytes32, task_id: bytes32) -> None:
    """
    Request a transaction from peers that advertised it, until we either
    receive it or timeout.
    """
    tried_peers: set[bytes32] = set()
    try:
        # Limit to asking a few peers, it's possible that this tx got included on chain already
        # Highly unlikely that the peers that advertised a tx don't respond to a request. Also, if we
        # drop some transactions, we don't want to re-fetch too many times
        for _ in range(5):
            peers_with_tx = full_node.full_node_store.peers_with_tx.get(transaction_id)
            if peers_with_tx is None:
                break
            peers_to_try = set(peers_with_tx) - tried_peers
            if len(peers_to_try) == 0:
                break
            peer_id = peers_to_try.pop()
            tried_peers.add(peer_id)
            assert full_node.server is not None
            if peer_id not in full_node.server.all_connections:
                continue
            random_peer = full_node.server.all_connections[peer_id]
            request_tx = full_node_protocol.RequestTransaction(transaction_id)
            msg = make_msg(ProtocolMessageTypes.request_transaction, request_tx)
            await random_peer.send_message(msg)
            await asyncio.sleep(5)
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


class FullNodeAPI(_FullNodeApiWalletMixin):
    if TYPE_CHECKING:
        from chia.apis.full_node_stub import FullNodeApiStub

        # Verify this class implements the FullNodeApiStub protocol
        def _protocol_check(self: FullNodeAPI) -> FullNodeApiStub:
            return self

    log: logging.Logger
    full_node: FullNode
    executor: ThreadPoolExecutor
    metadata: ClassVar[ApiMetadata] = full_node_metadata

    def __init__(self, full_node: FullNode) -> None:
        self.log = logging.getLogger(__name__)
        self.full_node = full_node
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="node-api-")

    @property
    def server(self) -> ChiaServer:
        assert self.full_node.server is not None
        return self.full_node.server

    def ready(self) -> bool:
        return self.full_node.initialized

    @metadata.request(peer_required=True, reply_types=[ProtocolMessageTypes.respond_peers])
    async def request_peers(self, _request: full_node_protocol.RequestPeers, peer: WSChiaConnection) -> Message | None:
        if peer.peer_server_port is None:
            return None
        peer_info = PeerInfo(peer.peer_info.host, peer.peer_server_port)
        if self.full_node.full_node_peers is not None:
            msg = await self.full_node.full_node_peers.request_peers(peer_info)
            return msg
        return None

    @metadata.request(peer_required=True)
    async def respond_peers(self, request: full_node_protocol.RespondPeers, peer: WSChiaConnection) -> Message | None:
        self.log.debug(f"Received {len(request.peer_list)} peers")
        if self.full_node.full_node_peers is not None:
            await self.full_node.full_node_peers.add_peers(request.peer_list, peer.get_peer_info(), True)
        return None

    @metadata.request(peer_required=True)
    async def respond_peers_introducer(
        self, request: introducer_protocol.RespondPeersIntroducer, peer: WSChiaConnection
    ) -> Message | None:
        self.log.debug(f"Received {len(request.peer_list)} peers from introducer")
        if self.full_node.full_node_peers is not None:
            await self.full_node.full_node_peers.add_peers(request.peer_list, peer.get_peer_info(), False)

        await peer.close()
        return None

    @metadata.request(peer_required=True, execute_task=True)
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

    @metadata.request(peer_required=True)
    async def new_transaction(
        self, transaction: full_node_protocol.NewTransaction, peer: WSChiaConnection
    ) -> Message | None:
        """
        A peer notifies us of a new transaction.
        Requests a full transaction if we haven't seen it previously, and if the fees are enough.
        """
        # Ignore if syncing
        if self.full_node.sync_store.get_sync_mode():
            return None
        if not (await self.full_node.synced()):
            return None

        # It's not reasonable to advertise a transaction with zero cost
        if transaction.cost == 0:
            self.log.warning(
                f"Banning peer {peer.peer_node_id}. Sent us a tx {transaction.transaction_id} with zero cost."
            )
            await peer.close(CONSENSUS_ERROR_BAN_SECONDS)
            return None

        # If already seen, the cost and fee must match, otherwise ban the peer
        mempool_item = self.full_node.mempool_manager.get_mempool_item(transaction.transaction_id, include_pending=True)
        if mempool_item is not None:
            # Older nodes (2.4.3 and earlier) compute the cost slightly
            # differently. They include the byte cost and execution cost of
            # the quote for the puzzle.
            tolerated_diff = QUOTE_BYTES * self.full_node.constants.COST_PER_BYTE + QUOTE_EXECUTION_COST
            if (transaction.cost != mempool_item.cost and transaction.cost != mempool_item.cost + tolerated_diff) or (
                transaction.fees != mempool_item.fee
            ):
                self.log.warning(
                    f"Banning peer {peer.peer_node_id} version {peer.version}. Sent us an already seen tx "
                    f"{transaction.transaction_id} with mismatch on cost {transaction.cost} vs validation "
                    f"cost {mempool_item.cost} and/or fee {transaction.fees} vs {mempool_item.fee}."
                )
                await peer.close(CONSENSUS_ERROR_BAN_SECONDS)
            return None

        if self.full_node.mempool_manager.is_fee_enough(transaction.fees, transaction.cost):
            # If there's current pending request just add this peer to the set of peers that have this tx
            if transaction.transaction_id in self.full_node.full_node_store.pending_tx_request:
                current_map = self.full_node.full_node_store.peers_with_tx.get(transaction.transaction_id)
                if current_map is None:
                    self.full_node.full_node_store.peers_with_tx[transaction.transaction_id] = {
                        peer.peer_node_id: PeerWithTx(
                            peer_host=peer.peer_info.host,
                            advertised_fee=transaction.fees,
                            advertised_cost=transaction.cost,
                        )
                    }
                    return None
                prev = current_map.get(peer.peer_node_id)
                if prev is not None:
                    if prev.advertised_fee != transaction.fees or prev.advertised_cost != transaction.cost:
                        self.log.warning(
                            f"Banning peer {peer.peer_node_id} version {peer.version}. Sent us a new tx "
                            f"{transaction.transaction_id} with mismatch on cost {transaction.cost} vs "
                            f"previous advertised cost {prev.advertised_cost} and/or fee {transaction.fees} "
                            f"vs previous advertised fee {prev.advertised_fee}."
                        )
                        await peer.close(CONSENSUS_ERROR_BAN_SECONDS)
                    return None
                current_map[peer.peer_node_id] = PeerWithTx(
                    peer_host=peer.peer_info.host, advertised_fee=transaction.fees, advertised_cost=transaction.cost
                )
                return None

            self.full_node.full_node_store.pending_tx_request[transaction.transaction_id] = peer.peer_node_id
            self.full_node.full_node_store.peers_with_tx[transaction.transaction_id] = {
                peer.peer_node_id: PeerWithTx(
                    peer_host=peer.peer_info.host, advertised_fee=transaction.fees, advertised_cost=transaction.cost
                )
            }

            task_id: bytes32 = bytes32.secret()
            fetch_task = create_referenced_task(
                tx_request_and_timeout(self.full_node, transaction.transaction_id, task_id)
            )
            self.full_node.full_node_store.tx_fetch_tasks[task_id] = fetch_task
            return None
        return None

    @metadata.request(reply_types=[ProtocolMessageTypes.respond_transaction])
    async def request_transaction(self, request: full_node_protocol.RequestTransaction) -> Message | None:
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

    @metadata.request(peer_required=True, bytes_required=True)
    async def respond_transaction(
        self,
        tx: full_node_protocol.RespondTransaction,
        peer: WSChiaConnection,
        tx_bytes: bytes = b"",
        test: bool = False,
    ) -> Message | None:
        """
        Receives a full transaction from peer.
        If tx is added to mempool, send tx_id to others. (new_transaction)
        """
        assert tx_bytes != b""
        spend_name = std_hash(tx_bytes)
        if spend_name in self.full_node.full_node_store.pending_tx_request:
            self.full_node.full_node_store.pending_tx_request.pop(spend_name)
        peers_with_tx = {}
        if spend_name in self.full_node.full_node_store.peers_with_tx:
            peers_with_tx = self.full_node.full_node_store.peers_with_tx.pop(spend_name)

        # TODO: Use fee in priority calculation, to prioritize high fee TXs
        try:
            self.full_node.transaction_queue.put(
                TransactionQueueEntry(tx.transaction, tx_bytes, spend_name, peer, test, peers_with_tx),
                peer.peer_node_id,
            )
        except TransactionQueueFull:
            pass  # we can't do anything here, the tx will be dropped. We might do something in the future.
        return None

    @metadata.request(reply_types=[ProtocolMessageTypes.respond_proof_of_weight])
    async def request_proof_of_weight(self, request: full_node_protocol.RequestProofOfWeight) -> Message | None:
        if self.full_node.weight_proof_handler is None:
            return None
        if self.full_node.blockchain.try_block_record(request.tip) is None:
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
            for i in range(4):
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

    @metadata.request()
    async def respond_proof_of_weight(self, request: full_node_protocol.RespondProofOfWeight) -> Message | None:
        self.log.warning("Received proof of weight too late.")
        return None

    @metadata.request(reply_types=[ProtocolMessageTypes.respond_block, ProtocolMessageTypes.reject_block])
    async def request_block(self, request: full_node_protocol.RequestBlock) -> Message | None:
        if not self.full_node.blockchain.contains_height(request.height):
            reject = RejectBlock(request.height)
            msg = make_msg(ProtocolMessageTypes.reject_block, reject)
            return msg
        header_hash: bytes32 | None = self.full_node.blockchain.height_to_hash(request.height)
        if header_hash is None:
            return make_msg(ProtocolMessageTypes.reject_block, RejectBlock(request.height))

        block: FullBlock | None = await self.full_node.block_store.get_full_block(header_hash)
        if block is not None:
            if not request.include_transaction_block and block.transactions_generator is not None:
                block = block.replace(transactions_generator=None)
            return make_msg(ProtocolMessageTypes.respond_block, full_node_protocol.RespondBlock(block))
        return make_msg(ProtocolMessageTypes.reject_block, RejectBlock(request.height))

    @metadata.request(reply_types=[ProtocolMessageTypes.respond_blocks, ProtocolMessageTypes.reject_blocks])
    async def request_blocks(self, request: full_node_protocol.RequestBlocks) -> Message | None:
        # note that we treat the request range as *inclusive*, but we check the
        # size before we bump end_height. So MAX_BLOCK_COUNT_PER_REQUESTS is off
        # by one
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
            blocks: list[FullBlock] = []
            for i in range(request.start_height, request.end_height + 1):
                header_hash_i: bytes32 | None = self.full_node.blockchain.height_to_hash(uint32(i))
                if header_hash_i is None:
                    reject = RejectBlocks(request.start_height, request.end_height)
                    return make_msg(ProtocolMessageTypes.reject_blocks, reject)

                block: FullBlock | None = await self.full_node.block_store.get_full_block(header_hash_i)
                if block is None:
                    reject = RejectBlocks(request.start_height, request.end_height)
                    return make_msg(ProtocolMessageTypes.reject_blocks, reject)
                block = block.replace(transactions_generator=None)
                blocks.append(block)
            msg = make_msg(
                ProtocolMessageTypes.respond_blocks,
                full_node_protocol.RespondBlocks(request.start_height, request.end_height, blocks),
            )
        else:
            blocks_bytes: list[bytes] = []
            for i in range(request.start_height, request.end_height + 1):
                header_hash_i = self.full_node.blockchain.height_to_hash(uint32(i))
                if header_hash_i is None:
                    reject = RejectBlocks(request.start_height, request.end_height)
                    return make_msg(ProtocolMessageTypes.reject_blocks, reject)
                block_bytes: bytes | None = await self.full_node.block_store.get_full_block_bytes(header_hash_i)
                if block_bytes is None:
                    reject = RejectBlocks(request.start_height, request.end_height)
                    msg = make_msg(ProtocolMessageTypes.reject_blocks, reject)
                    return msg

                blocks_bytes.append(block_bytes)

            respond_blocks_manually_streamed: bytes = (
                uint32(request.start_height).stream_to_bytes()
                + uint32(request.end_height).stream_to_bytes()
                + uint32(len(blocks_bytes)).stream_to_bytes()
            )
            for block_bytes in blocks_bytes:
                respond_blocks_manually_streamed += block_bytes
            msg = make_msg(ProtocolMessageTypes.respond_blocks, respond_blocks_manually_streamed)

        return msg

    @metadata.request(peer_required=True)
    async def reject_block(
        self,
        request: full_node_protocol.RejectBlock,
        peer: WSChiaConnection,
    ) -> None:
        self.log.warning(f"unsolicited reject_block {request.height}")
        await peer.close(RATE_LIMITER_BAN_SECONDS)

    @metadata.request(peer_required=True)
    async def reject_blocks(
        self,
        request: full_node_protocol.RejectBlocks,
        peer: WSChiaConnection,
    ) -> None:
        self.log.warning(f"reject_blocks {request.start_height} {request.end_height}")
        await peer.close(RATE_LIMITER_BAN_SECONDS)

    @metadata.request(peer_required=True)
    async def respond_blocks(
        self,
        request: full_node_protocol.RespondBlocks,
        peer: WSChiaConnection,
    ) -> None:
        self.log.warning("Received unsolicited/late blocks")
        await peer.close(RATE_LIMITER_BAN_SECONDS)

    @metadata.request(peer_required=True)
    async def respond_block(
        self,
        respond_block: full_node_protocol.RespondBlock,
        peer: WSChiaConnection,
    ) -> Message | None:
        self.log.warning(f"Received unsolicited/late block from peer {peer.get_peer_logging()}")
        await peer.close(RATE_LIMITER_BAN_SECONDS)
        return None

    @metadata.request()
    async def new_unfinished_block(self, new_unfinished_block: full_node_protocol.NewUnfinishedBlock) -> Message | None:
        # Ignore if syncing
        if self.full_node.sync_store.get_sync_mode():
            return None
        block_hash = new_unfinished_block.unfinished_reward_hash
        if self.full_node.full_node_store.get_unfinished_block(block_hash) is not None:
            return None

        # This prevents us from downloading the same block from many peers
        requesting, count = self.full_node.full_node_store.is_requesting_unfinished_block(block_hash, None)
        if requesting:
            self.log.debug(
                f"Already have or requesting {count} Unfinished Blocks with partial "
                f"hash {block_hash}. Ignoring this one"
            )
            return None

        msg = make_msg(
            ProtocolMessageTypes.request_unfinished_block,
            full_node_protocol.RequestUnfinishedBlock(block_hash),
        )
        self.full_node.full_node_store.mark_requesting_unfinished_block(block_hash, None)

        # However, we want to eventually download from other peers, if this peer does not respond
        # Todo: keep track of who it was
        async def eventually_clear() -> None:
            await asyncio.sleep(5)
            self.full_node.full_node_store.remove_requesting_unfinished_block(block_hash, None)

        create_referenced_task(eventually_clear(), known_unreferenced=True)

        return msg

    @metadata.request(reply_types=[ProtocolMessageTypes.respond_unfinished_block])
    async def request_unfinished_block(
        self, request_unfinished_block: full_node_protocol.RequestUnfinishedBlock
    ) -> Message | None:
        unfinished_block: UnfinishedBlock | None = self.full_node.full_node_store.get_unfinished_block(
            request_unfinished_block.unfinished_reward_hash
        )
        if unfinished_block is not None:
            msg = make_msg(
                ProtocolMessageTypes.respond_unfinished_block,
                full_node_protocol.RespondUnfinishedBlock(unfinished_block),
            )
            return msg
        return None

    @metadata.request()
    async def new_unfinished_block2(
        self, new_unfinished_block: full_node_protocol.NewUnfinishedBlock2
    ) -> Message | None:
        # Ignore if syncing
        if self.full_node.sync_store.get_sync_mode():
            return None
        block_hash = new_unfinished_block.unfinished_reward_hash
        foliage_hash = new_unfinished_block.foliage_hash
        entry, count, have_better = self.full_node.full_node_store.get_unfinished_block2(block_hash, foliage_hash)

        if entry is not None:
            return None

        if have_better:
            self.log.info(
                f"Already have a better Unfinished Block with partial hash {block_hash.hex()} ignoring this one"
            )
            return None

        max_duplicate_unfinished_blocks = self.full_node.config.get("max_duplicate_unfinished_blocks", 3)
        if count > max_duplicate_unfinished_blocks:
            self.log.info(
                f"Already have {count} Unfinished Blocks with partial hash {block_hash.hex()} ignoring another one"
            )
            return None

        # This prevents us from downloading the same block from many peers
        requesting, count = self.full_node.full_node_store.is_requesting_unfinished_block(block_hash, foliage_hash)
        if requesting:
            return None
        if count >= max_duplicate_unfinished_blocks:
            self.log.info(
                f"Already requesting {count} Unfinished Blocks with partial hash {block_hash} ignoring another one"
            )
            return None

        msg = make_msg(
            ProtocolMessageTypes.request_unfinished_block2,
            full_node_protocol.RequestUnfinishedBlock2(block_hash, foliage_hash),
        )
        self.full_node.full_node_store.mark_requesting_unfinished_block(block_hash, foliage_hash)

        # However, we want to eventually download from other peers, if this peer does not respond
        # Todo: keep track of who it was
        async def eventually_clear() -> None:
            await asyncio.sleep(5)
            self.full_node.full_node_store.remove_requesting_unfinished_block(block_hash, foliage_hash)

        create_referenced_task(eventually_clear(), known_unreferenced=True)

        return msg

    @metadata.request(reply_types=[ProtocolMessageTypes.respond_unfinished_block])
    async def request_unfinished_block2(
        self, request_unfinished_block: full_node_protocol.RequestUnfinishedBlock2
    ) -> Message | None:
        unfinished_block: UnfinishedBlock | None
        unfinished_block, _, _ = self.full_node.full_node_store.get_unfinished_block2(
            request_unfinished_block.unfinished_reward_hash,
            request_unfinished_block.foliage_hash,
        )
        if unfinished_block is not None:
            msg = make_msg(
                ProtocolMessageTypes.respond_unfinished_block,
                full_node_protocol.RespondUnfinishedBlock(unfinished_block),
            )
            return msg
        return None

    @metadata.request(peer_required=True)
    async def respond_unfinished_block(
        self,
        respond_unfinished_block: full_node_protocol.RespondUnfinishedBlock,
        peer: WSChiaConnection,
    ) -> Message | None:
        if self.full_node.sync_store.get_sync_mode():
            return None
        await self.full_node.add_unfinished_block(respond_unfinished_block.unfinished_block, peer)
        return None

    @metadata.request(peer_required=True)
    async def new_signage_point_or_end_of_sub_slot(
        self, new_sp: full_node_protocol.NewSignagePointOrEndOfSubSlot, peer: WSChiaConnection
    ) -> Message | None:
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

    @metadata.request(
        reply_types=[ProtocolMessageTypes.respond_signage_point, ProtocolMessageTypes.respond_end_of_sub_slot]
    )
    async def request_signage_point_or_end_of_sub_slot(
        self, request: full_node_protocol.RequestSignagePointOrEndOfSubSlot
    ) -> Message | None:
        if request.index_from_challenge == 0:
            sub_slot: tuple[EndOfSubSlotBundle, int, uint128] | None = self.full_node.full_node_store.get_sub_slot(
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
                    self.log.info(f"Don't have challenge hash {request.challenge_hash.hex()}")

            sp: SignagePoint | None = self.full_node.full_node_store.get_signage_point_by_index(
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

    @metadata.request(peer_required=True)
    async def respond_signage_point(
        self, request: full_node_protocol.RespondSignagePoint, peer: WSChiaConnection
    ) -> Message | None:
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
            existing_sp = self.full_node.full_node_store.get_signage_point_by_index_and_cc_output(
                request.challenge_chain_vdf.output.get_hash(),
                request.challenge_chain_vdf.challenge,
                request.index_from_challenge,
            )
            if existing_sp is not None and existing_sp.rc_vdf == request.reward_chain_vdf:
                return None
            peak = self.full_node.blockchain.get_peak()
            if peak is not None and peak.height > self.full_node.constants.MAX_SUB_SLOT_BLOCKS:
                next_sub_slot_iters = self.full_node.blockchain.get_next_sub_slot_iters_and_difficulty(
                    peak.header_hash, True
                )[0]
                sub_slots_for_peak = await self.full_node.blockchain.get_sp_and_ip_sub_slots(peak.header_hash)
                assert sub_slots_for_peak is not None
                ip_sub_slot: EndOfSubSlotBundle | None = sub_slots_for_peak[1]
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
                    f"{request.challenge_chain_vdf.challenge.hex()}, "
                    f"RC challenge: {request.reward_chain_vdf.challenge.hex()}"
                )

            return None

    @metadata.request(peer_required=True)
    async def respond_end_of_sub_slot(
        self, request: full_node_protocol.RespondEndOfSubSlot, peer: WSChiaConnection
    ) -> Message | None:
        if self.full_node.sync_store.get_sync_mode():
            return None
        msg, _ = await self.full_node.add_end_of_sub_slot(request.end_of_slot_bundle, peer)
        return msg

    @metadata.request(peer_required=True)
    async def request_mempool_transactions(
        self,
        request: full_node_protocol.RequestMempoolTransactions,
        peer: WSChiaConnection,
    ) -> Message | None:
        received_filter = PyBIP158(bytearray(request.filter))

        items = self.full_node.mempool_manager.get_items_not_in_filter(received_filter, limit=100)

        for item in items:
            transaction = full_node_protocol.NewTransaction(item.name, item.cost, item.fee)
            msg = make_msg(ProtocolMessageTypes.new_transaction, transaction)
            await peer.send_message(msg)
        return None

    # FARMER PROTOCOL
    @metadata.request(peer_required=True)
    async def declare_proof_of_space(
        self, request: farmer_protocol.DeclareProofOfSpace, peer: WSChiaConnection
    ) -> Message | None:
        """
        Creates a block body and header, with the proof of space, coinbase, and fee targets provided
        by the farmer, and sends the hash of the header data back to the farmer.
        """
        if self.full_node.sync_store.get_sync_mode():
            return None

        async with self.full_node.timelord_lock:
            sp_vdfs: SignagePoint | None = self.full_node.full_node_store.get_signage_point_by_index_and_cc_output(
                request.challenge_chain_sp, request.challenge_hash, request.signage_point_index
            )

            if sp_vdfs is None:
                self.log.warning(f"Received proof of space for an unknown signage point {request.challenge_chain_sp}")
                return None
            if request.signage_point_index > 0:
                assert sp_vdfs.rc_vdf is not None
                if sp_vdfs.rc_vdf.output.get_hash() != request.reward_chain_sp:
                    self.log.debug(
                        f"Received proof of space for a potentially old signage point {request.challenge_chain_sp}. "
                        f"Current sp: {sp_vdfs.rc_vdf.output.get_hash().hex()}"
                    )
                    return None

            if request.signage_point_index == 0:
                cc_challenge_hash: bytes32 = request.challenge_chain_sp
            else:
                assert sp_vdfs.cc_vdf is not None
                cc_challenge_hash = sp_vdfs.cc_vdf.challenge

            pos_sub_slot: tuple[EndOfSubSlotBundle, int, uint128] | None = None
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
            new_block_gen: NewBlockGenerator | None
            async with self.full_node.blockchain.priority_mutex.acquire(priority=BlockchainMutexPriority.high):
                peak: BlockRecord | None = self.full_node.blockchain.get_peak()
                tx_peak: BlockRecord | None = self.full_node.blockchain.get_tx_peak()

                # Checks that the proof of space is valid
                height: uint32
                tx_height: uint32
                if peak is None or tx_peak is None:
                    height = uint32(0)
                    tx_height = uint32(0)
                else:
                    height = peak.height
                    tx_height = tx_peak.height
                quality_string: bytes32 | None = verify_and_get_quality_string(
                    request.proof_of_space,
                    self.full_node.constants,
                    cc_challenge_hash,
                    request.challenge_chain_sp,
                    height=height,
                    prev_transaction_block_height=tx_height,
                )
                if quality_string is None:
                    self.log.warning("Received invalid proof of space in DeclareProofOfSpace from farmer")
                    return None

                if peak is not None:
                    # Finds the last transaction block before this one
                    curr_l_tb: BlockRecord = peak
                    while not curr_l_tb.is_transaction_block:
                        curr_l_tb = self.full_node.blockchain.block_record(curr_l_tb.prev_hash)
                    try:
                        # TODO: once we're confident in the new block creation,
                        # make it default to 1
                        block_version = self.full_node.config.get("block_creation", 0)
                        block_timeout = self.full_node.config.get("block_creation_timeout", 2.0)
                        if block_version == 0:
                            create_block = self.full_node.mempool_manager.create_block_generator
                        elif block_version == 1:
                            create_block = self.full_node.mempool_manager.create_block_generator2
                        else:
                            self.log.warning(f"Unknown 'block_creation' config: {block_version}")
                            create_block = self.full_node.mempool_manager.create_block_generator

                        new_block_gen = create_block(curr_l_tb.header_hash, block_timeout)

                        if (
                            new_block_gen is not None and peak.height < self.full_node.constants.HARD_FORK_HEIGHT
                        ):  # pragma: no cover
                            self.log.error("Cannot farm blocks pre-hard fork")

                    except Exception as e:
                        self.log.error(f"Traceback: {traceback.format_exc()}")
                        self.full_node.log.error(f"Error making spend bundle {e} peak: {peak}")
                        new_block_gen = None
                else:
                    new_block_gen = None

            def get_plot_sig(to_sign: bytes32, _extra: G1Element) -> G2Element:
                if to_sign == request.challenge_chain_sp:
                    return request.challenge_chain_sp_signature
                elif to_sign == request.reward_chain_sp:
                    return request.reward_chain_sp_signature
                return G2Element()

            def get_pool_sig(_1: PoolTarget, _2: G1Element | None) -> G2Element | None:
                return request.pool_signature

            prev_b: BlockRecord | None = peak

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
                finished_sub_slots: list[EndOfSubSlotBundle] | None = (
                    self.full_node.full_node_store.get_finished_sub_slots(
                        self.full_node.blockchain, prev_b, cc_challenge_hash
                    )
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

            tx_peak = self.full_node.blockchain.get_tx_peak()
            required_iters: uint64 = calculate_iterations_quality(
                self.full_node.constants,
                quality_string,
                request.proof_of_space.param(),
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
            timestamp = uint64(time.time())
            curr: BlockRecord | None = prev_b
            while curr is not None and not curr.is_transaction_block and curr.height != 0:
                curr = self.full_node.blockchain.try_block_record(curr.prev_hash)
            if curr is not None:
                assert curr.timestamp is not None
                if timestamp <= curr.timestamp:
                    timestamp = uint64(curr.timestamp + 1)

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
                new_block_gen,
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
                foliage_transaction_block_hash = bytes32.zeros
            assert foliage_transaction_block_hash is not None

            foliage_block_data: FoliageBlockData | None = None
            foliage_transaction_block_data: FoliageTransactionBlock | None = None
            rc_block_unfinished: RewardChainBlockUnfinished | None = None
            if request.include_signature_source_data:
                foliage_block_data = unfinished_block.foliage.foliage_block_data
                rc_block_unfinished = unfinished_block.reward_chain_block
                if unfinished_block.is_transaction_block():
                    foliage_transaction_block_data = unfinished_block.foliage_transaction_block

            message = farmer_protocol.RequestSignedValues(
                quality_string,
                foliage_sb_data_hash,
                foliage_transaction_block_hash,
                foliage_block_data=foliage_block_data,
                foliage_transaction_block_data=foliage_transaction_block_data,
                rc_block_unfinished=rc_block_unfinished,
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
                    prev_b,
                    finished_sub_slots,
                )

                self.full_node.full_node_store.add_candidate_block(
                    quality_string, height, unfinished_block_backup, backup=True
                )
        return None

    @metadata.request(peer_required=True)
    async def signed_values(
        self, farmer_request: farmer_protocol.SignedValues, peer: WSChiaConnection
    ) -> Message | None:
        """
        Signature of header hash, by the harvester. This is enough to create an unfinished
        block, which only needs a Proof of Time to be finished. If the signature is valid,
        we call the unfinished_block routine.
        """
        candidate_tuple: tuple[uint32, UnfinishedBlock] | None = self.full_node.full_node_store.get_candidate_block(
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

        fsb2 = candidate.foliage.replace(foliage_block_data_signature=farmer_request.foliage_block_data_signature)
        if candidate.is_transaction_block():
            fsb2 = fsb2.replace(foliage_transaction_block_signature=farmer_request.foliage_transaction_block_signature)

        new_candidate = candidate.replace(foliage=fsb2)
        if not self.full_node.has_valid_pool_sig(new_candidate):
            self.log.warning("Trying to make a pre-farm block but height is not 0")
            return None

        # Propagate to ourselves (which validates and does further propagations)
        try:
            await self.full_node.add_unfinished_block(new_candidate, None, True)
        except Exception as e:
            if isinstance(e, ValidationError) and e.code == Err.NO_OVERFLOWS_IN_FIRST_SUB_SLOT_NEW_EPOCH:
                self.full_node.log.info(
                    f"Failed to farm block {e}. Consensus rules prevent this block from being farmed. Not retrying"
                )
                return None

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
    @metadata.request(peer_required=True)
    async def new_infusion_point_vdf(
        self, request: timelord_protocol.NewInfusionPointVDF, peer: WSChiaConnection
    ) -> Message | None:
        if self.full_node.sync_store.get_sync_mode():
            return None
        # Lookup unfinished blocks
        async with self.full_node.timelord_lock:
            return await self.full_node.new_infusion_point_vdf(request, peer)

    @metadata.request(peer_required=True)
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

    @metadata.request(peer_required=True)
    async def new_end_of_sub_slot_vdf(
        self, request: timelord_protocol.NewEndOfSubSlotVDF, peer: WSChiaConnection
    ) -> Message | None:
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
                f"{request.end_of_sub_slot_bundle.challenge_chain.challenge_chain_end_of_slot_vdf.challenge.hex()}. "
                f"Re-sending new-peak to timelord"
            )
            await self.full_node.send_peak_to_timelords(peer=peer)
            return None
        else:
            return msg

    @metadata.request(bytes_required=True, execute_task=True)
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

    @metadata.request(peer_required=True, bytes_required=True, execute_task=True)
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

    @metadata.request(peer_required=True, reply_types=[ProtocolMessageTypes.respond_compact_vdf])
    async def request_compact_vdf(self, request: full_node_protocol.RequestCompactVDF, peer: WSChiaConnection) -> None:
        if self.full_node.sync_store.get_sync_mode():
            return None
        await self.full_node.request_compact_vdf(request, peer)
        return None

    @metadata.request(peer_required=True)
    async def respond_compact_vdf(self, request: full_node_protocol.RespondCompactVDF, peer: WSChiaConnection) -> None:
        if self.full_node.sync_store.get_sync_mode():
            return None
        await self.full_node.add_compact_vdf(request, peer)
        return None
