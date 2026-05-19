from __future__ import annotations

import pytest
from chia_rs import ConsensusConstants, FullBlock
from chia_rs.sized_ints import uint8, uint32

from chia.consensus.get_block_challenge import is_infused_before_sp, pre_sp_tx_block_height
from chia.consensus.pot_iterations import is_overflow_block
from chia.simulator.block_tools import BlockTools, load_block_list, test_constants
from chia.util.block_cache import BlockCache


@pytest.mark.parametrize(
    "candidate_sp_index,sp_index,slots_crossed,overflow,expected",
    [
        # Same slot, candidate SP 1 infuses at 4, which is before checked SP 5. Expected: True.
        pytest.param(1, 5, 0, False, True, id="non-overflow-same-slot-after-extra-intervals"),
        # Same slot, candidate SP 2 infuses at 5, exactly at checked SP 5. Expected: False.
        pytest.param(2, 5, 0, False, False, id="non-overflow-same-slot-at-extra-interval-boundary"),
        # Same slot with index wrap, candidate SP 14 infuses at 1, exactly at checked SP 1. Expected: False.
        pytest.param(14, 1, 0, False, False, id="non-overflow-wrapped-same-slot-at-boundary"),
        # Same slot with index wrap, candidate SP 13 infuses at 0, before checked SP 1. Expected: True.
        pytest.param(13, 1, 0, False, True, id="non-overflow-wrapped-same-slot-before-sp"),
        # One crossed slot, candidate SP 1 from the previous slot infuses before checked SP 1. Expected: True.
        pytest.param(1, 1, 1, False, True, id="non-overflow-crossed-slot-same-sp"),
        # One crossed slot, candidate SP 15 is an overflow candidate infused after checked SP 1. Expected: False.
        pytest.param(15, 1, 1, False, False, id="non-overflow-crossed-slot-overflow-candidate-after-sp"),
        # One crossed slot, candidate SP 14 infuses exactly at checked SP 1. Expected: False.
        pytest.param(14, 1, 1, False, False, id="non-overflow-crossed-slot-at-boundary"),
        # One crossed slot, candidate SP 13 infuses before checked SP 1. Expected: True.
        pytest.param(13, 1, 1, False, True, id="non-overflow-crossed-slot-before-sp"),
        # Checked SP is overflow; no crossed slot means low-SP candidate is after the checked SP. Expected: False.
        pytest.param(1, 15, 0, True, False, id="overflow-no-crossed-slot-low-sp-candidate-after-overflow-sp"),
        # Checked SP is overflow; no crossed slot, candidate SP 11 infuses at boundary/after. Expected: False.
        pytest.param(11, 15, 0, True, False, id="overflow-no-crossed-slot-before-boundary-still-after-sp"),
        # Checked SP is overflow; no crossed slot and same SP cannot be before itself. Expected: False.
        pytest.param(15, 15, 0, True, False, id="overflow-no-crossed-slot-same-sp"),
        # Checked SP is overflow; one crossed slot puts low-SP candidate before the checked SP. Expected: True.
        pytest.param(1, 15, 1, True, True, id="overflow-crossed-slot-low-sp-candidate-before-sp"),
        # Checked SP is overflow; one crossed slot, candidate SP 11 infuses before checked SP 15. Expected: True.
        pytest.param(11, 15, 1, True, True, id="overflow-crossed-slot-before-sp"),
        # Checked SP is overflow; one crossed slot, candidate SP 12 infuses exactly at checked SP 15. Expected: False.
        pytest.param(12, 15, 1, True, False, id="overflow-crossed-slot-at-extra-interval-boundary"),
        # Checked SP is overflow; two crossed slots makes even same-SP candidate safely before it. Expected: True.
        pytest.param(15, 15, 2, True, True, id="overflow-two-crossed-slots-same-sp"),
    ],
)
def test_is_infused_before_sp(
    candidate_sp_index: int,
    sp_index: int,
    slots_crossed: int,
    overflow: bool,
    expected: bool,
) -> None:
    assert (
        is_infused_before_sp(
            test_constants,
            uint8(candidate_sp_index),
            uint8(sp_index),
            slots_crossed,
            overflow,
        )
        is expected
    )


