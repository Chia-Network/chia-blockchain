from typing import Tuple

from src.consensus.blockchain_interface import BlockchainInterface
from src.consensus.block_record import BlockRecord
from src.util.ints import uint128


def get_prev_transaction_block(
    curr: BlockRecord,
    sub_blocks: BlockchainInterface,
    total_iters_sp: uint128,
) -> Tuple[bool, BlockRecord]:
    prev_block = curr
    while not curr.is_transaction_block:
        curr = sub_blocks.sub_block_record(curr.prev_hash)
    if total_iters_sp > curr.total_iters:
        prev_block = curr
        is_transaction_block = True
    else:
        is_transaction_block = False
    return is_transaction_block, prev_block
