from __future__ import annotations

from typing import Dict, Tuple, Union

from chia.consensus.block_record import BlockRecord
from chia.consensus.blockchain_interface import BlockRecordsProtocol
from chia.consensus.constants import ConsensusConstants
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.header_block import HeaderBlock
from chia.util.ints import uint32


async def find_fork_point_in_chain(
    blocks: BlockRecordsProtocol,
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


async def lookup_fork_chain(
    blocks: BlockRecordsProtocol,
    block_1: Tuple[int, bytes32],
    block_2: Tuple[int, bytes32],
    constants: ConsensusConstants,
) -> Tuple[Dict[uint32, bytes32], bytes32]:
    """
    Tries to find height where new chain (block_2) diverged from block_1.
    The inputs are (height, header-hash)-tuples.
    Returns two values:
        1. The height to hash map of block_2's chain down to, but not
           including, the fork height
        2. The header hash of the block at the fork height
    Note that height -1 is valid. There is never a block at that height, but
    there is a block hash (GENESIS_CHALLENGE).
    We never include the fork point in the returned height to hash map, so its
    key is unsigned
    """
    height_1 = block_1[0]
    bh_1 = block_1[1]
    height_2 = block_2[0]
    bh_2 = block_2[1]

    ret: Dict[uint32, bytes32] = {}

    while height_1 > height_2:
        [bh_1] = await blocks.prev_block_hash([bh_1])
        height_1 -= 1

    while height_2 > height_1:
        ret[uint32(height_2)] = bh_2
        [bh_2] = await blocks.prev_block_hash([bh_2])
        height_2 -= 1

    assert height_1 == height_2

    height = height_2
    while height > 0:
        if bh_1 == bh_2:
            return (ret, bh_2)
        ret[uint32(height)] = bh_2
        [bh_1, bh_2] = await blocks.prev_block_hash([bh_1, bh_2])
        height -= 1

    if bh_1 == bh_2:
        return (ret, bh_2)

    # this means the fork point is -1, and its hash is the GENESIS_CHALLENGE
    ret[uint32(0)] = bh_2
    return (ret, constants.GENESIS_CHALLENGE)
