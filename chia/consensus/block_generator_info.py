from __future__ import annotations

from chia.types.block_protocol import BlockInfo
from chia.types.blockchain_format.serialized_program import SerializedProgram


def block_has_transactions_generator(block: BlockInfo) -> bool:
    return block.transactions_generator is not None or block.transactions_generator_buffer is not None


def get_transactions_generator_bytes(block: BlockInfo) -> bytes | None:
    if block.transactions_generator is not None:
        return bytes(block.transactions_generator)
    return block.transactions_generator_buffer


def get_transactions_generator_program(block: BlockInfo) -> SerializedProgram | None:
    if block.transactions_generator is not None:
        return block.transactions_generator
    if block.transactions_generator_buffer is not None:
        return SerializedProgram.from_bytes(block.transactions_generator_buffer)
    return None
