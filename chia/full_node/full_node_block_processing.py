from __future__ import annotations

import asyncio
import copy
import dataclasses
import logging
import time
from collections.abc import Awaitable, Sequence
from typing import TYPE_CHECKING, Any

from chia_rs import (
    AugSchemeMPL,
    BlockRecord,
    CoinRecord,
    EndOfSubSlotBundle,
    FullBlock,
    PoolTarget,
    SubEpochSummary,
    UnfinishedBlock,
    get_flags_for_height_and_constants,
    run_block_generator,
    run_block_generator2,
)
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint8, uint32, uint64, uint128
from packaging.version import Version

from chia.consensus.augmented_chain import AugmentedBlockchain
from chia.consensus.block_body_validation import ForkInfo
from chia.consensus.block_creation import unfinished_block_to_full_block
from chia.consensus.blockchain import AddBlockResult, BlockchainMutexPriority, StateChangeSummary
from chia.consensus.condition_tools import pkm_pairs
from chia.consensus.cost_calculator import NPCResult
from chia.consensus.difficulty_adjustment import get_next_sub_slot_iters_and_difficulty
from chia.consensus.make_sub_epoch_summary import next_sub_epoch_summary
from chia.consensus.multiprocess_validation import PreValidationResult, pre_validate_block
from chia.consensus.pot_iterations import calculate_sp_iters
from chia.consensus.signage_point import SignagePoint
from chia.full_node.full_node_api import FullNodeAPI
from chia.full_node.full_node_store import FullNodeStorePeakResult
from chia.full_node.hint_management import get_hints_and_subscription_coin_ids
from chia.full_node.mempool import MempoolRemoveInfo
from chia.full_node.sync_store import Peak
from chia.protocols import farmer_protocol, full_node_protocol, timelord_protocol
from chia.protocols.farmer_protocol import SignagePointSourceData, SPSubSlotSourceData, SPVDFSourceData
from chia.protocols.full_node_protocol import RespondSignagePoint
from chia.protocols.outbound_message import Message, NodeType, make_msg
from chia.protocols.protocol_message_types import ProtocolMessageTypes
from chia.types.validation_state import ValidationState
from chia.util.bech32m import encode_puzzle_hash
from chia.util.errors import ConsensusError, Err, TimestampError
from chia.util.path import path_from_root
from chia.util.profiler import enable_profiler
from chia.util.task_referencer import create_referenced_task

if TYPE_CHECKING:
    from chia_rs import BLSCache

    from chia.full_node.full_node import FullNode
    from chia.server.ws_connection import WSChiaConnection
    from chia.types.peer_info import PeerInfo


# This is the result of calling peak_post_processing, which is then fed into peak_post_processing_2
@dataclasses.dataclass
class PeakPostProcessingResult:
    # The added transactions IDs from calling MempoolManager.new_peak
    mempool_peak_added_tx_ids: list[bytes32]
    mempool_removals: list[MempoolRemoveInfo]  # The removed mempool items from calling MempoolManager.new_peak
    fns_peak_result: FullNodeStorePeakResult  # The result of calling FullNodeStore.new_peak
    hints: list[tuple[bytes32, bytes]]  # The hints added to the DB
    lookup_coin_ids: list[bytes32]  # The coin IDs that we need to look up to notify wallets of changes
    signage_points: list[tuple[RespondSignagePoint, WSChiaConnection, EndOfSubSlotBundle | None]]


@dataclasses.dataclass(frozen=True)
class WalletUpdate:
    fork_height: uint32
    peak: Peak
    coin_records: list[CoinRecord]
    hints: dict[bytes32, bytes32]


async def add_block_batch(
    self: FullNode,
    all_blocks: list[FullBlock],
    peer_info: PeerInfo,
    fork_info: ForkInfo,
    vs: ValidationState,  # in-out parameter
    blockchain: AugmentedBlockchain,
    wp_summaries: list[SubEpochSummary] | None = None,
) -> tuple[bool, StateChangeSummary | None]:
    # Precondition: All blocks must be contiguous blocks, index i+1 must be the parent of index i
    # Returns a bool for success, as well as a StateChangeSummary if the peak was advanced

    pre_validate_start = time.monotonic()
    blocks_to_validate = await self.skip_blocks(blockchain, all_blocks, fork_info, vs)

    if len(blocks_to_validate) == 0:
        return True, None

    futures = await self.prevalidate_blocks(
        blockchain,
        blocks_to_validate,
        copy.copy(vs),
        wp_summaries,
    )
    pre_validation_results = list(await asyncio.gather(*futures))

    agg_state_change_summary, err = await self.add_prevalidated_blocks(
        blockchain,
        blocks_to_validate,
        pre_validation_results,
        fork_info,
        peer_info,
        vs,
    )

    if agg_state_change_summary is not None:
        self._state_changed("new_peak")
        self.log.debug(
            f"Total time for {len(blocks_to_validate)} blocks: {time.monotonic() - pre_validate_start}, "
            f"advanced: True"
        )
    return err is None, agg_state_change_summary


async def skip_blocks(
    self: FullNode,
    blockchain: AugmentedBlockchain,
    all_blocks: list[FullBlock],
    fork_info: ForkInfo,
    vs: ValidationState,  # in-out parameter
) -> list[FullBlock]:
    blocks_to_validate: list[FullBlock] = []
    for i, block in enumerate(all_blocks):
        header_hash = block.header_hash
        block_rec = await blockchain.get_block_record_from_db(header_hash)
        if block_rec is None:
            blocks_to_validate = all_blocks[i:]
            break
        else:
            blockchain.add_block_record(block_rec)
            if block_rec.sub_epoch_summary_included:
                # already validated block, update sub slot iters, difficulty and prev sub epoch summary
                vs.prev_ses_block = block_rec
                if block_rec.sub_epoch_summary_included.new_sub_slot_iters is not None:
                    vs.ssi = block_rec.sub_epoch_summary_included.new_sub_slot_iters
                if block_rec.sub_epoch_summary_included.new_difficulty is not None:
                    vs.difficulty = block_rec.sub_epoch_summary_included.new_difficulty

        # the below section updates the fork_info object, if
        # there is one.
        if block.height <= fork_info.peak_height:
            continue
        # we have already validated this block once, no need to do it again.
        # however, if this block is not part of the main chain, we need to
        # update the fork context with its additions and removals
        if self.blockchain.height_to_hash(block.height) == header_hash:
            # we're on the main chain, just fast-forward the fork height
            fork_info.reset(block.height, header_hash)
        else:
            # We have already validated the block, but if it's not part of the
            # main chain, we still need to re-run it to update the additions and
            # removals in fork_info.
            await self.blockchain.advance_fork_info(block, fork_info)
            await self.blockchain.run_single_block(block, fork_info)
    return blocks_to_validate


