from __future__ import annotations

import logging
from typing import List, Optional, Union

from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.serialized_program import SerializedProgram
from chia.types.generator_types import BlockGenerator, CompressorArg, GeneratorBlockCacheInterface
from chia.util.ints import uint32
from chia.wallet.puzzles.load_clvm import load_clvm_maybe_recompile

DECOMPRESS_BLOCK = load_clvm_maybe_recompile("block_program_zero.clsp", package_or_requirement="chia.wallet.puzzles")
DECOMPRESS_PUZZLE = load_clvm_maybe_recompile("decompress_puzzle.clsp", package_or_requirement="chia.wallet.puzzles")
# DECOMPRESS_CSE = load_clvm_maybe_recompile(
#     "decompress_coin_spend_entry.clsp",
#     package_or_requirement="chia.wallet.puzzles",
# )

DECOMPRESS_CSE_WITH_PREFIX = load_clvm_maybe_recompile(
    "decompress_coin_spend_entry_with_prefix.clsp", package_or_requirement="chia.wallet.puzzles"
)
log = logging.getLogger(__name__)


def create_block_generator(
    generator: SerializedProgram, block_heights_list: List[uint32], generator_block_cache: GeneratorBlockCacheInterface
) -> Optional[BlockGenerator]:
    """`create_block_generator` will returns None if it fails to look up any referenced block"""
    generator_list: List[SerializedProgram] = []
    generator_heights: List[uint32] = []
    for i in block_heights_list:
        previous_generator = generator_block_cache.get_generator_for_block_height(i)
        if previous_generator is None:
            log.error(f"Failed to look up generator for block {i}. Ref List: {block_heights_list}")
            return None
        generator_list.append(previous_generator)
        generator_heights.append(i)
    return BlockGenerator(generator, generator_list, generator_heights)


def create_compressed_generator(
    original_generator: CompressorArg,
    compressed_cse_list: List[List[List[Union[bytes, None, int, Program]]]],
) -> BlockGenerator:
    """
    Bind the generator block program template to a particular reference block,
    template bytes offsets, and SpendBundle.
    """
    start = original_generator.start
    end = original_generator.end
    program = DECOMPRESS_BLOCK.curry(
        DECOMPRESS_PUZZLE, DECOMPRESS_CSE_WITH_PREFIX, Program.to(start), Program.to(end), compressed_cse_list
    )
    return BlockGenerator(program, [original_generator.generator], [original_generator.block_height])
