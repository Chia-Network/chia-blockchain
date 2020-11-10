from typing import Dict

from src.full_node.sub_block_record import SubBlockRecord
from src.types.sized_bytes import bytes32
from src.util.ints import uint128


def get_prev_block(
    curr: SubBlockRecord, prev_block: SubBlockRecord, sub_blocks: Dict[bytes32, SubBlockRecord], total_iters_sp: uint128
) -> (bool, SubBlockRecord):
    while not curr.is_block:
        curr = sub_blocks[curr.prev_hash]
    if total_iters_sp > curr.total_iters:
        prev_block = curr
        is_block = True
    else:
        is_block = False
    return is_block, prev_block