async def prevalidate_blocks(
    self: FullNode,
    blockchain: AugmentedBlockchain,
    blocks_to_validate: list[FullBlock],
    vs: ValidationState,
    wp_summaries: list[SubEpochSummary] | None = None,
) -> Sequence[Awaitable[PreValidationResult]]:
    """
    This is a thin wrapper over pre_validate_block().

    Args:
        blockchain:
        blocks_to_validate:
        vs: The ValidationState for the first block in the batch. This is an in-out
            parameter. It will be updated to be the validation state for the next
            batch of blocks.
        wp_summaries:
    """
    # Validates signatures in multiprocessing since they take a while, and we don't have cached transactions
    # for these blocks (unlike during normal operation where we validate one at a time)
    # We have to copy the ValidationState object to preserve it for the add_block()
    # call below. pre_validate_block() will update the
    # object we pass in.
    ret: list[Awaitable[PreValidationResult]] = []
    for block in blocks_to_validate:
        ret.append(
            await pre_validate_block(
                self.constants,
                blockchain,
                block,
                self.blockchain.pool,
                None,
                vs,
                wp_summaries=wp_summaries,
            )
        )
    return ret


async def add_prevalidated_blocks(
    self: FullNode,
    blockchain: AugmentedBlockchain,
    blocks_to_validate: list[FullBlock],
    pre_validation_results: list[PreValidationResult],
    fork_info: ForkInfo,
    peer_info: PeerInfo,
    vs: ValidationState,  # in-out parameter
) -> tuple[StateChangeSummary | None, Err | None]:
    agg_state_change_summary: StateChangeSummary | None = None
    block_record = await self.blockchain.get_block_record_from_db(blocks_to_validate[0].prev_header_hash)
    for i, block in enumerate(blocks_to_validate):
        header_hash = block.header_hash
        assert vs.prev_ses_block is None or vs.prev_ses_block.height < block.height
        assert pre_validation_results[i].error is None
        assert pre_validation_results[i].required_iters is not None
        state_change_summary: StateChangeSummary | None
        # when adding blocks in batches, we won't have any overlapping
        # signatures with the mempool. There won't be any cache hits, so
        # there's no need to pass the BLS cache in

        if len(block.finished_sub_slots) > 0:
            cc_sub_slot = block.finished_sub_slots[0].challenge_chain
            if cc_sub_slot.new_sub_slot_iters is not None or cc_sub_slot.new_difficulty is not None:
                expected_sub_slot_iters, expected_difficulty = get_next_sub_slot_iters_and_difficulty(
                    self.constants, True, block_record, blockchain
                )
                assert cc_sub_slot.new_sub_slot_iters is not None
                vs.ssi = cc_sub_slot.new_sub_slot_iters
                assert cc_sub_slot.new_difficulty is not None
                vs.difficulty = cc_sub_slot.new_difficulty
                assert expected_sub_slot_iters == vs.ssi
                assert expected_difficulty == vs.difficulty
        block_rec = blockchain.block_record(block.header_hash)
        result, error, state_change_summary = await self.blockchain.add_block(
            block,
            pre_validation_results[i],
            vs.ssi,
            fork_info,
            prev_ses_block=vs.prev_ses_block,
            block_record=block_rec,
        )
        if error is None:
            blockchain.remove_extra_block(header_hash)

        if result == AddBlockResult.NEW_PEAK:
            # since this block just added a new peak, we've don't need any
            # fork history from fork_info anymore
            fork_info.reset(block.height, header_hash)
            assert state_change_summary is not None
            # Since all blocks are contiguous, we can simply append the rollback changes and npc results
            if agg_state_change_summary is None:
                agg_state_change_summary = state_change_summary
            else:
                # Keeps the old, original fork_height, since the next blocks will have fork height h-1
                # Groups up all state changes into one
                agg_state_change_summary = StateChangeSummary(
                    state_change_summary.peak,
                    agg_state_change_summary.fork_height,
                    agg_state_change_summary.rolled_back_records + state_change_summary.rolled_back_records,
                    agg_state_change_summary.removals + state_change_summary.removals,
                    agg_state_change_summary.additions + state_change_summary.additions,
                    agg_state_change_summary.new_rewards + state_change_summary.new_rewards,
                )
        elif result in {AddBlockResult.INVALID_BLOCK, AddBlockResult.DISCONNECTED_BLOCK}:
            if error is not None:
                self.log.error(f"Error: {error}, Invalid block from peer: {peer_info} ")
            return agg_state_change_summary, error
        block_record = blockchain.block_record(header_hash)
        assert block_record is not None
        if block_record.sub_epoch_summary_included is not None:
            vs.prev_ses_block = block_record
            if self.weight_proof_handler is not None:
                await self.weight_proof_handler.create_prev_sub_epoch_segments()
    if agg_state_change_summary is not None:
        self._state_changed("new_peak")
    return agg_state_change_summary, None


async def get_sub_slot_iters_difficulty_ses_block(
    self: FullNode, block: FullBlock, ssi: uint64 | None, diff: uint64 | None
) -> tuple[uint64, uint64, BlockRecord | None]:
    prev_ses_block = None
    if ssi is None or diff is None:
        if block.height == 0:
            ssi = self.constants.SUB_SLOT_ITERS_STARTING
            diff = self.constants.DIFFICULTY_STARTING
    if ssi is None or diff is None:
        if len(block.finished_sub_slots) > 0:
            if block.finished_sub_slots[0].challenge_chain.new_difficulty is not None:
                diff = block.finished_sub_slots[0].challenge_chain.new_difficulty
            if block.finished_sub_slots[0].challenge_chain.new_sub_slot_iters is not None:
                ssi = block.finished_sub_slots[0].challenge_chain.new_sub_slot_iters

    if block.height > 0:
        prev_b = await self.blockchain.get_block_record_from_db(block.prev_header_hash)
        curr = prev_b
        while prev_ses_block is None or ssi is None or diff is None:
            assert curr is not None
            if curr.height == 0:
                if ssi is None or diff is None:
                    ssi = self.constants.SUB_SLOT_ITERS_STARTING
                    diff = self.constants.DIFFICULTY_STARTING
                if prev_ses_block is None:
                    prev_ses_block = curr
            if curr.sub_epoch_summary_included is not None:
                if prev_ses_block is None:
                    prev_ses_block = curr
                if ssi is None or diff is None:
                    if curr.sub_epoch_summary_included.new_difficulty is not None:
                        diff = curr.sub_epoch_summary_included.new_difficulty
                    if curr.sub_epoch_summary_included.new_sub_slot_iters is not None:
                        ssi = curr.sub_epoch_summary_included.new_sub_slot_iters
            curr = await self.blockchain.get_block_record_from_db(curr.prev_hash)
    assert ssi is not None
    assert diff is not None
    return ssi, diff, prev_ses_block


