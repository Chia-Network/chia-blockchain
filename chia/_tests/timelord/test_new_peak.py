from __future__ import annotations

from typing import List, Optional, Tuple

import pytest

from chia._tests.blockchain.blockchain_test_utils import _validate_and_add_block
from chia._tests.util.blockchain import create_blockchain
from chia._tests.util.time_out_assert import time_out_assert
from chia.consensus.block_record import BlockRecord
from chia.consensus.blockchain import Blockchain
from chia.consensus.difficulty_adjustment import get_next_sub_slot_iters_and_difficulty
from chia.consensus.make_sub_epoch_summary import next_sub_epoch_summary
from chia.protocols import timelord_protocol
from chia.server.server import ChiaServer
from chia.simulator.block_tools import BlockTools
from chia.simulator.full_node_simulator import FullNodeSimulator
from chia.timelord.timelord_api import TimelordAPI
from chia.types.aliases import FullNodeService
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.blockchain_format.sub_epoch_summary import SubEpochSummary
from chia.types.full_block import FullBlock
from chia.types.unfinished_block import UnfinishedBlock
from chia.util.ints import uint128


class TestNewPeak:
    @pytest.mark.anyio
    async def test_timelord_new_peak_basic(
        self, bt: BlockTools, timelord: Tuple[TimelordAPI, ChiaServer], default_1000_blocks: List[FullBlock]
    ) -> None:
        async with create_blockchain(bt.constants, 2) as (b1, db_wrapper1):
            async with create_blockchain(bt.constants, 2) as (b2, db_wrapper2):
                timelord_api, _ = timelord
                for block in default_1000_blocks:
                    await _validate_and_add_block(b1, block)
                    await _validate_and_add_block(b2, block)

                peak = timelord_peak_from_block(b1, default_1000_blocks[-1])
                assert peak is not None
                assert timelord_api.timelord.new_peak is None
                await timelord_api.new_peak_timelord(peak)
                assert timelord_api.timelord.new_peak is not None
                assert timelord_api.timelord.new_peak.reward_chain_block.height == peak.reward_chain_block.height
                blocks = bt.get_consecutive_blocks(1, default_1000_blocks)
                await _validate_and_add_block(b1, blocks[-1])
                await _validate_and_add_block(b2, blocks[-1])

                await timelord_api.new_peak_timelord(timelord_peak_from_block(b1, blocks[-1]))
                assert timelord_api.timelord.new_peak.reward_chain_block.height == blocks[-1].height

                blocks_1 = bt.get_consecutive_blocks(2, blocks)
                await _validate_and_add_block(b1, blocks_1[-2])
                await _validate_and_add_block(b1, blocks_1[-1])
                await timelord_api.new_peak_timelord(timelord_peak_from_block(b1, blocks_1[-2]))
                await timelord_api.new_peak_timelord(timelord_peak_from_block(b1, blocks_1[-1]))
                assert timelord_api.timelord.new_peak.reward_chain_block.height == blocks_1[-1].height

                # new unknown peak, weight less then curr peak
                blocks_2 = bt.get_consecutive_blocks(1, blocks)
                await _validate_and_add_block(b2, blocks_2[-1])
                await timelord_api.new_peak_timelord(timelord_peak_from_block(b2, blocks_2[-1]))
                assert timelord_api.timelord.last_state.last_weight == blocks_1[-1].weight
                assert timelord_api.timelord.last_state.total_iters == blocks_1[-1].reward_chain_block.total_iters

    @pytest.mark.anyio
    async def test_timelord_new_peak_unfinished_not_orphaned(
        self, bt: BlockTools, timelord: Tuple[TimelordAPI, ChiaServer], default_1000_blocks: List[FullBlock]
    ) -> None:
        async with create_blockchain(bt.constants, 2) as (b1, db_wrapper1):
            timelord_api, _ = timelord
            for block in default_1000_blocks:
                await _validate_and_add_block(b1, block)

            peak = timelord_peak_from_block(b1, default_1000_blocks[-1])
            assert peak is not None
            assert timelord_api.timelord.new_peak is None
            await timelord_api.new_peak_timelord(peak)
            assert timelord_api.timelord.new_peak is not None
            assert timelord_api.timelord.new_peak.reward_chain_block.get_hash() == peak.reward_chain_block.get_hash()

            # make two new blocks on tip
            blocks_1 = bt.get_consecutive_blocks(2, default_1000_blocks)
            block_1 = blocks_1[-2]
            block_2 = blocks_1[-1]
            await _validate_and_add_block(b1, block_1)
            await _validate_and_add_block(b1, block_2)

            block_record = b1.block_record(block_2.header_hash)
            sub_slot_iters, difficulty = get_next_sub_slot_iters_and_difficulty(
                bt.constants, len(block_1.finished_sub_slots) > 0, b1.block_record(block_1.prev_header_hash), b1
            )

            timelord_unf_block = timelord_protocol.NewUnfinishedBlockTimelord(
                block_1.reward_chain_block.get_unfinished(),
                difficulty,
                sub_slot_iters,
                block_1.foliage,
                next_sub_epoch_summary(bt.constants, b1, block_record.required_iters, block_1, True),
                await get_rc_prev(b1, block_1),
            )
            await timelord_api.new_unfinished_block_timelord(timelord_unf_block)

            assert timelord_api.timelord.unfinished_blocks[-1].get_hash() == timelord_unf_block.get_hash()
            new_peak = timelord_peak_from_block(b1, block_2)
            assert timelord_unf_block.reward_chain_block.total_iters <= new_peak.reward_chain_block.total_iters
            await timelord_api.new_peak_timelord(new_peak)

            await time_out_assert(60, peak_new_peak_is_none, True, timelord_api)

            assert (
                timelord_api.timelord.last_state.peak.reward_chain_block.get_hash()
                == new_peak.reward_chain_block.get_hash()
            )

    @pytest.mark.anyio
    async def test_timelord_new_peak_unfinished_orphaned(
        self,
        one_node: Tuple[List[FullNodeService], List[FullNodeSimulator], BlockTools],
        timelord: Tuple[TimelordAPI, ChiaServer],
        default_1000_blocks: List[FullBlock],
    ) -> None:
        [full_node_service], _, bt = one_node
        full_node = full_node_service._node
        async with create_blockchain(bt.constants, 2) as (b1, db_wrapper1):
            async with create_blockchain(bt.constants, 2) as (b2, db_wrapper2):
                timelord_api, _ = timelord
                for block in default_1000_blocks:
                    await _validate_and_add_block(b1, block)
                    await _validate_and_add_block(b2, block)
                    await full_node.add_block(block)

                peak = timelord_peak_from_block(b1, default_1000_blocks[-1])
                assert peak is not None
                assert timelord_api.timelord.new_peak is None
                await timelord_api.new_peak_timelord(peak)
                assert timelord_api.timelord.new_peak is not None
                assert (
                    timelord_api.timelord.new_peak.reward_chain_block.get_hash() == peak.reward_chain_block.get_hash()
                )

                # make two new blocks on tip, block_2 has higher total iterations
                block_1 = bt.get_consecutive_blocks(1, default_1000_blocks)[-1]
                block_2 = bt.get_consecutive_blocks(
                    1, default_1000_blocks, min_signage_point=block_1.reward_chain_block.signage_point_index
                )[-1]

                # make sure block_2 has higher iterations then block_1
                assert block_2.total_iters > block_1.total_iters
                # make sure block_1 and block_2 have higher iterations then peak
                assert block_1.total_iters > default_1000_blocks[-1].total_iters

                await _validate_and_add_block(b1, block_1)
                await _validate_and_add_block(b2, block_2)

                block_record_1 = b1.block_record(block_1.header_hash)
                sub_slot_iters, difficulty = get_next_sub_slot_iters_and_difficulty(
                    bt.constants,
                    len(block_1.finished_sub_slots) > 0,
                    b1.block_record(block_1.prev_header_hash),
                    b1,
                )

                timelord_unf_block = timelord_protocol.NewUnfinishedBlockTimelord(
                    block_1.reward_chain_block.get_unfinished(),
                    difficulty,
                    sub_slot_iters,
                    block_1.foliage,
                    next_sub_epoch_summary(bt.constants, b1, block_record_1.required_iters, block_1, True),
                    await get_rc_prev(b1, block_1),
                )
                await timelord_api.new_unfinished_block_timelord(timelord_unf_block)
                assert timelord_api.timelord.unfinished_blocks[-1].get_hash() == timelord_unf_block.get_hash()
                new_peak = timelord_peak_from_block(b2, block_2)

                # timelord knows unfinished block_1 that has lower iterations,
                # add block_2 peak and make sure we skip it and prefer to finish block_1
                assert timelord_unf_block.reward_chain_block.total_iters <= new_peak.reward_chain_block.total_iters
                await timelord_api.new_peak_timelord(new_peak)
                await time_out_assert(60, peak_new_peak_is_none, True, timelord_api)

                # check that peak did not change
                assert (
                    timelord_api.timelord.last_state.peak.reward_chain_block.get_hash()
                    == peak.reward_chain_block.get_hash()
                )
                # check unfinished block_1 is still in cache
                assert timelord_api.timelord.unfinished_blocks[-1].get_hash() == timelord_unf_block.get_hash()

                # full node gets block_1 unfinished
                block_1_unf = UnfinishedBlock(
                    block_1.finished_sub_slots,
                    block_1.reward_chain_block.get_unfinished(),
                    block_1.challenge_chain_sp_proof,
                    block_1.reward_chain_sp_proof,
                    block_1.foliage,
                    block_1.foliage_transaction_block,
                    block_1.transactions_info,
                    block_1.transactions_generator,
                    [],
                )
                await full_node.add_unfinished_block(block_1_unf, None)
                unf: UnfinishedBlock = full_node.full_node_store.get_unfinished_block(block_1_unf.partial_hash)
                assert unf.get_hash() == block_1_unf.get_hash()
                # full node peak is block_2
                await full_node.add_block(block_2)
                curr = await full_node.blockchain.get_full_peak()
                assert block_2.header_hash == curr.header_hash

                # full_node gets finished block_1
                response = timelord_protocol.NewInfusionPointVDF(
                    block_1_unf.partial_hash,
                    block_1.reward_chain_block.challenge_chain_ip_vdf,
                    block_1.challenge_chain_ip_proof,
                    block_1.reward_chain_block.reward_chain_ip_vdf,
                    block_1.reward_chain_ip_proof,
                    block_1.reward_chain_block.infused_challenge_chain_ip_vdf,
                    block_1.infused_challenge_chain_ip_proof,
                )

                await full_node.new_infusion_point_vdf(response)
                peak_after_unf_infusion = await full_node.blockchain.get_full_peak()
                # assert full node switched peak to block_1 since it has the same height as block_2 but lower iterations
                assert peak_after_unf_infusion.header_hash == block_1.header_hash

    @pytest.mark.anyio
    async def test_timelord_new_peak_unfinished_orphaned_overflow(
        self, bt: BlockTools, timelord: Tuple[TimelordAPI, ChiaServer], default_1000_blocks: List[FullBlock]
    ) -> None:
        async with create_blockchain(bt.constants, 2) as (b1, db_wrapper1):
            async with create_blockchain(bt.constants, 2) as (b2, db_wrapper2):
                timelord_api, _ = timelord
                for block in default_1000_blocks:
                    await _validate_and_add_block(b1, block)
                    await _validate_and_add_block(b2, block)

                peak = timelord_peak_from_block(b1, default_1000_blocks[-1])
                assert peak is not None
                assert timelord_api.timelord.new_peak is None
                await timelord_api.new_peak_timelord(peak)
                assert timelord_api.timelord.new_peak is not None
                assert (
                    timelord_api.timelord.new_peak.reward_chain_block.get_hash() == peak.reward_chain_block.get_hash()
                )

                # make two new blocks on tip
                block_1 = bt.get_consecutive_blocks(1, default_1000_blocks, time_per_block=9, force_overflow=True)[-1]
                block_2 = bt.get_consecutive_blocks(
                    1, default_1000_blocks, seed=b"data", time_per_block=50, skip_slots=1
                )[-1]
                # make sure block_2 has higher iterations
                assert block_2.total_iters >= block_1.total_iters

                await _validate_and_add_block(b1, block_1)
                await _validate_and_add_block(b2, block_2)

                block_record = b1.block_record(block_1.header_hash)
                sub_slot_iters, difficulty = get_next_sub_slot_iters_and_difficulty(
                    bt.constants,
                    len(block_1.finished_sub_slots) > 0,
                    b1.block_record(block_1.prev_header_hash),
                    b1,
                )

                timelord_unf_block = timelord_protocol.NewUnfinishedBlockTimelord(
                    block_1.reward_chain_block.get_unfinished(),
                    difficulty,
                    sub_slot_iters,
                    block_1.foliage,
                    next_sub_epoch_summary(bt.constants, b1, block_record.required_iters, block_1, True),
                    await get_rc_prev(b1, block_1),
                )
                await timelord_api.new_unfinished_block_timelord(timelord_unf_block)

                assert timelord_api.timelord.overflow_blocks[-1].get_hash() == timelord_unf_block.get_hash()
                new_peak = timelord_peak_from_block(b2, block_2)
                assert timelord_unf_block.reward_chain_block.total_iters <= new_peak.reward_chain_block.total_iters
                await timelord_api.new_peak_timelord(new_peak)

                await time_out_assert(60, peak_new_peak_is_none, True, timelord_api)

                assert (
                    timelord_api.timelord.last_state.peak.reward_chain_block.get_hash()
                    == peak.reward_chain_block.get_hash()
                )

    @pytest.mark.anyio
    async def test_timelord_new_peak_unfinished_eos(
        self, bt: BlockTools, timelord: Tuple[TimelordAPI, ChiaServer], default_1000_blocks: List[FullBlock]
    ) -> None:
        async with create_blockchain(bt.constants, 2) as (b1, db_wrapper1):
            async with create_blockchain(bt.constants, 2) as (b2, db_wrapper2):
                timelord_api, _ = timelord
                for block in default_1000_blocks:
                    await _validate_and_add_block(b1, block)
                    await _validate_and_add_block(b2, block)

                peak = timelord_peak_from_block(b1, default_1000_blocks[-1])
                assert peak is not None
                assert timelord_api.timelord.new_peak is None
                await timelord_api.new_peak_timelord(peak)
                assert timelord_api.timelord.new_peak is not None
                assert (
                    timelord_api.timelord.new_peak.reward_chain_block.get_hash() == peak.reward_chain_block.get_hash()
                )

                # make two new blocks on tip, block_2 is in a new slot
                block_1 = bt.get_consecutive_blocks(1, default_1000_blocks)[-1]
                block_2 = bt.get_consecutive_blocks(
                    1, default_1000_blocks, skip_slots=1, skip_overflow=True, seed=b"data"
                )[-1]

                # make sure block_2 has higher iterations
                assert block_2.total_iters >= block_1.total_iters

                await _validate_and_add_block(b1, block_1)
                await _validate_and_add_block(b2, block_2)

                block_record = b2.block_record(block_2.header_hash)
                sub_slot_iters, difficulty = get_next_sub_slot_iters_and_difficulty(
                    bt.constants,
                    len(block_2.finished_sub_slots) > 0,
                    b1.block_record(block_2.prev_header_hash),
                    b1,
                )

                timelord_unf_block = timelord_protocol.NewUnfinishedBlockTimelord(
                    block_2.reward_chain_block.get_unfinished(),
                    difficulty,
                    sub_slot_iters,
                    block_2.foliage,
                    next_sub_epoch_summary(bt.constants, b1, block_record.required_iters, block_2, True),
                    await get_rc_prev(b2, block_2),
                )
                timelord_api.timelord.last_state.set_state(block_2.finished_sub_slots[-1])

                # add unfinished and make sure we cache it
                await timelord_api.new_unfinished_block_timelord(timelord_unf_block)
                assert timelord_api.timelord.unfinished_blocks[-1].get_hash() == timelord_unf_block.get_hash()
                new_peak = timelord_peak_from_block(b1, block_1)
                assert timelord_unf_block.reward_chain_block.total_iters >= new_peak.reward_chain_block.total_iters
                await timelord_api.new_peak_timelord(new_peak)
                await time_out_assert(60, peak_new_peak_is_none, True, timelord_api)

                # make sure we switch to lower iteration peak
                assert (
                    timelord_api.timelord.last_state.peak.reward_chain_block.get_hash()
                    == new_peak.reward_chain_block.get_hash()
                )


