from __future__ import annotations

from collections.abc import Awaitable
from typing import Callable, Optional

from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint32

from chia.types.block_protocol import BlockInfo
from chia.types.generator_types import BlockGenerator


async def get_block_generator(
    lookup_block_generators: Callable[[bytes32, set[uint32]], Awaitable[dict[uint32, bytes]]],
    block: BlockInfo,
) -> Optional[BlockGenerator]:
    ref_list = block.transactions_generator_ref_list
    if block.transactions_generator is None:
        assert len(ref_list) == 0
        return None
    if len(ref_list) == 0:
        return BlockGenerator(block.transactions_generator, [])

    generator_refs = set(ref_list)
    generators: dict[uint32, bytes] = await lookup_block_generators(block.prev_header_hash, generator_refs)

    result = [generators[height] for height in block.transactions_generator_ref_list]
    return BlockGenerator(block.transactions_generator, result)
