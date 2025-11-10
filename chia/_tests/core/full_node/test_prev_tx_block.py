from __future__ import annotations

from typing import Optional

from chia_rs import FullBlock
from chia_rs.sized_ints import uint8, uint32

from chia.consensus.get_block_challenge import prev_tx_block
from chia.simulator.block_tools import BlockTools, load_block_list, test_constants
from chia.util.block_cache import BlockCache


def test_prev_tx_block_none() -> None:
    # If prev_b is None, should return 0
    assert prev_tx_block(
        constants=test_constants,
        blocks=BlockCache({}),
        prev_b_hash=test_constants.GENESIS_CHALLENGE,
        sp_index=uint8(0),
        first_in_sub_slot=False,
    ) == uint32(0)
    assert prev_tx_block(
        constants=test_constants,
        blocks=BlockCache({}),
        prev_b_hash=test_constants.GENESIS_CHALLENGE,
        sp_index=uint8(1),
        first_in_sub_slot=True,
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
    latest_tx_before_sp = find_tx_before_sp(block_list)
    assert latest_tx_before_sp is not None
    assert (
        prev_tx_block(
            constants=test_constants,
            blocks=BlockCache(blocks),
            prev_b_hash=block.prev_header_hash,
            sp_index=block.reward_chain_block.signage_point_index,
            first_in_sub_slot=len(block.finished_sub_slots) > 0,
        )
        == latest_tx_before_sp.height
    )
    block = block_list[-2]
    latest_tx_before_sp = find_tx_before_sp(block_list[:-1])
    assert latest_tx_before_sp is not None
    assert (
        prev_tx_block(
            constants=test_constants,
            blocks=BlockCache(blocks),
            prev_b_hash=block.prev_header_hash,
            sp_index=block.reward_chain_block.signage_point_index,
            first_in_sub_slot=len(block.finished_sub_slots) > 0,
        )
        == latest_tx_before_sp.height
    )
    block = block_list[-3]
    latest_tx_before_sp = find_tx_before_sp(block_list[:-2])
    assert latest_tx_before_sp is not None
    assert (
        prev_tx_block(
            constants=test_constants,
            blocks=BlockCache(blocks),
            prev_b_hash=block.prev_header_hash,
            sp_index=block.reward_chain_block.signage_point_index,
            first_in_sub_slot=len(block.finished_sub_slots) > 0,
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
    latest_tx_before_sp = find_tx_before_sp(block_list)
    assert latest_tx_before_sp is not None
    assert prev_tx_block(
        constants=test_constants,
        blocks=BlockCache(blocks),
        prev_b_hash=block.prev_header_hash,
        sp_index=block.reward_chain_block.signage_point_index,
        first_in_sub_slot=len(block.finished_sub_slots) > 0,
    ) == uint32(latest_tx_before_sp.height)


# get the latest infused transaction block before the signage point of the last block in the list
def find_tx_before_sp(block_list: list[FullBlock]) -> Optional[FullBlock]:
    before_slot = False
    before_sp = False
    if len(block_list[-1].finished_sub_slots) > 0:
        before_slot = True
    sp_index = block_list[-1].reward_chain_block.signage_point_index
    idx = len(block_list) - 2
    curr = None
    while idx > 0:
        curr = block_list[idx]
        if curr.reward_chain_block.signage_point_index < sp_index:
            before_sp = True
        if curr.foliage_transaction_block is not None and (before_slot or before_sp):
            break
        if len(curr.finished_sub_slots) > 0:
            before_slot = True
        idx -= 1
    return curr
