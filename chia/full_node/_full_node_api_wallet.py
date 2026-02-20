from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Collection
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import TYPE_CHECKING, ClassVar, cast

import anyio
from chia_rs import (
    CoinRecord,
    CoinState,
    FullBlock,
    MerkleSet,
    RespondToPhUpdates,
    SubEpochSummary,
    additions_and_removals,
    get_flags_for_height_and_constants,
)
from chia_rs import get_puzzle_and_solution_for_coin2 as get_puzzle_and_solution_for_coin
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint8, uint32, uint64

from chia.consensus.generator_tools import get_block_header
from chia.consensus.get_block_generator import get_block_generator
from chia.full_node.coin_store import CoinStore
from chia.full_node.fee_estimator_interface import FeeEstimatorInterface
from chia.full_node.full_block_utils import get_height_and_tx_status_from_block, header_block_from_block
from chia.full_node.hard_fork_utils import get_flags
from chia.full_node.tx_processing_queue import TransactionQueueEntry, TransactionQueueFull
from chia.protocols import wallet_protocol
from chia.protocols.fee_estimate import FeeEstimate, FeeEstimateGroup, fee_rate_v2_to_v1
from chia.protocols.outbound_message import Message, make_msg
from chia.protocols.protocol_message_types import ProtocolMessageTypes
from chia.protocols.shared_protocol import Capability
from chia.protocols.wallet_protocol import (
    PuzzleSolutionResponse,
    RejectBlockHeaders,
    RejectHeaderBlocks,
    RejectHeaderRequest,
    RespondFeeEstimates,
    RespondSESInfo,
)
from chia.server.api_protocol import ApiMetadata
from chia.server.server import ChiaServer
from chia.server.ws_connection import WSChiaConnection
from chia.types.block_protocol import BlockInfo
from chia.types.blockchain_format.coin import Coin, hash_coin_ids
from chia.types.generator_types import BlockGenerator
from chia.types.mempool_inclusion_status import MempoolInclusionStatus
from chia.util.batches import to_batches
from chia.util.db_wrapper import SQLITE_MAX_VARIABLE_NUMBER

if TYPE_CHECKING:
    from chia.full_node.full_node import FullNode

# Shared ApiMetadata instance used by both _FullNodeApiWalletMixin and FullNodeAPI.
# This must be a single instance so that @metadata.request() decorators in both
# the mixin and FullNodeAPI register handlers into the same registry.
full_node_metadata = ApiMetadata()