def test_is_infused_before_sp_matches_iteration_comparison() -> None:
    sp_interval_iters = int(test_constants.SUB_SLOT_ITERS_STARTING // test_constants.NUM_SPS_SUB_SLOT)
    num_sps = int(test_constants.NUM_SPS_SUB_SLOT)
    extra_intervals = int(test_constants.NUM_SP_INTERVALS_EXTRA)

    for sp_index in range(num_sps):
        overflow = is_overflow_block(test_constants, uint8(sp_index))
        checked_sp_total_intervals = sp_index - (num_sps if overflow else 0)

        for candidate_sp_index in range(num_sps):
            for slots_crossed in range(3):
                candidate_sp_total_intervals = candidate_sp_index - slots_crossed * num_sps
                if not overflow and checked_sp_total_intervals - candidate_sp_total_intervals <= 0:
                    candidate_sp_total_intervals -= num_sps

                checked_sp_total_iters = checked_sp_total_intervals * sp_interval_iters
                candidate_ip_total_iters = (candidate_sp_total_intervals + extra_intervals) * sp_interval_iters + 1
                expected = candidate_ip_total_iters < checked_sp_total_iters

                assert (
                    is_infused_before_sp(
                        test_constants,
                        uint8(candidate_sp_index),
                        uint8(sp_index),
                        slots_crossed,
                        overflow,
                    )
                    is expected
                ), (
                    candidate_sp_index,
                    sp_index,
                    slots_crossed,
                    overflow,
                    candidate_ip_total_iters,
                    checked_sp_total_iters,
                )


def test_prev_tx_block_none() -> None:
    # If prev_b is None, should return 0
    assert pre_sp_tx_block_height(
        constants=test_constants,
        blocks=BlockCache({}),
        prev_b_hash=test_constants.GENESIS_CHALLENGE,
        sp_index=uint8(0),
        finished_sub_slots=0,
    ) == uint32(0)
    assert pre_sp_tx_block_height(
        constants=test_constants,
        blocks=BlockCache({}),
        prev_b_hash=test_constants.GENESIS_CHALLENGE,
        sp_index=uint8(1),
        finished_sub_slots=1,
    ) == uint32(0)


def test_prev_tx_block_blockrecord_tx(bt: BlockTools) -> None:
    # If prev_b is BlockRecord and prev_transaction_block_hash is not None, return its height
    block_list = bt.get_consecutive_blocks(
        10,
        block_list_input=[],
        guarantee_transaction_block=True,
    )
    _, _, blocks = load_block_list(block_list, bt.constants)
    block = block_list[-1]
    latest_tx_before_sp = find_tx_before_sp(block_list, bt.constants)
    assert latest_tx_before_sp is not None
    assert (
        pre_sp_tx_block_height(
            constants=bt.constants,
            blocks=BlockCache(blocks),
            prev_b_hash=block.prev_header_hash,
            sp_index=block.reward_chain_block.signage_point_index,
            finished_sub_slots=len(block.finished_sub_slots),
        )
        == latest_tx_before_sp.height
    )
    block = block_list[-2]
    latest_tx_before_sp = find_tx_before_sp(block_list[:-1], bt.constants)
    assert latest_tx_before_sp is not None
    assert (
        pre_sp_tx_block_height(
            constants=bt.constants,
            blocks=BlockCache(blocks),
            prev_b_hash=block.prev_header_hash,
            sp_index=block.reward_chain_block.signage_point_index,
            finished_sub_slots=len(block.finished_sub_slots),
        )
        == latest_tx_before_sp.height
    )
    block = block_list[-3]
    latest_tx_before_sp = find_tx_before_sp(block_list[:-2], bt.constants)
    assert latest_tx_before_sp is not None
    assert (
        pre_sp_tx_block_height(
            constants=bt.constants,
            blocks=BlockCache(blocks),
            prev_b_hash=block.prev_header_hash,
            sp_index=block.reward_chain_block.signage_point_index,
            finished_sub_slots=len(block.finished_sub_slots),
        )
        == latest_tx_before_sp.height
    )


def test_prev_tx_block_blockrecord_not_tx(bt: BlockTools) -> None:
    # If prev_b is BlockRecord and prev_transaction_block_hash is not None, return its height
    block_list = bt.get_consecutive_blocks(
        8,
        block_list_input=[],
        guarantee_transaction_block=True,
    )
    block_list = bt.get_consecutive_blocks(
        2,
        block_list_input=block_list,
    )
    _, _, blocks = load_block_list(block_list, bt.constants)
    block = block_list[-1]
    latest_tx_before_sp = find_tx_before_sp(block_list, bt.constants)
    assert latest_tx_before_sp is not None
    assert pre_sp_tx_block_height(
        constants=bt.constants,
        blocks=BlockCache(blocks),
        prev_b_hash=block.prev_header_hash,
        sp_index=block.reward_chain_block.signage_point_index,
        finished_sub_slots=len(block.finished_sub_slots),
    ) == uint32(latest_tx_before_sp.height)


# get the latest infused transaction block before the signage point of the last block in the list
def find_tx_before_sp(block_list: list[FullBlock], constants: ConsensusConstants) -> FullBlock | None:
    sp_index = block_list[-1].reward_chain_block.signage_point_index
    overflow = is_overflow_block(constants, sp_index)
    slots_crossed = len(block_list[-1].finished_sub_slots)
    idx = len(block_list) - 2
    curr = None
    while idx > 0:
        curr = block_list[idx]
        if curr.foliage_transaction_block is not None and is_infused_before_sp(
            constants,
            curr.reward_chain_block.signage_point_index,
            sp_index,
            slots_crossed,
            overflow,
        ):
            break
        if len(curr.finished_sub_slots) > 0:
            slots_crossed += 1
        idx -= 1
    return curr
