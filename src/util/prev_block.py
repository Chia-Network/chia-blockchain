from typing import Dict, Tuple

from src.consensus.sub_block_record import SubBlockRecord
from src.types.sized_bytes import bytes32
from src.util.ints import uint128


def get_prev_block(
    curr: SubBlockRecord,
    sub_blocks: Dict[bytes32, SubBlockRecord],
    total_iters_sp: uint128,
) -> Tuple[bool, SubBlockRecord]:
    prev_block = curr
    while not curr.is_block:
        curr = sub_blocks[curr.prev_hash]
    if total_iters_sp > curr.total_iters:
        prev_block = curr
        is_block = True
    else:
        is_block = False
    return is_block, prev_block