def has_valid_pool_sig(self: FullNode, block: UnfinishedBlock | FullBlock) -> bool:
    if (
        block.foliage.foliage_block_data.pool_target
        == PoolTarget(self.constants.GENESIS_PRE_FARM_POOL_PUZZLE_HASH, uint32(0))
        and block.foliage.prev_block_hash != self.constants.GENESIS_CHALLENGE
        and block.reward_chain_block.proof_of_space.pool_public_key is not None
    ):
        assert block.foliage.foliage_block_data.pool_signature is not None
        if not AugSchemeMPL.verify(
            block.reward_chain_block.proof_of_space.pool_public_key,
            bytes(block.foliage.foliage_block_data.pool_target),
            block.foliage.foliage_block_data.pool_signature,
        ):
            return False
    return True


async def signage_point_post_processing(
    self: FullNode,
    request: full_node_protocol.RespondSignagePoint,
    peer: WSChiaConnection,
    ip_sub_slot: EndOfSubSlotBundle | None,
) -> None:
    self.log.info(
        f"⏲️  Finished signage point {request.index_from_challenge}/"
        f"{self.constants.NUM_SPS_SUB_SLOT}: "
        f"CC: {request.challenge_chain_vdf.output.get_hash().hex()} "
        f"RC: {request.reward_chain_vdf.output.get_hash().hex()} "
    )
    self.signage_point_times[request.index_from_challenge] = time.time()
    sub_slot_tuple = self.full_node_store.get_sub_slot(request.challenge_chain_vdf.challenge)
    prev_challenge: bytes32 | None
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
    msg = make_msg(ProtocolMessageTypes.new_signage_point_or_end_of_sub_slot, broadcast)
    await self.server.send_to_all([msg], NodeType.FULL_NODE, peer.peer_node_id)

    peak = self.blockchain.get_peak()
    if peak is not None and peak.height > self.constants.MAX_SUB_SLOT_BLOCKS:
        sub_slot_iters = peak.sub_slot_iters
        difficulty = uint64(peak.weight - self.blockchain.block_record(peak.prev_hash).weight)
        # Makes sure to potentially update the difficulty if we are past the peak (into a new sub-slot)
        assert ip_sub_slot is not None
        if request.challenge_chain_vdf.challenge != ip_sub_slot.challenge_chain.get_hash():
            sub_slot_iters, difficulty = self.blockchain.get_next_sub_slot_iters_and_difficulty(
                peak.header_hash, True
            )
    else:
        difficulty = self.constants.DIFFICULTY_STARTING
        sub_slot_iters = self.constants.SUB_SLOT_ITERS_STARTING

    tx_peak = self.blockchain.get_tx_peak()
    # Notify farmers of the new signage point
    broadcast_farmer = farmer_protocol.NewSignagePoint(
        request.challenge_chain_vdf.challenge,
        request.challenge_chain_vdf.output.get_hash(),
        request.reward_chain_vdf.output.get_hash(),
        difficulty,
        sub_slot_iters,
        request.index_from_challenge,
        uint32(0) if peak is None else peak.height,
        tx_peak.height if tx_peak is not None else uint32(0),
        sp_source_data=SignagePointSourceData(
            vdf_data=SPVDFSourceData(request.challenge_chain_vdf.output, request.reward_chain_vdf.output)
        ),
    )
    msg = make_msg(ProtocolMessageTypes.new_signage_point, broadcast_farmer)
    await self.server.send_to_all([msg], NodeType.FARMER)

    self._state_changed("signage_point", {"broadcast_farmer": broadcast_farmer})


async def peak_post_processing(
    self: FullNode,
    block: FullBlock,
    state_change_summary: StateChangeSummary,
    peer: WSChiaConnection | None,
) -> PeakPostProcessingResult:
    """
    Must be called under self.blockchain.priority_mutex. This updates the internal state of the full node with the
    latest peak information. It also notifies peers about the new peak.
    """

    record = state_change_summary.peak
    sub_slot_iters, difficulty = self.blockchain.get_next_sub_slot_iters_and_difficulty(record.header_hash, False)

    self.log.info(
        f"🌱 Updated peak to height {record.height}, weight {record.weight}, "
        f"hh {record.header_hash.hex()}, "
        f"ph {record.prev_hash.hex()}, "
        f"forked at {state_change_summary.fork_height}, rh: {record.reward_infusion_new_challenge.hex()}, "
        f"total iters: {record.total_iters}, "
        f"overflow: {record.overflow}, "
        f"deficit: {record.deficit}, "
        f"difficulty: {difficulty}, "
        f"sub slot iters: {sub_slot_iters}, "
        f"Generator size: "
        f"{len(bytes(block.transactions_generator)) if block.transactions_generator else 'No tx'}, "
        f"Generator ref list size: "
        f"{len(block.transactions_generator_ref_list) if block.transactions_generator else 'No tx'}"
    )

    hints_to_add, lookup_coin_ids = get_hints_and_subscription_coin_ids(
        state_change_summary,
        self.subscriptions.has_coin_subscription,
        self.subscriptions.has_puzzle_subscription,
    )
    await self.hint_store.add_hints(hints_to_add)

    sub_slots = await self.blockchain.get_sp_and_ip_sub_slots(record.header_hash)
    assert sub_slots is not None

    if not self.sync_store.get_sync_mode():
        self.blockchain.clean_block_records()

    fork_block: BlockRecord | None = None
    if state_change_summary.fork_height != block.height - 1 and block.height != 0:
        # This is a reorg
        fork_hash: bytes32 | None = self.blockchain.height_to_hash(state_change_summary.fork_height)
        assert fork_hash is not None
        fork_block = await self.blockchain.get_block_record_from_db(fork_hash)

    fns_peak_result: FullNodeStorePeakResult = self.full_node_store.new_peak(
        record,
        block,
        sub_slots[0],
        sub_slots[1],
        fork_block,
        self.blockchain,
        sub_slot_iters,
        difficulty,
    )

    signage_points: list[tuple[RespondSignagePoint, WSChiaConnection, EndOfSubSlotBundle | None]] = []
    if fns_peak_result.new_signage_points is not None and peer is not None:
        for index, sp in fns_peak_result.new_signage_points:
            assert (
                sp.cc_vdf is not None
                and sp.cc_proof is not None
                and sp.rc_vdf is not None
                and sp.rc_proof is not None
            )
            # Collect the data for networking outside the mutex
            signage_points.append(
                (
                    RespondSignagePoint(index, sp.cc_vdf, sp.cc_proof, sp.rc_vdf, sp.rc_proof),
                    peer,
                    sub_slots[1],
                )
            )

    if sub_slots[1] is None:
        assert record.ip_sub_slot_total_iters(self.constants) == 0
    # Ensure the signage point is also in the store, for consistency
    self.full_node_store.new_signage_point(
        record.signage_point_index,
        self.blockchain,
        record,
        record.sub_slot_iters,
        SignagePoint(
            block.reward_chain_block.challenge_chain_sp_vdf,
            block.challenge_chain_sp_proof,
            block.reward_chain_block.reward_chain_sp_vdf,
            block.reward_chain_sp_proof,
        ),
        skip_vdf_validation=True,
    )

    # Update the mempool (returns successful pending transactions added to the mempool)
    spent_coins: list[bytes32] = [coin_id for coin_id, _ in state_change_summary.removals]
    mempool_new_peak_result = await self.mempool_manager.new_peak(self.blockchain.get_tx_peak(), spent_coins)

    return PeakPostProcessingResult(
        mempool_new_peak_result.spend_bundle_ids,
        mempool_new_peak_result.removals,
        fns_peak_result,
        hints_to_add,
        lookup_coin_ids,
        signage_points=signage_points,
    )


