from __future__ import annotations

from typing import Union

from chia.consensus.block_record import BlockRecord
from chia.consensus.blockchain_interface import BlockchainInterface
from chia.types.header_block import HeaderBlock


def find_fork_point_in_chain(
    blocks: BlockchainInterface,
    block_1: Union[BlockRecord, HeaderBlock],
    block_2: Union[BlockRecord, HeaderBlock],
) -> int:
    """Tries to find height where new chain (block_2) diverged from block_1 (assuming prev blocks
    are all included in chain)
    Returns -1 if chains have no common ancestor
    * assumes the fork point is loaded in blocks
    """
    while block_2.height > 0 or block_1.height > 0:
        if block_2.height > block_1.height:
            block_2 = blocks.block_record(block_2.prev_hash)
        elif block_1.height > block_2.height:
            block_1 = blocks.block_record(block_1.prev_hash)
        else:
            if block_2.header_hash == block_1.header_hash:
                return block_2.height
            block_2 = blocks.block_record(block_2.prev_hash)
            block_1 = blocks.block_record(block_1.prev_hash)
    if block_2 != block_1:
        # All blocks are different
        return -1

    # First block is the same
    return 0
