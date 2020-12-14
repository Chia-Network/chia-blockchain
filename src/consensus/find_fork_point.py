from typing import Dict, Union

from src.consensus.sub_block_record import SubBlockRecord
from src.types.header_block import HeaderBlock


def find_fork_point_in_chain(
    hash_to_block: Dict,
    sub_block_1: Union[SubBlockRecord, HeaderBlock],
    sub_block_2: Union[SubBlockRecord, HeaderBlock],
) -> int:
    """Tries to find height where new chain (sub_block_2) diverged from sub_block_1 (assuming prev blocks
    are all included in chain)
    Returns -1 if chains have no common ancestor
    """
    while sub_block_2.sub_block_height > 0 or sub_block_1.sub_block_height > 0:
        if sub_block_2.sub_block_height > sub_block_1.sub_block_height:
            sub_block_2 = hash_to_block[sub_block_2.prev_hash]
        elif sub_block_1.sub_block_height > sub_block_2.sub_block_height:
            sub_block_1 = hash_to_block[sub_block_1.prev_hash]
        else:
            if sub_block_2.header_hash == sub_block_1.header_hash:
                return sub_block_2.sub_block_height
            sub_block_2 = hash_to_block[sub_block_2.prev_hash]
            sub_block_1 = hash_to_block[sub_block_1.prev_hash]
    if sub_block_2 != sub_block_1:
        # All blocks are different
        return -1

    # First block is the same
    return 0
