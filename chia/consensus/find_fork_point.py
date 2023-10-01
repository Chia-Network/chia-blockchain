from __future__ import annotations

from typing import Optional, Union

from chia.consensus.block_record import BlockRecord
from chia.consensus.blockchain_interface import BlockchainInterface
from chia.types.header_block import HeaderBlock


def unwrap(block: Optional[BlockRecord]) -> BlockRecord:
    if block is None:
        raise KeyError("missing block in chain")
    return block


async def find_fork_point_in_chain(
    blocks: BlockchainInterface,
    block_1: Union[BlockRecord, HeaderBlock],
    block_2: Union[BlockRecord, HeaderBlock],
) -> int:
    """Tries to find height where new chain (block_2) diverged from block_1 (assuming prev blocks
    are all included in chain)
    Returns -1 if chains have no common ancestor
    * assumes the fork point is loaded in blocks
    """
    height_1 = int(block_1.height)
    height_2 = int(block_2.height)
    bh_1 = block_1.header_hash
    bh_2 = block_2.header_hash

    # special case for first level, since we actually already know the previous
    # hash
    if height_1 > height_2:
        bh_1 = block_1.prev_hash
        height_1 -= 1
    elif height_2 > height_1:
        bh_2 = block_2.prev_hash
        height_2 -= 1

    while height_1 > height_2:
        [bh_1] = await blocks.prev_block_hash([bh_1])
        height_1 -= 1

    while height_2 > height_1:
        [bh_2] = await blocks.prev_block_hash([bh_2])
        height_2 -= 1

    assert height_1 == height_2

    height = height_2
    while height > 0:
        if bh_1 == bh_2:
            return height
        [bh_1, bh_2] = await blocks.prev_block_hash([bh_1, bh_2])
        height -= 1

    if bh_2 != bh_1:
        # All blocks are different
        return -1

    # First block is the same
    return 0