async def get_rc_prev(blockchain: Blockchain, block: FullBlock) -> bytes32:
    if block.reward_chain_block.signage_point_index == 0:
        # find first in slot and find slot challenge
        blk = blockchain.block_record(block.header_hash)
        while blk.first_in_sub_slot is False:
            blk = blockchain.block_record(block.prev_header_hash)
        full_blk = await blockchain.get_full_block(blk.header_hash)
        assert full_blk is not None
        sub_slot = None
        for s in full_blk.finished_sub_slots:
            if s is not None and s.challenge_chain.get_hash() == block.reward_chain_block.pos_ss_cc_challenge_hash:
                sub_slot = s
        if sub_slot is None:
            assert block.reward_chain_block.pos_ss_cc_challenge_hash == blockchain.constants.GENESIS_CHALLENGE
            rc_prev = blockchain.constants.GENESIS_CHALLENGE
        else:
            rc_prev = sub_slot.reward_chain.get_hash()
    else:
        assert block.reward_chain_block.reward_chain_sp_vdf is not None
        rc_prev = block.reward_chain_block.reward_chain_sp_vdf.challenge
    return rc_prev


def get_recent_reward_challenges(blockchain: Blockchain) -> List[Tuple[bytes32, uint128]]:
    peak = blockchain.get_peak()
    if peak is None:
        return []
    recent_rc: List[Tuple[bytes32, uint128]] = []
    curr: Optional[BlockRecord] = peak
    while curr is not None and len(recent_rc) < 2 * blockchain.constants.MAX_SUB_SLOT_BLOCKS:
        if curr != peak:
            recent_rc.append((curr.reward_infusion_new_challenge, curr.total_iters))
        if curr.first_in_sub_slot:
            assert curr.finished_reward_slot_hashes is not None
            sub_slot_total_iters = curr.ip_sub_slot_total_iters(blockchain.constants)
            # Start from the most recent
            for rc in reversed(curr.finished_reward_slot_hashes):
                if sub_slot_total_iters < curr.sub_slot_iters:
                    break
                recent_rc.append((rc, sub_slot_total_iters))
                sub_slot_total_iters = uint128(sub_slot_total_iters - curr.sub_slot_iters)
        curr = blockchain.try_block_record(curr.prev_hash)
    return list(reversed(recent_rc))