async def peak_post_processing_2(
    self: FullNode,
    block: FullBlock,
    peer: WSChiaConnection | None,
    state_change_summary: StateChangeSummary,
    ppp_result: PeakPostProcessingResult,
) -> None:
    """
    Does NOT need to be called under the blockchain lock. Handle other parts of post processing like communicating
    with peers
    """
    record = state_change_summary.peak
    for signage_point in ppp_result.signage_points:
        await self.signage_point_post_processing(*signage_point)
    for transaction_id in ppp_result.mempool_peak_added_tx_ids:
        self.log.debug(f"Added transaction to mempool: {transaction_id}")
        mempool_item = self.mempool_manager.get_mempool_item(transaction_id)
        assert mempool_item is not None
        await self.broadcast_added_tx(mempool_item)

    # If there were pending end of slots that happen after this peak, broadcast them if they are added
    if ppp_result.fns_peak_result.added_eos is not None:
        broadcast = full_node_protocol.NewSignagePointOrEndOfSubSlot(
            ppp_result.fns_peak_result.added_eos.challenge_chain.challenge_chain_end_of_slot_vdf.challenge,
            ppp_result.fns_peak_result.added_eos.challenge_chain.get_hash(),
            uint8(0),
            ppp_result.fns_peak_result.added_eos.reward_chain.end_of_slot_vdf.challenge,
        )
        msg = make_msg(ProtocolMessageTypes.new_signage_point_or_end_of_sub_slot, broadcast)
        await self.server.send_to_all([msg], NodeType.FULL_NODE)

    # TODO: maybe add and broadcast new IPs as well

    if record.height % 1000 == 0:
        # Occasionally clear data in full node store to keep memory usage small
        self.full_node_store.clear_old_cache_entries()

    if self.sync_store.get_sync_mode() is False:
        await self.send_peak_to_timelords(block)
        await self.broadcast_removed_tx(ppp_result.mempool_removals)

        # Tell full nodes about the new peak
        msg = make_msg(
            ProtocolMessageTypes.new_peak,
            full_node_protocol.NewPeak(
                record.header_hash,
                record.height,
                record.weight,
                state_change_summary.fork_height,
                block.reward_chain_block.get_unfinished().get_hash(),
            ),
        )
        if peer is not None:
            await self.server.send_to_all([msg], NodeType.FULL_NODE, peer.peer_node_id)
        else:
            await self.server.send_to_all([msg], NodeType.FULL_NODE)

    coin_hints: dict[bytes32, bytes32] = {
        coin_id: bytes32(hint) for coin_id, hint in ppp_result.hints if len(hint) == 32
    }

    peak = Peak(
        state_change_summary.peak.header_hash, state_change_summary.peak.height, state_change_summary.peak.weight
    )

    # Looks up coin records in DB for the coins that wallets are interested in
    new_states = await self.coin_store.get_coin_records(ppp_result.lookup_coin_ids)

    await self.wallet_sync_queue.put(
        WalletUpdate(
            state_change_summary.fork_height,
            peak,
            state_change_summary.rolled_back_records + new_states,
            coin_hints,
        )
    )

    self._state_changed("new_peak")


