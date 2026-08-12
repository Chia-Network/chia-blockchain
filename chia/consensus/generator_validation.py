from __future__ import annotations

from chia_rs import ConsensusConstants, FullBlock, UnfinishedBlock
from chia_rs.sized_ints import uint32

from chia.util.errors import Err
from chia.util.hash import std_hash


def validate_generator_ref_list(
    constants: ConsensusConstants,
    block: FullBlock | UnfinishedBlock,
    height: uint32,
    prev_transaction_block_height: uint32,
) -> Err | None:
    assert block.transactions_info is not None

    generator_refs = block.transactions_generator_ref_list
    if not generator_refs:
        if block.transactions_info.generator_refs_root != bytes([1] * 32):
            return Err.INVALID_TRANSACTIONS_GENERATOR_REFS_ROOT
        return None

    if prev_transaction_block_height >= constants.SOFT_FORK9_HEIGHT:
        return Err.TOO_MANY_GENERATOR_REFS
    if block.transactions_generator is None:
        return Err.INVALID_TRANSACTIONS_GENERATOR_REFS_ROOT
    if len(generator_refs) > constants.MAX_GENERATOR_REF_LIST_SIZE:
        return Err.TOO_MANY_GENERATOR_REFS
    generator_refs_hash = std_hash(b"".join(i.stream_to_bytes() for i in generator_refs))
    if block.transactions_info.generator_refs_root != generator_refs_hash:
        return Err.INVALID_TRANSACTIONS_GENERATOR_REFS_ROOT
    if any(index >= height for index in generator_refs):
        return Err.FUTURE_GENERATOR_REFS

    return None
