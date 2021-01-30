from typing import Tuple

from src.consensus.blockchain_interface import BlockchainInterface
from src.consensus.sub_block_record import SubBlockRecord
from src.util.ints import uint128


def get_prev_block(
    curr: SubBlockRecord,
    sub_blocks: BlockchainInterface,
    total_iters_sp: uint128,
) -> Tuple[bool, SubBlockRecord]:
    prev_block = curr
    while not curr.is_block:
        curr = sub_blocks.sub_block_record(curr.prev_hash)
    if total_iters_sp > curr.total_iters:
        prev_block = curr
        is_block = True
    else:
        is_block = False
    return is_block, prev_block