async def add_block(
    self: FullNode,
    block: FullBlock,
    peer: WSChiaConnection | None = None,
    bls_cache: BLSCache | None = None,
    raise_on_disconnected: bool = False,
    fork_info: ForkInfo | None = None,
) -> Message | None:
    """
    Add a full block from a peer full node (or ourselves).
    """
    if self.sync_store.get_sync_mode():
        return None

    # Adds the block to seen, and check if it's seen before (which means header is in memory)
    header_hash = block.header_hash
    if self.blockchain.contains_block(header_hash, block.height):
        if fork_info is not None:
            await self.blockchain.run_single_block(block, fork_info)
        return None

    pre_validation_result: PreValidationResult | None = None
    if (
        block.is_transaction_block()
        and block.transactions_info is not None
        and block.transactions_info.generator_root != bytes([0] * 32)
        and block.transactions_generator is None
    ):
        # This is the case where we already had the unfinished block, and asked for this block without
        # the transactions (since we already had them). Therefore, here we add the transactions.
        unfinished_rh: bytes32 = block.reward_chain_block.get_unfinished().get_hash()
        foliage_hash: bytes32 | None = block.foliage.foliage_transaction_block_hash
        assert foliage_hash is not None
        unf_entry = self.full_node_store.get_unfinished_block_result(unfinished_rh, foliage_hash)
        assert unf_entry is None or unf_entry.result is None or unf_entry.result.validated_signature is True
        if (
            unf_entry is not None
            and unf_entry.unfinished_block is not None
            and unf_entry.unfinished_block.transactions_generator is not None
            and unf_entry.unfinished_block.foliage_transaction_block == block.foliage_transaction_block
        ):
            # We checked that the transaction block is the same, therefore all transactions and the signature
            # must be identical in the unfinished and finished blocks. We can therefore use the cache.

            # this is a transaction block, the foliage hash should be set
            assert foliage_hash is not None
            pre_validation_result = unf_entry.result
            assert pre_validation_result is not None
            block = block.replace(
                transactions_generator=unf_entry.unfinished_block.transactions_generator,
                transactions_generator_ref_list=unf_entry.unfinished_block.transactions_generator_ref_list,
            )
        else:
            # We still do not have the correct information for this block, perhaps there is a duplicate block
            # with the same unfinished block hash in the cache, so we need to fetch the correct one
            if peer is None:
                return None

            block_response: Any | None = await peer.call_api(
                FullNodeAPI.request_block, full_node_protocol.RequestBlock(block.height, True)
            )
            if block_response is None or not isinstance(block_response, full_node_protocol.RespondBlock):
                self.log.warning(
                    f"Was not able to fetch the correct block for height {block.height} {block_response}"
                )
                return None
            new_block: FullBlock = block_response.block
            if new_block.foliage_transaction_block != block.foliage_transaction_block:
                self.log.warning(
                    f"Received the wrong block for height {block.height} {new_block.header_hash.hex()}"
                )
                return None
            assert new_block.transactions_generator is not None

            self.log.debug(
                f"Wrong info in the cache for bh {new_block.header_hash.hex()}, "
                f"there might be multiple blocks from the "
                f"same farmer with the same pospace."
            )
            # This recursion ends here, we cannot recurse again because transactions_generator is not None
            return await self.add_block(new_block, peer, bls_cache)
    state_change_summary: StateChangeSummary | None = None
    ppp_result: PeakPostProcessingResult | None = None
    async with (
        self.blockchain.priority_mutex.acquire(priority=BlockchainMutexPriority.high),
        enable_profiler(self.profile_block_validation) as pr,
    ):
        # After acquiring the lock, check again, because another asyncio thread might have added it
        if self.blockchain.contains_block(header_hash, block.height):
            if fork_info is not None:
                await self.blockchain.run_single_block(block, fork_info)
            return None
        validation_start = time.monotonic()
        # Tries to add the block to the blockchain, if we already validated transactions, don't do it again
        conds = None
        if pre_validation_result is not None and pre_validation_result.conds is not None:
            conds = pre_validation_result.conds

        # Don't validate signatures because we want to validate them in the main thread later, since we have a
        # cache available
        prev_b = None
        prev_ses_block = None
        if block.height > 0:
            prev_b = await self.blockchain.get_block_record_from_db(block.prev_header_hash)
            assert prev_b is not None
            curr = prev_b
            while curr.height > 0 and curr.sub_epoch_summary_included is None:
                curr = self.blockchain.block_record(curr.prev_hash)
            prev_ses_block = curr
        new_slot = len(block.finished_sub_slots) > 0
        ssi, diff = get_next_sub_slot_iters_and_difficulty(self.constants, new_slot, prev_b, self.blockchain)
        future = await pre_validate_block(
            self.blockchain.constants,
            AugmentedBlockchain(self.blockchain),
            block,
            self.blockchain.pool,
            conds,
            ValidationState(ssi, diff, prev_ses_block),
        )
        pre_validation_result = await future
        added: AddBlockResult | None = None
        add_block_start = time.monotonic()
        pre_validation_time = add_block_start - validation_start
        try:
            if pre_validation_result.error is not None:
                if Err(pre_validation_result.error) == Err.INVALID_PREV_BLOCK_HASH:
                    added = AddBlockResult.DISCONNECTED_BLOCK
                    error_code: Err | None = Err.INVALID_PREV_BLOCK_HASH
                elif Err(pre_validation_result.error) == Err.TIMESTAMP_TOO_FAR_IN_FUTURE:
                    raise TimestampError
                else:
                    raise ValueError(
                        f"Failed to validate block {header_hash} height "
                        f"{block.height}: {Err(pre_validation_result.error).name}"
                    )
            else:
                if fork_info is None:
                    fork_info = ForkInfo(block.height - 1, block.height - 1, block.prev_header_hash)
                (added, error_code, state_change_summary) = await self.blockchain.add_block(
                    block, pre_validation_result, ssi, fork_info
                )
            add_block_time = time.monotonic() - add_block_start
            if added == AddBlockResult.ALREADY_HAVE_BLOCK:
                return None
            elif added == AddBlockResult.INVALID_BLOCK:
                assert error_code is not None
                self.log.error(f"Block {header_hash} at height {block.height} is invalid with code {error_code}.")
                raise ConsensusError(error_code, [header_hash])
            elif added == AddBlockResult.DISCONNECTED_BLOCK:
                self.log.info(f"Disconnected block {header_hash} at height {block.height}")
                if raise_on_disconnected:
                    raise RuntimeError("Expected block to be added, received disconnected block.")
                return None
            elif added == AddBlockResult.NEW_PEAK:
                # Evict any related BLS cache entries as we no longer need them
                if bls_cache is not None and pre_validation_result.conds is not None:
                    pairs_pks, pairs_msgs = pkm_pairs(
                        pre_validation_result.conds, self.constants.AGG_SIG_ME_ADDITIONAL_DATA
                    )
                    bls_cache.evict(pairs_pks, pairs_msgs)
                # Only propagate blocks which extend the blockchain (becomes one of the heads)
                assert state_change_summary is not None
                post_process_time = time.monotonic()
                ppp_result = await self.peak_post_processing(block, state_change_summary, peer)
                post_process_time = time.monotonic() - post_process_time

            elif added == AddBlockResult.ADDED_AS_ORPHAN:
                self.log.info(
                    f"Received orphan block of height {block.height} rh {block.reward_chain_block.get_hash()}"
                )
                post_process_time = 0.0
            else:
                # Should never reach here, all the cases are covered
                raise RuntimeError(f"Invalid result from add_block {added}")
        except asyncio.CancelledError:
            # We need to make sure to always call this method even when we get a cancel exception, to make sure
            # the node stays in sync
            if added == AddBlockResult.NEW_PEAK:
                assert state_change_summary is not None
                await self.peak_post_processing(block, state_change_summary, peer)
            raise

        validation_time = time.monotonic() - validation_start

    if ppp_result is not None:
        assert state_change_summary is not None
        post_process_time2 = time.monotonic()
        await self.peak_post_processing_2(block, peer, state_change_summary, ppp_result)
        post_process_time2 = time.monotonic() - post_process_time2
    else:
        post_process_time2 = 0.0

    percent_full_str = (
        (
            ", percent full: "
            + str(round(100.0 * float(block.transactions_info.cost) / self.constants.MAX_BLOCK_COST_CLVM, 3))
            + "%"
        )
        if block.transactions_info is not None
        else ""
    )
    self.log.log(
        logging.WARNING if validation_time > 2 else logging.DEBUG,
        f"Block validation: {validation_time:0.2f}s, "
        f"pre_validation: {pre_validation_time:0.2f}s, "
        f"CLVM: {pre_validation_result.timing / 1000.0:0.2f}s, "
        f"add-block: {add_block_time:0.2f}s, "
        f"post-process: {post_process_time:0.2f}s, "
        f"post-process2: {post_process_time2:0.2f}s, "
        f"cost: {block.transactions_info.cost if block.transactions_info is not None else 'None'}"
        f"{percent_full_str} header_hash: {header_hash.hex()} height: {block.height}",
    )

    # this is not covered by any unit tests as it's essentially test code
    # itself. It's exercised manually when investigating performance issues
    if validation_time > 2 and pr is not None:  # pragma: no cover
        pr.create_stats()
        profile_dir = path_from_root(self.root_path, "block-validation-profile")
        pr.dump_stats(profile_dir / f"{block.height}-{validation_time:0.1f}.profile")

    # This code path is reached if added == ADDED_AS_ORPHAN or NEW_TIP
    peak = self.blockchain.get_peak()
    assert peak is not None

    # Removes all temporary data for old blocks
    clear_height = uint32(max(0, peak.height - 50))
    self.full_node_store.clear_candidate_blocks_below(clear_height)
    self.full_node_store.clear_unfinished_blocks_below(clear_height)

    state_changed_data: dict[str, Any] = {
        "transaction_block": False,
        "k_size": block.reward_chain_block.proof_of_space.param().size_v1,
        "strength": block.reward_chain_block.proof_of_space.param().strength_v2,
        "header_hash": block.header_hash,
        "fork_height": None,
        "rolled_back_records": None,
        "height": block.height,
        "validation_time": validation_time,
        "pre_validation_time": pre_validation_time,
    }

    if state_change_summary is not None:
        state_changed_data["fork_height"] = state_change_summary.fork_height
        state_changed_data["rolled_back_records"] = len(state_change_summary.rolled_back_records)

    if block.transactions_info is not None:
        state_changed_data["transaction_block"] = True
        state_changed_data["block_cost"] = block.transactions_info.cost
        state_changed_data["block_fees"] = block.transactions_info.fees

    if block.foliage_transaction_block is not None:
        state_changed_data["timestamp"] = block.foliage_transaction_block.timestamp

    if block.transactions_generator is not None:
        state_changed_data["transaction_generator_size_bytes"] = len(bytes(block.transactions_generator))

    state_changed_data["transaction_generator_ref_list"] = block.transactions_generator_ref_list
    if added is not None:
        state_changed_data["receive_block_result"] = added.value

    self._state_changed("block", state_changed_data)

    record = self.blockchain.block_record(block.header_hash)
    if self.weight_proof_handler is not None and record.sub_epoch_summary_included is not None:
        self._segment_task_list.append(
            create_referenced_task(self.weight_proof_handler.create_prev_sub_epoch_segments())
        )
        for task in self._segment_task_list[:]:
            if task.done():
                self._segment_task_list.remove(task)
    return None


