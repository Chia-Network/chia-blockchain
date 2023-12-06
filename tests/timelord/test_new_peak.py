from __future__ import annotations

from typing import List, Optional, Tuple

import pytest

from chia.consensus.block_record import BlockRecord
from chia.consensus.blockchain import Blockchain
from chia.consensus.difficulty_adjustment import get_next_sub_slot_iters_and_difficulty
from chia.consensus.make_sub_epoch_summary import next_sub_epoch_summary
from chia.protocols import timelord_protocol
from chia.server.server import ChiaServer
from chia.simulator.block_tools import BlockTools
from chia.timelord.timelord_api import TimelordAPI
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.blockchain_format.sub_epoch_summary import SubEpochSummary
from chia.types.full_block import FullBlock
from chia.util.ints import uint128
from tests.blockchain.blockchain_test_utils import _validate_and_add_block
from tests.util.blockchain import create_blockchain
from tests.util.time_out_assert import time_out_assert


class TestNewPeak:
    @pytest.mark.anyio
    async def test_timelord_new_peak_basic(
        self, bt: BlockTools, timelord: Tuple[TimelordAPI, ChiaServer], default_1000_blocks: List[FullBlock]
    ) -> None:
        b1, db_wrapper1 = await create_blockchain(bt.constants, 2)
        b2, db_wrapper2 = await create_blockchain(bt.constants, 2)

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

        await db_wrapper1.close()
        await db_wrapper2.close()
        b1.shut_down()
        b2.shut_down()

        return None

    @pytest.mark.anyio
    async def test_timelord_new_peak_heavier_unfinished_same_chain_not_orphand(
        self, bt: BlockTools, timelord: Tuple[TimelordAPI, ChiaServer], default_1000_blocks: List[FullBlock]
    ) -> None:
        b1, db_wrapper1 = await create_blockchain(bt.constants, 2)
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
        await _validate_and_add_block(b1, blocks_1[-2])
        await _validate_and_add_block(b1, blocks_1[-1])
        block_record = b1.block_record(blocks_1[-1].header_hash)
        block_1 = blocks_1[-2]
        block_2 = blocks_1[-1]

        ses: Optional[SubEpochSummary] = next_sub_epoch_summary(
            bt.constants, b1, block_record.required_iters, block_1, True
        )

        sub_slot_iters, difficulty = get_next_sub_slot_iters_and_difficulty(
            bt.constants, len(block_1.finished_sub_slots) > 0, b1.block_record(block_1.prev_header_hash), b1
        )

        rc_prev = await get_rc_prev(b1, block_1)

        timelord_unf_block = timelord_protocol.NewUnfinishedBlockTimelord(
            block_1.reward_chain_block.get_unfinished(), difficulty, sub_slot_iters, block_1.foliage, ses, rc_prev
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

        await db_wrapper1.close()
        b1.shut_down()

        return None

    @pytest.mark.anyio
    async def test_timelord_new_peak_heavier_unfinished_same_chain_orphand(
        self, bt: BlockTools, timelord: Tuple[TimelordAPI, ChiaServer], default_1000_blocks: List[FullBlock]
    ) -> None:
        b1, db_wrapper1 = await create_blockchain(bt.constants, 2)
        b2, db_wrapper2 = await create_blockchain(bt.constants, 2)

        timelord_api, _ = timelord
        for block in default_1000_blocks:
            await _validate_and_add_block(b1, block)
            await _validate_and_add_block(b2, block)

        peak = timelord_peak_from_block(b1, default_1000_blocks[-1])
        assert peak is not None
        assert timelord_api.timelord.new_peak is None
        await timelord_api.new_peak_timelord(peak)
        assert timelord_api.timelord.new_peak is not None
        assert timelord_api.timelord.new_peak.reward_chain_block.get_hash() == peak.reward_chain_block.get_hash()

        # make two new blocks on tip
        blocks_1 = bt.get_consecutive_blocks(1, default_1000_blocks, time_per_block=9)
        await _validate_and_add_block(b1, blocks_1[-1])
        blocks_2 = bt.get_consecutive_blocks(1, default_1000_blocks, seed=b"data", time_per_block=50)
        await _validate_and_add_block(b2, blocks_2[-1])
        block_record = b1.block_record(blocks_1[-1].header_hash)
        block_1 = blocks_1[-1]
        block_2 = blocks_2[-1]

        assert block_2.total_iters >= block_1.total_iters

        ses: Optional[SubEpochSummary] = next_sub_epoch_summary(
            bt.constants, b1, block_record.required_iters, block_1, True
        )

        sub_slot_iters, difficulty = get_next_sub_slot_iters_and_difficulty(
            bt.constants, len(block_1.finished_sub_slots) > 0, b1.block_record(blocks_1[-1].prev_header_hash), b1
        )

        rc_prev = await get_rc_prev(b1, block_1)

        timelord_unf_block = timelord_protocol.NewUnfinishedBlockTimelord(
            block_1.reward_chain_block.get_unfinished(), difficulty, sub_slot_iters, block_1.foliage, ses, rc_prev
        )
        await timelord_api.new_unfinished_block_timelord(timelord_unf_block)

        assert timelord_api.timelord.unfinished_blocks[-1].get_hash() == timelord_unf_block.get_hash()
        new_peak = timelord_peak_from_block(b2, block_2)
        assert timelord_unf_block.reward_chain_block.total_iters <= new_peak.reward_chain_block.total_iters
        await timelord_api.new_peak_timelord(new_peak)

        await time_out_assert(60, peak_new_peak_is_none, True, timelord_api)

        assert timelord_api.timelord.last_state.peak.reward_chain_block.get_hash() == peak.reward_chain_block.get_hash()

        await db_wrapper1.close()
        await db_wrapper2.close()
        b1.shut_down()
        b2.shut_down()

        return None


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

    recent_rc = get_recent_reward_challenges(blockchain)
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
        recent_rc,
        last_csb_or_eos,
        passed_ses_height_but_not_yet_included,
    )


def peak_new_peak_is_none(timelord: TimelordAPI) -> bool:
    return timelord.timelord.new_peak is None
