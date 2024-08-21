from __future__ import annotations

from typing import Awaitable, Callable, Dict, Optional, Set

from chia.types.block_protocol import BlockInfo
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.generator_types import BlockGenerator
from chia.util.ints import uint32


async def get_block_generator(
    lookup_block_generators: Callable[[bytes32, Set[uint32]], Awaitable[Dict[uint32, bytes]]],
    block: BlockInfo,
) -> Optional[BlockGenerator]:
    ref_list = block.transactions_generator_ref_list
    if block.transactions_generator is None:
        assert len(ref_list) == 0
        return None
    if len(ref_list) == 0:
        return BlockGenerator(block.transactions_generator, [])

    generator_refs = set(ref_list)
    generators: Dict[uint32, bytes] = await lookup_block_generators(block.prev_header_hash, generator_refs)

    result = [generators[height] for height in block.transactions_generator_ref_list]
    return BlockGenerator(block.transactions_generator, result)