async def add_unfinished_block(
    self: FullNode,
    block: UnfinishedBlock,
    peer: WSChiaConnection | None,
    farmed_block: bool = False,
) -> None:
    """
    We have received an unfinished block, either created by us, or from another peer.
    We can validate and add it and if it's a good block, propagate it to other peers and
    timelords.
    """
    receive_time = time.time()

    if (
        block.prev_header_hash != self.constants.GENESIS_CHALLENGE
        and self.blockchain.try_block_record(block.prev_header_hash) is None
    ):
        # No need to request the parent, since the peer will send it to us anyway, via NewPeak
        self.log.debug("Received a disconnected unfinished block")
        return None

    # Adds the unfinished block to seen, and check if it's seen before, to prevent
    # processing it twice. This searches for the exact version of the unfinished block (there can be many different
    # foliages for the same trunk). This is intentional, to prevent DOS attacks.
    # Note that it does not require that this block was successfully processed
    if self.full_node_store.seen_unfinished_block(block.get_hash()):
        return None

    block_hash = bytes32(block.reward_chain_block.get_hash())
    foliage_tx_hash = block.foliage.foliage_transaction_block_hash

    # If we have already added the block with this reward block hash and
    # foliage hash, return
    if self.full_node_store.get_unfinished_block2(block_hash, foliage_tx_hash)[0] is not None:
        return None

    peak: BlockRecord | None = self.blockchain.get_peak()
    if peak is not None:
        if block.total_iters < peak.sp_total_iters(self.constants):
            # This means this unfinished block is pretty far behind, it will not add weight to our chain
            return None

    if block.prev_header_hash == self.constants.GENESIS_CHALLENGE:
        prev_b = None
    else:
        prev_b = self.blockchain.block_record(block.prev_header_hash)

    # Count the blocks in sub slot, and check if it's a new epoch
    if len(block.finished_sub_slots) > 0:
        num_blocks_in_ss = 1  # Curr
    else:
        curr = self.blockchain.try_block_record(block.prev_header_hash)
        num_blocks_in_ss = 2  # Curr and prev
        while (curr is not None) and not curr.first_in_sub_slot:
            curr = self.blockchain.try_block_record(curr.prev_hash)
            num_blocks_in_ss += 1

    if num_blocks_in_ss > self.constants.MAX_SUB_SLOT_BLOCKS:
        # TODO: potentially allow overflow blocks here, which count for the next slot
        self.log.warning("Too many blocks added, not adding block")
        return None

    # The clvm generator and aggregate signature are validated outside of the lock, to allow other blocks and
    # transactions to get validated
    npc_result: NPCResult | None = None
    pre_validation_time = None

    async with self.blockchain.priority_mutex.acquire(priority=BlockchainMutexPriority.high):
        start_header_time = time.monotonic()
        _, header_error = await self.blockchain.validate_unfinished_block_header(block)
        if header_error is not None:
            if header_error == Err.TIMESTAMP_TOO_FAR_IN_FUTURE:
                raise TimestampError
            else:
                raise ConsensusError(header_error)
        validate_time = time.monotonic() - start_header_time
        self.log.log(
            logging.WARNING if validate_time > 2 else logging.DEBUG,
            f"Time for header validate: {validate_time:0.3f}s",
        )

    if block.transactions_generator is not None:
        pre_validation_start = time.monotonic()
        assert block.transactions_info is not None
        if len(block.transactions_generator_ref_list) > 0:
            generator_refs = set(block.transactions_generator_ref_list)
            generators: dict[uint32, bytes] = await self.blockchain.lookup_block_generators(
                block.prev_header_hash, generator_refs
            )
            generator_args = [generators[height] for height in block.transactions_generator_ref_list]
        else:
            generator_args = []

        height = uint32(0) if prev_b is None else uint32(prev_b.height + 1)
        flags = get_flags_for_height_and_constants(height, self.constants)

        # on mainnet we won't receive unfinished blocks for heights
        # below the hard fork activation, but we have tests where we do
        if height >= self.constants.HARD_FORK_HEIGHT:
            run_block = run_block_generator2
        else:
            run_block = run_block_generator

        # run_block() also validates the signature
        err, conditions = await asyncio.get_running_loop().run_in_executor(
            self.blockchain.pool,
            run_block,
            bytes(block.transactions_generator),
            generator_args,
            min(self.constants.MAX_BLOCK_COST_CLVM, block.transactions_info.cost),
            flags,
            block.transactions_info.aggregated_signature,
            self._bls_cache,
            self.constants,
        )

        if err is not None:
            raise ConsensusError(Err(err))
        assert conditions is not None
        assert conditions.validated_signature
        npc_result = NPCResult(None, conditions)
        pre_validation_time = time.monotonic() - pre_validation_start

    async with self.blockchain.priority_mutex.acquire(priority=BlockchainMutexPriority.high):
        # TODO: pre-validate VDFs outside of lock
        validation_start = time.monotonic()
        validate_result = await self.blockchain.validate_unfinished_block(block, npc_result)
        if validate_result.error is not None:
            raise ConsensusError(Err(validate_result.error))
        validation_time = time.monotonic() - validation_start

    assert validate_result.required_iters is not None

    # Perform another check, in case we have already concurrently added the same unfinished block
    if self.full_node_store.get_unfinished_block2(block_hash, foliage_tx_hash)[0] is not None:
        return None

    if block.prev_header_hash == self.constants.GENESIS_CHALLENGE:
        height = uint32(0)
    else:
        height = uint32(self.blockchain.block_record(block.prev_header_hash).height + 1)

    ses: SubEpochSummary | None = next_sub_epoch_summary(
        self.constants,
        self.blockchain,
        validate_result.required_iters,
        block,
        True,
    )

    self.full_node_store.add_unfinished_block(height, block, validate_result)
    pre_validation_log = (
        f"pre_validation time {pre_validation_time:0.4f}, " if pre_validation_time is not None else ""
    )
    block_duration_in_seconds = (
        receive_time - self.signage_point_times[block.reward_chain_block.signage_point_index]
    )
    if farmed_block is True:
        self.log.info(
            f"🍀 ️Farmed unfinished_block {block_hash}, SP: {block.reward_chain_block.signage_point_index}, "
            f"validation time: {validation_time:0.4f} seconds, {pre_validation_log}"
            f"cost: {block.transactions_info.cost if block.transactions_info else 'None'} "
        )
    else:
        percent_full_str = (
            (
                ", percent full: "
                + str(round(100.0 * float(block.transactions_info.cost) / self.constants.MAX_BLOCK_COST_CLVM, 3))
                + "%"
            )
            if block.transactions_info is not None
            else ""
        )
        self.log.info(
            f"Added unfinished_block {block_hash}, not farmed by us,"
            f" SP: {block.reward_chain_block.signage_point_index} farmer response time: "
            f"{block_duration_in_seconds:0.4f}, "
            f"Pool pk {encode_puzzle_hash(block.foliage.foliage_block_data.pool_target.puzzle_hash, 'xch')}, "
            f"validation time: {validation_time:0.4f} seconds, {pre_validation_log}"
            f"cost: {block.transactions_info.cost if block.transactions_info else 'None'}"
            f"{percent_full_str}"
        )

    sub_slot_iters, difficulty = get_next_sub_slot_iters_and_difficulty(
        self.constants,
        len(block.finished_sub_slots) > 0,
        prev_b,
        self.blockchain,
    )

    if block.reward_chain_block.signage_point_index == 0:
        res = self.full_node_store.get_sub_slot(block.reward_chain_block.pos_ss_cc_challenge_hash)
        if res is None:
            if block.reward_chain_block.pos_ss_cc_challenge_hash == self.constants.GENESIS_CHALLENGE:
                rc_prev = self.constants.GENESIS_CHALLENGE
            else:
                self.log.warning(f"Do not have sub slot {block.reward_chain_block.pos_ss_cc_challenge_hash}")
                return None
        else:
            rc_prev = res[0].reward_chain.get_hash()
    else:
        assert block.reward_chain_block.reward_chain_sp_vdf is not None
        rc_prev = block.reward_chain_block.reward_chain_sp_vdf.challenge

    timelord_request = timelord_protocol.NewUnfinishedBlockTimelord(
        block.reward_chain_block,
        difficulty,
        sub_slot_iters,
        block.foliage,
        ses,
        rc_prev,
    )

    timelord_msg = make_msg(ProtocolMessageTypes.new_unfinished_block_timelord, timelord_request)
    await self.server.send_to_all([timelord_msg], NodeType.TIMELORD)

    # create two versions of the NewUnfinishedBlock message, one to be sent
    # to newer clients and one for older clients
    full_node_request = full_node_protocol.NewUnfinishedBlock(block.reward_chain_block.get_hash())
    msg = make_msg(ProtocolMessageTypes.new_unfinished_block, full_node_request)

    full_node_request2 = full_node_protocol.NewUnfinishedBlock2(
        block.reward_chain_block.get_hash(), block.foliage.foliage_transaction_block_hash
    )
    msg2 = make_msg(ProtocolMessageTypes.new_unfinished_block2, full_node_request2)

    def old_clients(conn: WSChiaConnection) -> bool:
        # don't send this to peers with new clients
        return conn.protocol_version <= Version("0.0.35")

    def new_clients(conn: WSChiaConnection) -> bool:
        # don't send this to peers with old clients
        return conn.protocol_version > Version("0.0.35")

    peer_id: bytes32 | None = None if peer is None else peer.peer_node_id
    await self.server.send_to_all_if([msg], NodeType.FULL_NODE, old_clients, peer_id)
    await self.server.send_to_all_if([msg2], NodeType.FULL_NODE, new_clients, peer_id)

    self._state_changed(
        "unfinished_block",
        {
            "block_duration_in_seconds": block_duration_in_seconds,
            "validation_time_in_seconds": validation_time,
            "pre_validation_time_in_seconds": pre_validation_time,
            "unfinished_block": block.to_json_dict(),
        },
    )


