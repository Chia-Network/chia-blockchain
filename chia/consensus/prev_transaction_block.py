from __future__ import annotations

from chia_rs import BlockRecord
from chia_rs.sized_ints import uint128

from chia.consensus.blockchain_interface import BlockRecordsProtocol


def get_prev_transaction_block(
    curr: BlockRecord,
    blocks: BlockRecordsProtocol,
    total_iters_sp: uint128,
) -> tuple[bool, BlockRecord]:
    while not curr.is_transaction_block:
        curr = blocks.block_record(curr.prev_hash)
    is_transaction_block = total_iters_sp > curr.total_iters
    return is_transaction_block, curr
