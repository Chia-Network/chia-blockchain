from __future__ import annotations

import pytest
from chia_rs import ConsensusConstants, FullBlock
from chia_rs.sized_ints import uint8, uint32

import chia.consensus.get_block_challenge as get_block_challenge_module
from chia.consensus.blockchain_mmr import BlockchainMMRManager
from chia.consensus.get_block_challenge import is_infused_before_sp, post_hard_fork2, pre_sp_tx_block_height
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
        # Same slot, candidate SP 15 is an overflow candidate infused after checked SP 1. Expected: False.
        pytest.param(15, 1, 0, False, False, id="non-overflow-same-slot-overflow-candidate-after-sp"),
        # One crossed slot, candidate SP 15 is an overflow candidate infused before checked SP 1. Expected: True.
        pytest.param(15, 1, 1, False, True, id="non-overflow-crossed-slot-overflow-candidate-before-sp"),
        # One crossed slot, candidate SP 14 is an overflow candidate infused before checked SP 1. Expected: True.
        pytest.param(14, 1, 1, False, True, id="non-overflow-crossed-slot-overflow-candidate-before-sp"),
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
        # Checked SP is overflow; one crossed slot and same overflow SP is safely before it. Expected: True.
        pytest.param(15, 15, 1, True, True, id="overflow-crossed-slot-same-overflow-sp"),
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
                candidate_overflow = is_overflow_block(test_constants, uint8(candidate_sp_index))
                candidate_sp_total_intervals = candidate_sp_index - (
                    slots_crossed + int(candidate_overflow)
                ) * num_sps

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
        blocks=BlockCache({}, BlockchainMMRManager(test_constants.GENESIS_CHALLENGE)),
        prev_b_hash=test_constants.GENESIS_CHALLENGE,
        sp_index=uint8(0),
        finished_sub_slots=0,
    ) == uint32(0)
    assert pre_sp_tx_block_height(
        constants=test_constants,
        blocks=BlockCache({}, BlockchainMMRManager(test_constants.GENESIS_CHALLENGE)),
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
            blocks=BlockCache(blocks, BlockchainMMRManager(bt.constants.GENESIS_CHALLENGE)),
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
            blocks=BlockCache(blocks, BlockchainMMRManager(bt.constants.GENESIS_CHALLENGE)),
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
            blocks=BlockCache(blocks, BlockchainMMRManager(bt.constants.GENESIS_CHALLENGE)),
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
        blocks=BlockCache(blocks, BlockchainMMRManager(bt.constants.GENESIS_CHALLENGE)),
        prev_b_hash=block.prev_header_hash,
        sp_index=block.reward_chain_block.signage_point_index,
        finished_sub_slots=len(block.finished_sub_slots),
    ) == uint32(latest_tx_before_sp.height)


def test_post_hard_fork2_uses_actual_finished_sub_slot_count(bt: BlockTools) -> None:
    block_list = bt.get_consecutive_blocks(
        8,
        block_list_input=[],
        guarantee_transaction_block=True,
    )
    candidate_block: FullBlock | None = None
    actual_height: uint32 | None = None
    reduced_height: uint32 | None = None
    block_cache: BlockCache | None = None
    overflow_blocks: list[FullBlock] = []

    for seed in range(8):
        block_list = bt.get_consecutive_blocks(
            1,
            block_list_input=block_list,
            guarantee_transaction_block=True,
            skip_slots=1,
            force_overflow=True,
            seed=seed.to_bytes(2, "big"),
        )
        overflow_blocks.append(block_list[-1])

    _, _, blocks = load_block_list(block_list, bt.constants)
    block_cache = BlockCache(blocks, BlockchainMMRManager(bt.constants.GENESIS_CHALLENGE))

    for block in reversed(overflow_blocks):
        sp_index = block.reward_chain_block.signage_point_index
        assert is_overflow_block(bt.constants, sp_index)

        actual_height = pre_sp_tx_block_height(
            constants=bt.constants,
            blocks=block_cache,
            prev_b_hash=block.header_hash,
            sp_index=sp_index,
            finished_sub_slots=1,
        )
        reduced_height = pre_sp_tx_block_height(
            constants=bt.constants,
            blocks=block_cache,
            prev_b_hash=block.header_hash,
            sp_index=sp_index,
            finished_sub_slots=0,
        )
        if actual_height != reduced_height:
            candidate_block = block
            break

    assert candidate_block is not None
    assert actual_height is not None
    assert reduced_height is not None
    assert block_cache is not None

    assert actual_height == candidate_block.height
    assert reduced_height < actual_height

    constants = bt.constants.replace(HARD_FORK2_HEIGHT=actual_height)
    assert post_hard_fork2(
        constants=constants,
        blocks=block_cache,
        prev_b_hash=candidate_block.header_hash,
        sp_index=candidate_block.reward_chain_block.signage_point_index,
        finished_sub_slots=1,
    )
    assert not post_hard_fork2(
        constants=constants,
        blocks=block_cache,
        prev_b_hash=candidate_block.header_hash,
        sp_index=candidate_block.reward_chain_block.signage_point_index,
        finished_sub_slots=0,
    )