async def new_infusion_point_vdf(
    self: FullNode, request: timelord_protocol.NewInfusionPointVDF, timelord_peer: WSChiaConnection | None = None
) -> Message | None:
    # Lookup unfinished blocks
    unfinished_block: UnfinishedBlock | None = self.full_node_store.get_unfinished_block(
        request.unfinished_reward_hash
    )

    if unfinished_block is None:
        self.log.warning(
            f"Do not have unfinished reward chain block {request.unfinished_reward_hash}, cannot finish."
        )
        return None

    prev_b: BlockRecord | None = None

    target_rc_hash = request.reward_chain_ip_vdf.challenge
    last_slot_cc_hash = request.challenge_chain_ip_vdf.challenge

    # Backtracks through end of slot objects, should work for multiple empty sub slots
    for eos, _, _ in reversed(self.full_node_store.finished_sub_slots):
        if eos is not None and eos.reward_chain.get_hash() == target_rc_hash:
            target_rc_hash = eos.reward_chain.end_of_slot_vdf.challenge
    if target_rc_hash == self.constants.GENESIS_CHALLENGE:
        prev_b = None
    else:
        # Find the prev block, starts looking backwards from the peak. target_rc_hash must be the hash of a block
        # and not an end of slot (since we just looked through the slots and backtracked)
        curr: BlockRecord | None = self.blockchain.get_peak()

        for _ in range(10):
            if curr is None:
                break
            if curr.reward_infusion_new_challenge == target_rc_hash:
                # Found our prev block
                prev_b = curr
                break
            curr = self.blockchain.try_block_record(curr.prev_hash)

        # If not found, cache keyed on prev block
        if prev_b is None:
            self.full_node_store.add_to_future_ip(request)
            self.log.warning(
                f"Previous block is None, infusion point {request.reward_chain_ip_vdf.challenge.hex()}"
            )
            return None

    finished_sub_slots: list[EndOfSubSlotBundle] | None = self.full_node_store.get_finished_sub_slots(
        self.blockchain,
        prev_b,
        last_slot_cc_hash,
    )
    if finished_sub_slots is None:
        return None

    sub_slot_iters, difficulty = get_next_sub_slot_iters_and_difficulty(
        self.constants,
        len(finished_sub_slots) > 0,
        prev_b,
        self.blockchain,
    )

    if unfinished_block.reward_chain_block.pos_ss_cc_challenge_hash == self.constants.GENESIS_CHALLENGE:
        sub_slot_start_iters = uint128(0)
    else:
        ss_res = self.full_node_store.get_sub_slot(unfinished_block.reward_chain_block.pos_ss_cc_challenge_hash)
        if ss_res is None:
            self.log.warning(f"Do not have sub slot {unfinished_block.reward_chain_block.pos_ss_cc_challenge_hash}")
            return None
        _, _, sub_slot_start_iters = ss_res
    sp_total_iters = uint128(
        sub_slot_start_iters
        + calculate_sp_iters(
            self.constants,
            sub_slot_iters,
            unfinished_block.reward_chain_block.signage_point_index,
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
        prev_b,
        self.blockchain,
        sp_total_iters,
        difficulty,
    )
    if not self.has_valid_pool_sig(block):
        self.log.warning("Trying to make a pre-farm block but height is not 0")
        return None
    try:
        await self.add_block(block, None, self._bls_cache, raise_on_disconnected=True)
    except Exception as e:
        self.log.warning(f"Consensus error validating block: {e}")
        if timelord_peer is not None:
            # Only sends to the timelord who sent us this VDF, to reset them to the correct peak
            await self.send_peak_to_timelords(peer=timelord_peer)
    return None


async def add_end_of_sub_slot(
    self: FullNode, end_of_slot_bundle: EndOfSubSlotBundle, peer: WSChiaConnection
) -> tuple[Message | None, bool]:
    fetched_ss = self.full_node_store.get_sub_slot(end_of_slot_bundle.challenge_chain.get_hash())

    # We are not interested in sub-slots which have the same challenge chain but different reward chain. If there
    # is a reorg, we will find out through the broadcast of blocks instead.
    if fetched_ss is not None:
        # Already have the sub-slot
        return None, True

    async with self.timelord_lock:
        fetched_ss = self.full_node_store.get_sub_slot(
            end_of_slot_bundle.challenge_chain.challenge_chain_end_of_slot_vdf.challenge
        )
        if (
            (fetched_ss is None)
            and end_of_slot_bundle.challenge_chain.challenge_chain_end_of_slot_vdf.challenge
            != self.constants.GENESIS_CHALLENGE
        ):
            # If we don't have the prev, request the prev instead
            full_node_request = full_node_protocol.RequestSignagePointOrEndOfSubSlot(
                end_of_slot_bundle.challenge_chain.challenge_chain_end_of_slot_vdf.challenge,
                uint8(0),
                bytes32.zeros,
            )
            return (
                make_msg(ProtocolMessageTypes.request_signage_point_or_end_of_sub_slot, full_node_request),
                False,
            )

        peak = self.blockchain.get_peak()
        if peak is not None and peak.height > 2:
            next_sub_slot_iters, next_difficulty = self.blockchain.get_next_sub_slot_iters_and_difficulty(
                peak.header_hash, True
            )
        else:
            next_sub_slot_iters = self.constants.SUB_SLOT_ITERS_STARTING
            next_difficulty = self.constants.DIFFICULTY_STARTING

        # Adds the sub slot and potentially get new infusions
        new_infusions = self.full_node_store.new_finished_sub_slot(
            end_of_slot_bundle,
            self.blockchain,
            peak,
            next_sub_slot_iters,
            next_difficulty,
            await self.blockchain.get_full_peak(),
        )
        # It may be an empty list, even if it's not None. Not None means added successfully
        if new_infusions is not None:
            self.log.info(
                f"⏲️  Finished sub slot, SP {self.constants.NUM_SPS_SUB_SLOT}/{self.constants.NUM_SPS_SUB_SLOT}, "
                f"{end_of_slot_bundle.challenge_chain.get_hash().hex()}, "
                f"number of sub-slots: {len(self.full_node_store.finished_sub_slots)}, "
                f"RC hash: {end_of_slot_bundle.reward_chain.get_hash().hex()}, "
                f"Deficit {end_of_slot_bundle.reward_chain.deficit}"
            )
            # Reset farmer response timer for sub slot (SP 0)
            self.signage_point_times[0] = time.time()
            # Notify full nodes of the new sub-slot
            broadcast = full_node_protocol.NewSignagePointOrEndOfSubSlot(
                end_of_slot_bundle.challenge_chain.challenge_chain_end_of_slot_vdf.challenge,
                end_of_slot_bundle.challenge_chain.get_hash(),
                uint8(0),
                end_of_slot_bundle.reward_chain.end_of_slot_vdf.challenge,
            )
            msg = make_msg(ProtocolMessageTypes.new_signage_point_or_end_of_sub_slot, broadcast)
            await self.server.send_to_all([msg], NodeType.FULL_NODE, peer.peer_node_id)

            for infusion in new_infusions:
                await self.new_infusion_point_vdf(infusion)
            tx_peak = self.blockchain.get_tx_peak()
            # Notify farmers of the new sub-slot
            broadcast_farmer = farmer_protocol.NewSignagePoint(
                end_of_slot_bundle.challenge_chain.get_hash(),
                end_of_slot_bundle.challenge_chain.get_hash(),
                end_of_slot_bundle.reward_chain.get_hash(),
                next_difficulty,
                next_sub_slot_iters,
                uint8(0),
                uint32(0) if peak is None else peak.height,
                tx_peak.height if tx_peak is not None else uint32(0),
                sp_source_data=SignagePointSourceData(
                    sub_slot_data=SPSubSlotSourceData(
                        end_of_slot_bundle.challenge_chain, end_of_slot_bundle.reward_chain
                    )
                ),
            )
            msg = make_msg(ProtocolMessageTypes.new_signage_point, broadcast_farmer)
            await self.server.send_to_all([msg], NodeType.FARMER)
            return None, True
        else:
            self.log.info(
                f"End of slot not added CC challenge "
                f"{end_of_slot_bundle.challenge_chain.challenge_chain_end_of_slot_vdf.challenge.hex()}"
            )
    return None, False
