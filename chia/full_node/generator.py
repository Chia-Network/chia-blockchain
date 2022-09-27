import logging
from typing import List, Optional, Union, Tuple
from chia.types.blockchain_format.program import Program, SerializedProgram
from chia.types.generator_types import BlockGenerator, GeneratorBlockCacheInterface, CompressorArg
from chia.util.ints import uint32
from chia.wallet.puzzles.load_clvm import load_clvm_maybe_recompile
from chia.wallet.puzzles.rom_bootstrap_generator import get_generator

GENERATOR_MOD = get_generator()

DECOMPRESS_BLOCK = load_clvm_maybe_recompile("block_program_zero.clvm", package_or_requirement="chia.wallet.puzzles")
DECOMPRESS_PUZZLE = load_clvm_maybe_recompile("decompress_puzzle.clvm", package_or_requirement="chia.wallet.puzzles")
# DECOMPRESS_CSE = load_clvm_maybe_recompile(
#     "decompress_coin_spend_entry.clvm",
#     package_or_requirement="chia.wallet.puzzles",
# )

DECOMPRESS_CSE_WITH_PREFIX = load_clvm_maybe_recompile(
    "decompress_coin_spend_entry_with_prefix.clvm", package_or_requirement="chia.wallet.puzzles"
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


def create_generator_args(generator_ref_list: List[SerializedProgram]) -> Program:
    """
    `create_generator_args`: The format and contents of these arguments affect consensus.
    """
    gen_ref_list = [bytes(g) for g in generator_ref_list]
    ret: Program = Program.to([gen_ref_list])
    return ret


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


def setup_generator_args(self: BlockGenerator) -> Tuple[SerializedProgram, Program]:
    args = create_generator_args(self.generator_refs)
    return self.program, args


def run_generator_mempool(self: BlockGenerator, max_cost: int) -> Tuple[int, SerializedProgram]:
    program, args = setup_generator_args(self)
    return GENERATOR_MOD.run_mempool_with_cost(max_cost, program, args)


def run_generator_unsafe(self: BlockGenerator, max_cost: int) -> Tuple[int, SerializedProgram]:
    """This mode is meant for accepting possibly soft-forked transactions into the mempool"""
    program, args = setup_generator_args(self)
    return GENERATOR_MOD.run_with_cost(max_cost, program, args)