def test_post_hard_fork2_matches_real_chain_cutoff(bt: BlockTools) -> None:
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

    block_cache = BlockCache(blocks, BlockchainMMRManager(bt.constants.GENESIS_CHALLENGE))
    at_cutoff = bt.constants.replace(HARD_FORK2_HEIGHT=uint32(latest_tx_before_sp.height))
    above_cutoff = bt.constants.replace(HARD_FORK2_HEIGHT=uint32(latest_tx_before_sp.height + 1))

    assert post_hard_fork2(
        constants=at_cutoff,
        blocks=block_cache,
        prev_b_hash=block.prev_header_hash,
        sp_index=block.reward_chain_block.signage_point_index,
        finished_sub_slots=len(block.finished_sub_slots),
    )
    assert not post_hard_fork2(
        constants=above_cutoff,
        blocks=block_cache,
        prev_b_hash=block.prev_header_hash,
        sp_index=block.reward_chain_block.signage_point_index,
        finished_sub_slots=len(block.finished_sub_slots),
    )


def test_post_hard_fork2_skips_slow_path_outside_fork_window(bt: BlockTools, monkeypatch: pytest.MonkeyPatch) -> None:
    block_list = bt.get_consecutive_blocks(int(bt.constants.SUB_EPOCH_BLOCKS) + 5, guarantee_transaction_block=True)
    _, _, blocks = load_block_list(block_list, bt.constants)
    block_cache = BlockCache(blocks, BlockchainMMRManager(bt.constants.GENESIS_CHALLENGE))

    def fail_if_called(*args: object, **kwargs: object) -> uint32:
        raise AssertionError("pre_sp_tx_block_height() should not be called")

    monkeypatch.setattr(get_block_challenge_module, "pre_sp_tx_block_height", fail_if_called)

    early_block = block_list[1]
    early_prev = block_cache.block_record(early_block.prev_header_hash)
    early_constants = bt.constants.replace(HARD_FORK2_HEIGHT=uint32(early_prev.height + 2))
    assert not post_hard_fork2(
        constants=early_constants,
        blocks=block_cache,
        prev_b_hash=early_block.prev_header_hash,
        sp_index=early_block.reward_chain_block.signage_point_index,
        finished_sub_slots=len(early_block.finished_sub_slots),
    )

    late_block = block_list[-1]
    late_prev = block_cache.block_record(late_block.prev_header_hash)
    late_constants = bt.constants.replace(
        HARD_FORK2_HEIGHT=uint32(late_prev.height - bt.constants.SUB_EPOCH_BLOCKS + 1)
    )
    assert post_hard_fork2(
        constants=late_constants,
        blocks=block_cache,
        prev_b_hash=late_block.prev_header_hash,
        sp_index=late_block.reward_chain_block.signage_point_index,
        finished_sub_slots=len(late_block.finished_sub_slots),
    )


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