def timelord_peak_from_block(
    blockchain: Blockchain,
    block: FullBlock,
) -> timelord_protocol.NewPeakTimelord:
    peak = blockchain.block_record(block.header_hash)
    _, difficulty = get_next_sub_slot_iters_and_difficulty(blockchain.constants, False, peak, blockchain)
    ses: Optional[SubEpochSummary] = next_sub_epoch_summary(
        blockchain.constants, blockchain, peak.required_iters, block, True
    )

    curr = peak
    while not curr.is_challenge_block(blockchain.constants) and not curr.first_in_sub_slot:
        curr = blockchain.block_record(curr.prev_hash)

    if curr.is_challenge_block(blockchain.constants):
        last_csb_or_eos = curr.total_iters
    else:
        last_csb_or_eos = curr.ip_sub_slot_total_iters(blockchain.constants)

    curr = peak
    passed_ses_height_but_not_yet_included = True
    while (curr.height % blockchain.constants.SUB_EPOCH_BLOCKS) != 0:
        if curr.sub_epoch_summary_included:
            passed_ses_height_but_not_yet_included = False
        curr = blockchain.block_record(curr.prev_hash)
    if curr.sub_epoch_summary_included or curr.height == 0:
        passed_ses_height_but_not_yet_included = False
    return timelord_protocol.NewPeakTimelord(
        block.reward_chain_block,
        difficulty,
        peak.deficit,
        peak.sub_slot_iters,
        ses,
        get_recent_reward_challenges(blockchain),
        last_csb_or_eos,
        passed_ses_height_but_not_yet_included,
    )


def peak_new_peak_is_none(timelord: TimelordAPI) -> bool:
    return timelord.timelord.new_peak is None
