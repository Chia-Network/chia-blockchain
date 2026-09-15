from __future__ import annotations

from chia.types.block_protocol import BlockInfo
from chia.types.generator_types import GeneratorFormat


def block_has_transactions_generator(block: BlockInfo) -> bool:
    # these fields are mutually exclusive
    assert block.transactions_generator is None or block.transactions_generator_buffer is None
    return block.transactions_generator is not None or block.transactions_generator_buffer is not None


def get_transactions_generator_bytes(block: BlockInfo) -> bytes | None:
    if block.transactions_generator is not None:
        return bytes(block.transactions_generator)
    return block.transactions_generator_buffer


def get_transactions_generator_format(block: BlockInfo) -> GeneratorFormat | None:
    # these fields are mutually exclusive, same as above
    if block.transactions_generator is not None:
        return GeneratorFormat.CLASSIC
    if block.transactions_generator_buffer is not None:
        return GeneratorFormat.SERDE_2026
    return None
