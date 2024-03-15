from __future__ import annotations

from typing import List, Optional, Tuple

import pytest

from chia._tests.blockchain.blockchain_test_utils import _validate_and_add_block
from chia._tests.util.blockchain import create_blockchain
from chia.consensus.block_record import BlockRecord
from chia.consensus.blockchain_interface import BlockchainInterface
from chia.consensus.constants import ConsensusConstants
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

                peak = timelord_peak_from_block(default_1000_blocks[-1], b1, bt.constants)
                assert peak is not None
                assert timelord_api.timelord.new_peak is None
                await timelord_api.new_peak_timelord(peak)
                assert timelord_api.timelord.new_peak is not None
                assert timelord_api.timelord.new_peak.reward_chain_block.height == peak.reward_chain_block.height
                blocks = bt.get_consecutive_blocks(1, default_1000_blocks)
                await _validate_and_add_block(b1, blocks[-1])
                await _validate_and_add_block(b2, blocks[-1])

                await timelord_api.new_peak_timelord(timelord_peak_from_block(blocks[-1], b1, bt.constants))
                assert timelord_api.timelord.new_peak.reward_chain_block.height == blocks[-1].height

                blocks_1 = bt.get_consecutive_blocks(2, blocks)
                await _validate_and_add_block(b1, blocks_1[-2])
                await _validate_and_add_block(b1, blocks_1[-1])
                await timelord_api.new_peak_timelord(timelord_peak_from_block(blocks_1[-2], b1, bt.constants))
                await timelord_api.new_peak_timelord(timelord_peak_from_block(blocks_1[-1], b1, bt.constants))
                assert timelord_api.timelord.new_peak.reward_chain_block.height == blocks_1[-1].height

                # # new unknown peak, weight less then curr peak
                # blocks_2 = bt.get_consecutive_blocks(1, blocks)
                # await _validate_and_add_block(b2, blocks_2[-1])
                # await timelord_api.new_peak_timelord(timelord_peak_from_block(blocks_2[-1], b2, bt.constants))
                # assert timelord_api.timelord.new_peak.reward_chain_block.height == blocks_1[-1].height

    @pytest.mark.anyio
    async def test_timelord_new_peak_heavier_unfinished(
        self, bt: BlockTools, timelord: Tuple[TimelordAPI, ChiaServer], default_1000_blocks: List[FullBlock]
    ) -> None:
        async with create_blockchain(bt.constants, 2) as (b1, db_wrapper1):
            async with create_blockchain(bt.constants, 2) as (b2, db_wrapper2):
                timelord_api, _ = timelord
                for block in default_1000_blocks:
                    await _validate_and_add_block(b1, block)
                    await _validate_and_add_block(b2, block)

                peak = timelord_peak_from_block(default_1000_blocks[-1], b1, bt.constants)
                assert peak is not None
                assert timelord_api.timelord.new_peak is None
                await timelord_api.new_peak_timelord(peak)
                assert timelord_api.timelord.new_peak is not None
                assert timelord_api.timelord.new_peak.reward_chain_block.height == peak.reward_chain_block.height

                # make two new blocks on tip
                blocks_1 = bt.get_consecutive_blocks(2, default_1000_blocks)
                await _validate_and_add_block(b1, blocks_1[-2])
                await _validate_and_add_block(b1, blocks_1[-1])
                blocks_2 = bt.get_consecutive_blocks(1, default_1000_blocks)
                await _validate_and_add_block(b2, blocks_2[-1])
                block_record = b1.block_record(blocks_1[-1].header_hash)
                block = blocks_1[-1]

                ses: Optional[SubEpochSummary] = next_sub_epoch_summary(
                    bt.constants, b1, block_record.required_iters, block, True
                )

                sub_slot_iters, difficulty = get_next_sub_slot_iters_and_difficulty(
                    bt.constants, len(block.finished_sub_slots) > 0, b1.block_record(blocks_1[-1].prev_header_hash), b1
                )

                if block.reward_chain_block.signage_point_index == 0:
                    # find first in slot and find slot challenge
                    blk = b1.block_record(blocks_1[-1].header_hash)
                    while blk.first_in_sub_slot is False:
                        blk = b1.block_record(blocks_1[-1].prev_header_hash)
                    full_blk = await b1.get_full_block(blk.header_hash)
                    sub_slot = None
                    for s in full_blk.finished_sub_slots:
                        if (
                            s is not None
                            and s.challenge_chain.get_hash() == block.reward_chain_block.pos_ss_cc_challenge_hash
                        ):
                            sub_slot = s
                    if sub_slot is None:
                        assert block.reward_chain_block.pos_ss_cc_challenge_hash == bt.constants.GENESIS_CHALLENGE
                        rc_prev = bt.constants.GENESIS_CHALLENGE
                    else:
                        rc_prev = sub_slot.reward_chain.get_hash()
                else:
                    assert block.reward_chain_block.reward_chain_sp_vdf is not None
                    rc_prev = block.reward_chain_block.reward_chain_sp_vdf.challenge

                timelord_unf_block = timelord_protocol.NewUnfinishedBlockTimelord(
                    block.reward_chain_block.get_unfinished(), difficulty, sub_slot_iters, block.foliage, ses, rc_prev
                )

                timelord_api.new_unfinished_block_timelord(timelord_unf_block)

                await timelord_api.new_peak_timelord(timelord_peak_from_block(blocks_2[-1], b2, bt.constants))
                assert timelord_api.timelord.last_state.get_height() == peak.reward_chain_block.height


def get_recent_reward_challenges(
    blockchain: BlockchainInterface, constants: ConsensusConstants
) -> List[Tuple[bytes32, uint128]]:
    peak = blockchain.get_peak()
    if peak is None:
        return []
    recent_rc: List[Tuple[bytes32, uint128]] = []
    curr: Optional[BlockRecord] = peak
    while curr is not None and len(recent_rc) < 2 * constants.MAX_SUB_SLOT_BLOCKS:
        if curr != peak:
            recent_rc.append((curr.reward_infusion_new_challenge, curr.total_iters))
        if curr.first_in_sub_slot:
            assert curr.finished_reward_slot_hashes is not None
            sub_slot_total_iters = curr.ip_sub_slot_total_iters(constants)
            # Start from the most recent
            for rc in reversed(curr.finished_reward_slot_hashes):
                if sub_slot_total_iters < curr.sub_slot_iters:
                    break
                recent_rc.append((rc, sub_slot_total_iters))
                sub_slot_total_iters = uint128(sub_slot_total_iters - curr.sub_slot_iters)
        curr = blockchain.try_block_record(curr.prev_hash)
    return list(reversed(recent_rc))


def timelord_peak_from_block(
    block: FullBlock, blockchain: BlockchainInterface, constants: ConsensusConstants
) -> timelord_protocol.NewPeakTimelord:
    peak = blockchain.block_record(block.header_hash)
    _, difficulty = get_next_sub_slot_iters_and_difficulty(constants, False, peak, blockchain)
    ses: Optional[SubEpochSummary] = next_sub_epoch_summary(constants, blockchain, peak.required_iters, block, True)

    recent_rc = get_recent_reward_challenges(blockchain, constants)
    curr = peak
    while not curr.is_challenge_block(constants) and not curr.first_in_sub_slot:
        curr = blockchain.block_record(curr.prev_hash)

    if curr.is_challenge_block(constants):
        last_csb_or_eos = curr.total_iters
    else:
        last_csb_or_eos = curr.ip_sub_slot_total_iters(constants)

    curr = peak
    passed_ses_height_but_not_yet_included = True
    while (curr.height % constants.SUB_EPOCH_BLOCKS) != 0:
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