class _FullNodeApiWalletMixin:
    """Wallet protocol handlers for FullNodeAPI.

    This mixin is combined with FullNodeAPI via inheritance and is not meant to
    be instantiated directly. At runtime the concrete class (FullNodeAPI) provides
    ``full_node``, ``log``, ``executor``, and ``server`` attributes.
    """

    full_node: FullNode
    log: logging.Logger
    executor: ThreadPoolExecutor
    metadata: ClassVar[ApiMetadata] = full_node_metadata

    @property
    def server(self) -> ChiaServer:
        raise NotImplementedError

    # WALLET PROTOCOL
    @metadata.request()
    async def request_block_header(self, request: wallet_protocol.RequestBlockHeader) -> Message | None:
        header_hash = self.full_node.blockchain.height_to_hash(request.height)
        if header_hash is None:
            msg = make_msg(ProtocolMessageTypes.reject_header_request, RejectHeaderRequest(request.height))
            return msg
        block: FullBlock | None = await self.full_node.block_store.get_full_block(header_hash)
        if block is None:
            return None

        removals_and_additions: tuple[Collection[bytes32], Collection[Coin]] | None = None

        if block.transactions_generator is not None:
            block_generator: BlockGenerator | None = await get_block_generator(
                self.full_node.blockchain.lookup_block_generators, block
            )
            # get_block_generator() returns None in case the block we specify
            # does not have a generator (i.e. is not a transaction block).
            # in this case we've already made sure `block` does have a
            # transactions_generator, so the block_generator should always be set
            assert block_generator is not None, "failed to get block_generator for tx-block"
            flags = await get_flags(constants=self.full_node.constants, blocks=self.full_node.blockchain, block=block)
            additions, removals = await asyncio.get_running_loop().run_in_executor(
                self.executor,
                additions_and_removals,
                bytes(block.transactions_generator),
                block_generator.generator_refs,
                flags,
                self.full_node.constants,
            )
            # strip the hint from additions, and compute the puzzle hash for
            # removals
            removals_and_additions = ([name for name, _ in removals], [name for name, _ in additions])
        elif block.is_transaction_block():
            # This is a transaction block with just reward coins.
            removals_and_additions = ([], [])

        header_block = get_block_header(block, removals_and_additions)
        msg = make_msg(
            ProtocolMessageTypes.respond_block_header,
            wallet_protocol.RespondBlockHeader(header_block),
        )
        return msg

    @metadata.request()
    async def request_additions(self, request: wallet_protocol.RequestAdditions) -> Message | None:
        if request.header_hash is None:
            header_hash: bytes32 | None = self.full_node.blockchain.height_to_hash(request.height)
        else:
            header_hash = request.header_hash
        if header_hash is None:
            raise ValueError(f"Block at height {request.height} not found")

        # Note: this might return bad data if there is a reorg in this time
        additions = await self.full_node.coin_store.get_coins_added_at_height(request.height)

        if self.full_node.blockchain.height_to_hash(request.height) != header_hash:
            raise ValueError(f"Block {header_hash} no longer in chain, or invalid header_hash")

        puzzlehash_coins_map: dict[bytes32, list[Coin]] = {}
        for coin_record in additions:
            if coin_record.coin.puzzle_hash in puzzlehash_coins_map:
                puzzlehash_coins_map[coin_record.coin.puzzle_hash].append(coin_record.coin)
            else:
                puzzlehash_coins_map[coin_record.coin.puzzle_hash] = [coin_record.coin]

        coins_map: list[tuple[bytes32, list[Coin]]] = []
        proofs_map: list[tuple[bytes32, bytes, bytes | None]] = []

        if request.puzzle_hashes is None:
            for puzzle_hash, coins in puzzlehash_coins_map.items():
                coins_map.append((puzzle_hash, coins))
            response = wallet_protocol.RespondAdditions(request.height, header_hash, coins_map, None)
        else:
            # Create addition Merkle set
            # Addition Merkle set contains puzzlehash and hash of all coins with that puzzlehash
            leafs: list[bytes32] = []
            for puzzle, coins in puzzlehash_coins_map.items():
                leafs.append(puzzle)
                leafs.append(hash_coin_ids([c.name() for c in coins]))

            addition_merkle_set = MerkleSet(leafs)

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

    @metadata.request()
    async def request_removals(self, request: wallet_protocol.RequestRemovals) -> Message | None:
        block: FullBlock | None = await self.full_node.block_store.get_full_block(request.header_hash)

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
        all_removals: list[CoinRecord] = await self.full_node.coin_store.get_coins_removed_at_height(block.height)

        if self.full_node.blockchain.height_to_hash(block.height) != request.header_hash:
            raise ValueError(f"Block {block.header_hash} no longer in chain")

        all_removals_dict: dict[bytes32, Coin] = {}
        for coin_record in all_removals:
            all_removals_dict[coin_record.coin.name()] = coin_record.coin

        coins_map: list[tuple[bytes32, Coin | None]] = []
        proofs_map: list[tuple[bytes32, bytes]] = []

        # If there are no transactions, respond with empty lists
        if block.transactions_generator is None:
            proofs: list[tuple[bytes32, bytes]] | None
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
            leafs: list[bytes32] = []
            for removed_name, removed_coin in all_removals_dict.items():
                leafs.append(removed_name)
            removal_merkle_set = MerkleSet(leafs)
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

    @metadata.request(peer_required=True)
    async def send_transaction(
        self, request: wallet_protocol.SendTransaction, peer: WSChiaConnection, *, test: bool = False
    ) -> Message | None:
        spend_name = request.transaction.name()
        if self.full_node.mempool_manager.get_spendbundle(spend_name) is not None:
            self.full_node.mempool_manager.remove_seen(spend_name)
            response = wallet_protocol.TransactionAck(spend_name, uint8(MempoolInclusionStatus.SUCCESS), None)
            return make_msg(ProtocolMessageTypes.transaction_ack, response)
        high_priority = self.is_trusted(peer)
        queue_entry = TransactionQueueEntry(request.transaction, None, spend_name, None, test)
        try:
            self.full_node.transaction_queue.put(queue_entry, peer_id=peer.peer_node_id, high_priority=high_priority)
        except TransactionQueueFull:
            return make_msg(
                ProtocolMessageTypes.transaction_ack,
                wallet_protocol.TransactionAck(
                    spend_name, uint8(MempoolInclusionStatus.FAILED), "Transaction queue full"
                ),
            )
        try:
            with anyio.fail_after(delay=45):
                status, error = await queue_entry.done.wait()
        except TimeoutError:
            response = wallet_protocol.TransactionAck(spend_name, uint8(MempoolInclusionStatus.PENDING), None)
        else:
            error_name = error.name if error is not None else None
            if status == MempoolInclusionStatus.SUCCESS:
                response = wallet_protocol.TransactionAck(spend_name, uint8(status.value), error_name)
            # If it failed/pending, but it previously succeeded (in mempool), this is idempotence, return SUCCESS
            elif self.full_node.mempool_manager.get_spendbundle(spend_name) is not None:
                response = wallet_protocol.TransactionAck(spend_name, uint8(MempoolInclusionStatus.SUCCESS.value), None)
            else:
                response = wallet_protocol.TransactionAck(spend_name, uint8(status.value), error_name)
        return make_msg(ProtocolMessageTypes.transaction_ack, response)

    @metadata.request()
    async def request_puzzle_solution(self, request: wallet_protocol.RequestPuzzleSolution) -> Message | None:
        coin_name = request.coin_name
        height = request.height
        coin_record = await self.full_node.coin_store.get_coin_record(coin_name)
        reject = wallet_protocol.RejectPuzzleSolution(coin_name, height)
        reject_msg = make_msg(ProtocolMessageTypes.reject_puzzle_solution, reject)
        if coin_record is None or coin_record.spent_block_index != height:
            return reject_msg

        header_hash: bytes32 | None = self.full_node.blockchain.height_to_hash(height)
        if header_hash is None:
            return reject_msg

        block: BlockInfo | None = await self.full_node.block_store.get_block_info(header_hash)

        if block is None or block.transactions_generator is None:
            return reject_msg

        block_generator: BlockGenerator | None = await get_block_generator(
            self.full_node.blockchain.lookup_block_generators, block
        )
        assert block_generator is not None
        try:
            puzzle, solution = await asyncio.get_running_loop().run_in_executor(
                self.executor,
                get_puzzle_and_solution_for_coin,
                block_generator.program,
                block_generator.generator_refs,
                self.full_node.constants.MAX_BLOCK_COST_CLVM,
                coin_record.coin,
                get_flags_for_height_and_constants(height, self.full_node.constants),
            )
        except ValueError:
            return reject_msg
        wrapper = PuzzleSolutionResponse(coin_name, height, puzzle, solution)
        response = wallet_protocol.RespondPuzzleSolution(wrapper)
        response_msg = make_msg(ProtocolMessageTypes.respond_puzzle_solution, response)
        return response_msg

    @metadata.request()
    async def request_block_headers(self, request: wallet_protocol.RequestBlockHeaders) -> Message | None:
        """Returns header blocks by directly streaming bytes into Message

        This method should be used instead of RequestHeaderBlocks
        """
        reject = RejectBlockHeaders(request.start_height, request.end_height)

        if request.end_height < request.start_height or request.end_height - request.start_height > 128:
            return make_msg(ProtocolMessageTypes.reject_block_headers, reject)
        try:
            blocks_bytes = await self.full_node.block_store.get_block_bytes_in_range(
                request.start_height, request.end_height
            )
        except ValueError:
            return make_msg(ProtocolMessageTypes.reject_block_headers, reject)

        if len(blocks_bytes) != (request.end_height - request.start_height + 1):  # +1 because interval is inclusive
            return make_msg(ProtocolMessageTypes.reject_block_headers, reject)
        return_filter = request.return_filter
        header_blocks_bytes: list[bytes] = []
        for b in blocks_bytes:
            b_mem_view = memoryview(b)
            height, is_tx_block = get_height_and_tx_status_from_block(b_mem_view)
            if not is_tx_block:
                tx_addition_coins = []
                removal_names = []
            else:
                added_coins_records_coroutine = self.full_node.coin_store.get_coins_added_at_height(height)
                removed_coins_records_coroutine = self.full_node.coin_store.get_coins_removed_at_height(height)
                added_coins_records, removed_coins_records = await asyncio.gather(
                    added_coins_records_coroutine, removed_coins_records_coroutine
                )
                tx_addition_coins = [record.coin for record in added_coins_records if not record.coinbase]
                removal_names = [record.coin.name() for record in removed_coins_records]
            header_blocks_bytes.append(
                header_block_from_block(b_mem_view, return_filter, tx_addition_coins, removal_names)
            )

        # we're building the RespondHeaderBlocks manually to avoid cost of
        # dynamic serialization
        # ---
        # we start building RespondBlockHeaders response (start_height, end_height)
        # and then need to define size of list object
        respond_header_blocks_manually_streamed: bytes = (
            uint32(request.start_height).stream_to_bytes()
            + uint32(request.end_height).stream_to_bytes()
            + uint32(len(header_blocks_bytes)).stream_to_bytes()
        )
        # and now stream the whole list in bytes
        respond_header_blocks_manually_streamed += b"".join(header_blocks_bytes)
        return make_msg(ProtocolMessageTypes.respond_block_headers, respond_header_blocks_manually_streamed)

    @metadata.request()
    async def request_header_blocks(self, request: wallet_protocol.RequestHeaderBlocks) -> Message | None:
        """DEPRECATED: please use RequestBlockHeaders"""
        if (
            request.end_height < request.start_height
            or request.end_height - request.start_height > self.full_node.constants.MAX_BLOCK_COUNT_PER_REQUESTS
        ):
            return None
        height_to_hash = self.full_node.blockchain.height_to_hash
        header_hashes: list[bytes32] = []
        for i in range(request.start_height, request.end_height + 1):
            header_hash: bytes32 | None = height_to_hash(uint32(i))
            if header_hash is None:
                reject = RejectHeaderBlocks(request.start_height, request.end_height)
                msg = make_msg(ProtocolMessageTypes.reject_header_blocks, reject)
                return msg
            header_hashes.append(header_hash)

        blocks: list[FullBlock] = await self.full_node.block_store.get_blocks_by_hash(header_hashes)
        header_blocks = []
        for block in blocks:
            if not block.is_transaction_block():
                header_blocks.append(get_block_header(block))
                continue
            added_coins_records_coroutine = self.full_node.coin_store.get_coins_added_at_height(block.height)
            removed_coins_records_coroutine = self.full_node.coin_store.get_coins_removed_at_height(block.height)
            added_coins_records, removed_coins_records = await asyncio.gather(
                added_coins_records_coroutine, removed_coins_records_coroutine
            )
            added_coins = [record.coin for record in added_coins_records if not record.coinbase]
            removal_names = [record.coin.name() for record in removed_coins_records]
            header_block = get_block_header(block, (removal_names, added_coins))
            header_blocks.append(header_block)

        msg = make_msg(
            ProtocolMessageTypes.respond_header_blocks,
            wallet_protocol.RespondHeaderBlocks(request.start_height, request.end_height, header_blocks),
        )
        return msg

    @metadata.request(peer_required=True)
    async def register_for_ph_updates(
        self, request: wallet_protocol.RegisterForPhUpdates, peer: WSChiaConnection
    ) -> Message:
        trusted = self.is_trusted(peer)
        max_items = self.max_subscribe_response_items(peer)
        max_subscriptions = self.max_subscriptions(peer)

        # the returned puzzle hashes are the ones we ended up subscribing to.
        # It will have filtered duplicates and ones exceeding the subscription
        # limit.
        puzzle_hashes = self.full_node.subscriptions.add_puzzle_subscriptions(
            peer.peer_node_id, request.puzzle_hashes, max_subscriptions
        )

        start_time = time.monotonic()

        # Note that coin state updates may arrive out-of-order on the client side.
        # We add the subscription before we're done collecting all the coin
        # state that goes into the response. CoinState updates may be sent
        # before we send the response

        # Send all coins with requested puzzle hash that have been created after the specified height
        states: set[CoinState] = await self.full_node.coin_store.get_coin_states_by_puzzle_hashes(
            include_spent_coins=True, puzzle_hashes=puzzle_hashes, min_height=request.min_height, max_items=max_items
        )
        max_items -= len(states)

        hint_coin_ids = await self.full_node.hint_store.get_coin_ids_multi(
            cast(set[bytes], puzzle_hashes), max_items=max_items
        )

        hint_states: list[CoinState] = []
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

        response = RespondToPhUpdates(request.puzzle_hashes, request.min_height, list(states))
        msg = make_msg(ProtocolMessageTypes.respond_to_ph_updates, response)
        return msg

    @metadata.request(peer_required=True)
    async def register_for_coin_updates(
        self, request: wallet_protocol.RegisterForCoinUpdates, peer: WSChiaConnection
    ) -> Message:
        max_items = self.max_subscribe_response_items(peer)
        max_subscriptions = self.max_subscriptions(peer)

        # TODO: apparently we have tests that expect to receive a
        # RespondToCoinUpdates even when subscribing to the same coin multiple
        # times, so we can't optimize away such DB lookups (yet)
        self.full_node.subscriptions.add_coin_subscriptions(peer.peer_node_id, request.coin_ids, max_subscriptions)

        states: list[CoinState] = await self.full_node.coin_store.get_coin_states_by_ids(
            include_spent_coins=True, coin_ids=set(request.coin_ids), min_height=request.min_height, max_items=max_items
        )

        response = wallet_protocol.RespondToCoinUpdates(request.coin_ids, request.min_height, states)
        msg = make_msg(ProtocolMessageTypes.respond_to_coin_updates, response)
        return msg

    @metadata.request()
    async def request_children(self, request: wallet_protocol.RequestChildren) -> Message | None:
        coin_records: list[CoinRecord] = await self.full_node.coin_store.get_coin_records_by_parent_ids(
            True, [request.coin_name]
        )
        states = [record.coin_state for record in coin_records]
        response = wallet_protocol.RespondChildren(states)
        msg = make_msg(ProtocolMessageTypes.respond_children, response)
        return msg

    @metadata.request()
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

    @metadata.request(reply_types=[ProtocolMessageTypes.respond_fee_estimates])
    async def request_fee_estimates(self, request: wallet_protocol.RequestFeeEstimates) -> Message:
        def get_fee_estimates(est: FeeEstimatorInterface, req_times: list[uint64]) -> list[FeeEstimate]:
            now = datetime.now(timezone.utc)
            utc_time = now.replace(tzinfo=timezone.utc)
            utc_now = int(utc_time.timestamp())
            deltas = [max(0, req_ts - utc_now) for req_ts in req_times]
            fee_rates = [est.estimate_fee_rate(time_offset_seconds=d) for d in deltas]
            v1_fee_rates = [fee_rate_v2_to_v1(est) for est in fee_rates]
            return [FeeEstimate(None, req_ts, fee_rate) for req_ts, fee_rate in zip(req_times, v1_fee_rates)]

        fee_estimates: list[FeeEstimate] = get_fee_estimates(
            self.full_node.mempool_manager.mempool.fee_estimator, request.time_targets
        )
        response = RespondFeeEstimates(FeeEstimateGroup(error=None, estimates=fee_estimates))
        msg = make_msg(ProtocolMessageTypes.respond_fee_estimates, response)
        return msg

    @metadata.request(
        peer_required=True,
        reply_types=[ProtocolMessageTypes.respond_remove_puzzle_subscriptions],
    )
    async def request_remove_puzzle_subscriptions(
        self, request: wallet_protocol.RequestRemovePuzzleSubscriptions, peer: WSChiaConnection
    ) -> Message:
        peer_id = peer.peer_node_id
        subs = self.full_node.subscriptions

        if request.puzzle_hashes is None:
            removed = list(subs.puzzle_subscriptions(peer_id))
            subs.clear_puzzle_subscriptions(peer_id)
        else:
            removed = list(subs.remove_puzzle_subscriptions(peer_id, request.puzzle_hashes))

        response = wallet_protocol.RespondRemovePuzzleSubscriptions(removed)
        msg = make_msg(ProtocolMessageTypes.respond_remove_puzzle_subscriptions, response)
        return msg

    @metadata.request(
        peer_required=True,
        reply_types=[ProtocolMessageTypes.respond_remove_coin_subscriptions],
    )
    async def request_remove_coin_subscriptions(
        self, request: wallet_protocol.RequestRemoveCoinSubscriptions, peer: WSChiaConnection
    ) -> Message:
        peer_id = peer.peer_node_id
        subs = self.full_node.subscriptions

        if request.coin_ids is None:
            removed = list(subs.coin_subscriptions(peer_id))
            subs.clear_coin_subscriptions(peer_id)
        else:
            removed = list(subs.remove_coin_subscriptions(peer_id, request.coin_ids))

        response = wallet_protocol.RespondRemoveCoinSubscriptions(removed)
        msg = make_msg(ProtocolMessageTypes.respond_remove_coin_subscriptions, response)
        return msg

    @metadata.request(peer_required=True, reply_types=[ProtocolMessageTypes.respond_puzzle_state])
    async def request_puzzle_state(
        self, request: wallet_protocol.RequestPuzzleState, peer: WSChiaConnection
    ) -> Message:
        max_items = self.max_subscribe_response_items(peer)
        max_subscriptions = self.max_subscriptions(peer)
        subs = self.full_node.subscriptions

        request_puzzle_hashes = list(dict.fromkeys(request.puzzle_hashes))

        # This is a limit imposed by `batch_coin_states_by_puzzle_hashes`, due to the SQLite variable limit.
        # It can be increased in the future, and this protocol should be written and tested in a way that
        # this increase would not break the API.
        count = CoinStore.MAX_PUZZLE_HASH_BATCH_SIZE
        puzzle_hashes = request_puzzle_hashes[:count]

        previous_header_hash = (
            self.full_node.blockchain.height_to_hash(request.previous_height)
            if request.previous_height is not None
            else self.full_node.blockchain.constants.GENESIS_CHALLENGE
        )

        if request.header_hash != previous_header_hash:
            rejection = wallet_protocol.RejectPuzzleState(uint8(wallet_protocol.RejectStateReason.REORG))
            msg = make_msg(ProtocolMessageTypes.reject_puzzle_state, rejection)
            return msg

        # Check if the request would exceed the subscription limit now.
        def check_subscription_limit() -> Message | None:
            new_subscription_count = len(puzzle_hashes) + subs.peer_subscription_count(peer.peer_node_id)

            if request.subscribe_when_finished and new_subscription_count > max_subscriptions:
                rejection = wallet_protocol.RejectPuzzleState(
                    uint8(wallet_protocol.RejectStateReason.EXCEEDED_SUBSCRIPTION_LIMIT)
                )
                msg = make_msg(ProtocolMessageTypes.reject_puzzle_state, rejection)
                return msg

            return None

        sub_rejection = check_subscription_limit()
        if sub_rejection is not None:
            return sub_rejection

        min_height = uint32((request.previous_height + 1) if request.previous_height is not None else 0)

        (coin_states, next_min_height) = await self.full_node.coin_store.batch_coin_states_by_puzzle_hashes(
            puzzle_hashes,
            min_height=min_height,
            include_spent=request.filters.include_spent,
            include_unspent=request.filters.include_unspent,
            include_hinted=request.filters.include_hinted,
            min_amount=request.filters.min_amount,
            max_items=max_items,
        )
        is_done = next_min_height is None

        peak_height = self.full_node.blockchain.get_peak_height()
        assert peak_height is not None

        height = uint32(next_min_height - 1) if next_min_height is not None else peak_height
        header_hash = self.full_node.blockchain.height_to_hash(height)
        assert header_hash is not None

        # Check if the request would exceed the subscription limit.
        # We do this again since we've crossed an `await` point, to prevent a race condition.
        sub_rejection = check_subscription_limit()
        if sub_rejection is not None:
            return sub_rejection

        if is_done and request.subscribe_when_finished:
            subs.add_puzzle_subscriptions(peer.peer_node_id, puzzle_hashes, max_subscriptions)
            await self.mempool_updates_for_puzzle_hashes(peer, set(puzzle_hashes), request.filters.include_hinted)

        response = wallet_protocol.RespondPuzzleState(puzzle_hashes, height, header_hash, is_done, coin_states)
        msg = make_msg(ProtocolMessageTypes.respond_puzzle_state, response)
        return msg

    @metadata.request(peer_required=True, reply_types=[ProtocolMessageTypes.respond_coin_state])
    async def request_coin_state(self, request: wallet_protocol.RequestCoinState, peer: WSChiaConnection) -> Message:
        max_items = self.max_subscribe_response_items(peer)
        max_subscriptions = self.max_subscriptions(peer)
        subs = self.full_node.subscriptions

        request_coin_ids = list(dict.fromkeys(request.coin_ids))
        coin_ids = request_coin_ids[:max_items]

        previous_header_hash = (
            self.full_node.blockchain.height_to_hash(request.previous_height)
            if request.previous_height is not None
            else self.full_node.blockchain.constants.GENESIS_CHALLENGE
        )

        if request.header_hash != previous_header_hash:
            rejection = wallet_protocol.RejectCoinState(uint8(wallet_protocol.RejectStateReason.REORG))
            msg = make_msg(ProtocolMessageTypes.reject_coin_state, rejection)
            return msg

        # Check if the request would exceed the subscription limit now.
        def check_subscription_limit() -> Message | None:
            new_subscription_count = len(coin_ids) + subs.peer_subscription_count(peer.peer_node_id)

            if request.subscribe and new_subscription_count > max_subscriptions:
                rejection = wallet_protocol.RejectCoinState(
                    uint8(wallet_protocol.RejectStateReason.EXCEEDED_SUBSCRIPTION_LIMIT)
                )
                msg = make_msg(ProtocolMessageTypes.reject_coin_state, rejection)
                return msg

            return None

        sub_rejection = check_subscription_limit()
        if sub_rejection is not None:
            return sub_rejection

        min_height = uint32(request.previous_height + 1 if request.previous_height is not None else 0)

        coin_states = await self.full_node.coin_store.get_coin_states_by_ids(
            True, coin_ids, min_height=min_height, max_items=max_items
        )

        # Check if the request would exceed the subscription limit.
        # We do this again since we've crossed an `await` point, to prevent a race condition.
        sub_rejection = check_subscription_limit()
        if sub_rejection is not None:
            return sub_rejection

        if request.subscribe:
            subs.add_coin_subscriptions(peer.peer_node_id, coin_ids, max_subscriptions)
            await self.mempool_updates_for_coin_ids(peer, set(coin_ids))

        response = wallet_protocol.RespondCoinState(coin_ids, coin_states)
        msg = make_msg(ProtocolMessageTypes.respond_coin_state, response)
        return msg

    @metadata.request(reply_types=[ProtocolMessageTypes.respond_cost_info])
    async def request_cost_info(self, _request: wallet_protocol.RequestCostInfo) -> Message | None:
        mempool_manager = self.full_node.mempool_manager
        response = wallet_protocol.RespondCostInfo(
            max_transaction_cost=mempool_manager.max_tx_clvm_cost,
            max_block_cost=mempool_manager.max_block_clvm_cost,
            max_mempool_cost=uint64(mempool_manager.mempool_max_total_cost),
            mempool_cost=uint64(mempool_manager.mempool._total_cost),
            mempool_fee=uint64(mempool_manager.mempool._total_fee),
            bump_fee_per_cost=uint8(mempool_manager.nonzero_fee_minimum_fpc),
        )
        msg = make_msg(ProtocolMessageTypes.respond_cost_info, response)
        return msg

    async def mempool_updates_for_puzzle_hashes(
        self, peer: WSChiaConnection, puzzle_hashes: set[bytes32], include_hints: bool
    ) -> None:
        if Capability.MEMPOOL_UPDATES not in peer.peer_capabilities:
            return

        start_time = time.monotonic()

        async with self.full_node.db_wrapper.reader() as conn:
            transaction_ids = set(
                self.full_node.mempool_manager.mempool.items_with_puzzle_hashes(puzzle_hashes, include_hints)
            )

            hinted_coin_ids: set[bytes32] = set()

            for batch in to_batches(puzzle_hashes, SQLITE_MAX_VARIABLE_NUMBER):
                hints_db: tuple[bytes, ...] = tuple(batch.entries)
                cursor = await conn.execute(
                    f"SELECT coin_id from hints INDEXED BY hint_index "
                    f"WHERE hint IN ({'?,' * (len(batch.entries) - 1)}?)",
                    hints_db,
                )
                for row in await cursor.fetchall():
                    hinted_coin_ids.add(bytes32(row[0]))
                await cursor.close()

            transaction_ids |= set(self.full_node.mempool_manager.mempool.items_with_coin_ids(hinted_coin_ids))

        if len(transaction_ids) > 0:
            message = wallet_protocol.MempoolItemsAdded(list(transaction_ids))
            await peer.send_message(make_msg(ProtocolMessageTypes.mempool_items_added, message))

        total_time = time.monotonic() - start_time

        self.log.log(
            logging.DEBUG if total_time < 2.0 else logging.WARNING,
            f"Sending initial mempool items to peer {peer.peer_node_id} took {total_time:.4f}s",
        )

    async def mempool_updates_for_coin_ids(self, peer: WSChiaConnection, coin_ids: set[bytes32]) -> None:
        if Capability.MEMPOOL_UPDATES not in peer.peer_capabilities:
            return

        start_time = time.monotonic()

        transaction_ids = self.full_node.mempool_manager.mempool.items_with_coin_ids(coin_ids)

        if len(transaction_ids) > 0:
            message = wallet_protocol.MempoolItemsAdded(list(transaction_ids))
            await peer.send_message(make_msg(ProtocolMessageTypes.mempool_items_added, message))

        total_time = time.monotonic() - start_time

        self.log.log(
            logging.DEBUG if total_time < 2.0 else logging.WARNING,
            f"Sending initial mempool items to peer {peer.peer_node_id} took {total_time:.4f}s",
        )

    def max_subscriptions(self, peer: WSChiaConnection) -> int:
        if self.is_trusted(peer):
            return cast(int, self.full_node.config.get("trusted_max_subscribe_items", 2000000))
        else:
            return cast(int, self.full_node.config.get("max_subscribe_items", 200000))

    def max_subscribe_response_items(self, peer: WSChiaConnection) -> int:
        if self.is_trusted(peer):
            return cast(int, self.full_node.config.get("trusted_max_subscribe_response_items", 500000))
        else:
            return cast(int, self.full_node.config.get("max_subscribe_response_items", 100000))

    def is_trusted(self, peer: WSChiaConnection) -> bool:
        return self.server.is_trusted_peer(peer, self.full_node.config.get("trusted_peers", {}))
