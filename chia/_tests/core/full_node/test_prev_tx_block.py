from __future__ import annotations

from chia_rs import ConsensusConstants, FullBlock
from chia_rs.sized_ints import uint8, uint32

from chia.consensus.get_block_challenge import post_hard_fork2, pre_sp_tx_block_height
from chia.consensus.pot_iterations import is_overflow_block
from chia.simulator.block_tools import BlockTools, load_block_list, test_constants
from chia.util.block_cache import BlockCache


def test_prev_tx_block_none() -> None:
    # If prev_b is None, should return 0
    assert pre_sp_tx_block_height(
        constants=test_constants,
        blocks=BlockCache({}, test_constants.GENESIS_CHALLENGE),
        prev_b_hash=test_constants.GENESIS_CHALLENGE,
        sp_index=uint8(0),
        finished_sub_slots=0,
    ) == uint32(0)
    assert pre_sp_tx_block_height(
        constants=test_constants,
        blocks=BlockCache({}, test_constants.GENESIS_CHALLENGE),
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
            blocks=BlockCache(blocks, bt.constants.GENESIS_CHALLENGE),
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
            blocks=BlockCache(blocks, bt.constants.GENESIS_CHALLENGE),
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
            blocks=BlockCache(blocks, bt.constants.GENESIS_CHALLENGE),
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
        blocks=BlockCache(blocks, bt.constants.GENESIS_CHALLENGE),
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
    block_cache = BlockCache(blocks, bt.constants.GENESIS_CHALLENGE)

    for block in reversed(overflow_blocks):
        sp_index = block.reward_chain_block.signage_point_index
        assert is_overflow_block(bt.constants, sp_index)

        actual_height = pre_sp_tx_block_height(
            constants=bt.constants,
            blocks=block_cache,
            prev_b_hash=block.header_hash,
            sp_index=sp_index,
            finished_sub_slots=2,
        )
        reduced_height = pre_sp_tx_block_height(
            constants=bt.constants,
            blocks=block_cache,
            prev_b_hash=block.header_hash,
            sp_index=sp_index,
            finished_sub_slots=1,
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
        finished_sub_slots=2,
    )
    assert not post_hard_fork2(
        constants=constants,
        blocks=block_cache,
        prev_b_hash=candidate_block.header_hash,
        sp_index=candidate_block.reward_chain_block.signage_point_index,
        finished_sub_slots=1,
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

    block_cache = BlockCache(blocks, bt.constants.GENESIS_CHALLENGE)
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


# get the latest infused transaction block before the signage point of the last block in the list
def find_tx_before_sp(block_list: list[FullBlock], constants: ConsensusConstants) -> FullBlock | None:
    sp_index = block_list[-1].reward_chain_block.signage_point_index
    overflow = is_overflow_block(constants, sp_index)
    slots_crossed = len(block_list[-1].finished_sub_slots)
    idx = len(block_list) - 2
    curr = None
    while idx > 0:
        curr = block_list[idx]
        if not overflow:
            before_sp = curr.reward_chain_block.signage_point_index < sp_index or slots_crossed > 0
        else:
            before_sp = slots_crossed >= 2 or (
                slots_crossed == 1 and curr.reward_chain_block.signage_point_index < sp_index
            )
        if curr.foliage_transaction_block is not None and before_sp:
            break

        if len(curr.finished_sub_slots) > 0:
            slots_crossed += 1
        idx -= 1

    return curr
