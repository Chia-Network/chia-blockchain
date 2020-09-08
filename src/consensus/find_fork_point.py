from typing import Dict, Any
from src.util.ints import uint32


def find_fork_point_in_chain(hash_to_block: Dict, block_1: Any, block_2: Any) -> uint32:
    """Tries to find height where new chain (block_2) diverged from block_1 (assuming prev blocks
    are all included in chain)"""
    while block_2.height > 0 or block_1.height > 0:
        if block_2.height > block_1.height:
            block_2 = hash_to_block[block_2.prev_header_hash]
        elif block_1.height > block_2.height:
            block_1 = hash_to_block[block_1.prev_header_hash]
        else:
            if block_2.header_hash == block_1.header_hash:
                return block_2.height
            block_2 = hash_to_block[block_2.prev_header_hash]
            block_1 = hash_to_block[block_1.prev_header_hash]
    assert block_2 == block_1  # Genesis block is the same, genesis fork
    return uint32(0)
