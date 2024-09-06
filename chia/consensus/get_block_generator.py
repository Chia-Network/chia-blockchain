from __future__ import annotations

from typing import Awaitable, Callable, Dict, Optional, Set

from chia.types.block_protocol import BlockInfo
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.full_block import FullBlock
from chia.types.generator_types import BlockGenerator
from chia.util.errors import Err
from chia.util.ints import uint32


async def get_block_generator(
    lookup_block_generators: Callable[[bytes32, Set[uint32]], Awaitable[Dict[uint32, bytes]]],
    block: BlockInfo,
    additional_blocks: Optional[Dict[bytes32, FullBlock]] = None,
) -> Optional[BlockGenerator]:
    if additional_blocks is None:
        additional_blocks = {}
    ref_list = block.transactions_generator_ref_list
    if block.transactions_generator is None:
        assert len(ref_list) == 0
        return None
    if len(ref_list) == 0:
        return BlockGenerator(block.transactions_generator, [])

    generator_refs = set(ref_list)

    # The block heights in the transactions_generator_ref_list don't
    # necessarily refer to the main chain. The generators may be found in 3
    # different places. The additional blocks, a fork of the chain (but in
    # the database) or in the main chain.
    # we'll look through the additional blocks in this function, and then be
    # done with them.

    #              * <- block
    # additional : |
    #              * <- peak of fork (i.e. we have not
    #              | :  validated blocks past this height)
    #              | :
    # peak -> *    | : reorg_chain
    #          \   / :
    #           \ /  :
    #            *  <- fork point
    #         :  |
    #  main   :  |
    #  chain  :  |
    #         :  |
    #         :  * <- genesis

    generators: Dict[uint32, bytes] = {}

    # traverse the additional blocks (if any) and resolve heights into
    # generators
    curr = block
    to_remove = []
    while curr.prev_header_hash in additional_blocks:
        prev: FullBlock = additional_blocks[curr.prev_header_hash]
        if prev.height in generator_refs:
            if prev.transactions_generator is None:
                raise ValueError(Err.GENERATOR_REF_HAS_NO_GENERATOR)
            generators[prev.height] = bytes(prev.transactions_generator)
            to_remove.append(prev.height)
        curr = prev
    for i in to_remove:
        generator_refs.remove(i)

    if len(generator_refs) > 0:
        generators.update(await lookup_block_generators(curr.prev_header_hash, generator_refs))

    result = [generators[height] for height in block.transactions_generator_ref_list]
    return BlockGenerator(block.transactions_generator, result)
