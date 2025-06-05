from __future__ import annotations

from chia_rs.sized_ints import uint32

from chia.consensus.generator_tools import get_block_header
from chia.consensus.get_block_challenge import prev_tx_block
from chia.simulator.block_tools import BlockTools, load_block_list
from chia.util.block_cache import BlockCache


def test_prev_tx_block_none() -> None:
    # If prev_b is None, should return 0
    assert prev_tx_block(BlockCache({}), None) == uint32(0)


def test_prev_tx_block_blockrecord_tx(bt: BlockTools) -> None:
    # If prev_b is BlockRecord and prev_transaction_block_hash is not None, return its height
    block_list = bt.get_consecutive_blocks(
        10,
        block_list_input=[],
        guarantee_transaction_block=True,
    )
    _, _, blocks = load_block_list(block_list, bt.constants)
    assert prev_tx_block(BlockCache(blocks), block_list[-1]) == uint32(9)
    assert prev_tx_block(BlockCache(blocks), blocks[block_list[-1].header_hash]) == uint32(9)
    assert prev_tx_block(BlockCache(blocks), get_block_header(block_list[-1])) == uint32(9)


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
    assert prev_tx_block(BlockCache(blocks), block_list[-1]) == uint32(7)
    assert prev_tx_block(BlockCache(blocks), blocks[block_list[-1].header_hash]) == uint32(7)
    assert prev_tx_block(BlockCache(blocks), get_block_header(block_list[-1])) == uint32(7)
