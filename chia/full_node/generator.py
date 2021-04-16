import logging
from typing import List, Optional, Union, Tuple
from chia.types.blockchain_format.program import Program, SerializedProgram, NIL
from chia.types.generator_types import BlockGenerator, GeneratorArg, GeneratorBlockCacheInterface
from chia.util.ints import uint32, uint64
from chia.wallet.puzzles.load_clvm import load_clvm
from chia.wallet.puzzles.lowlevel_generator import get_generator

GENERATOR_MOD = get_generator()

DESERIALIZE_MOD = load_clvm("chialisp_deserialisation.clvm", package_or_requirement="chia.wallet.puzzles")
DECOMPRESS_BLOCK = load_clvm("block_program_zero.clvm", package_or_requirement="chia.wallet.puzzles")
DECOMPRESS_PUZZLE = load_clvm("decompress_puzzle.clvm", package_or_requirement="chia.wallet.puzzles")
# DECOMPRESS_CSE = load_clvm("decompress_coin_solution_entry.clvm", package_or_requirement="chia.wallet.puzzles")

DECOMPRESS_CSE_WITH_PREFIX = load_clvm(
    "decompress_coin_solution_entry_with_prefix.clvm", package_or_requirement="chia.wallet.puzzles"
)
log = logging.getLogger(__name__)


def create_block_generator(
    generator: SerializedProgram,
    block_heights_list: List[uint32],
    generator_block_cache: GeneratorBlockCacheInterface,
    start,
    end,
) -> Optional[BlockGenerator]:
    """ `create_block_generator` will returns None if it fails to look up any referenced block """
    generator_arg_list: List[GeneratorArg] = []
    for i in block_heights_list:
        previous_generator = generator_block_cache.get_generator_for_block_height(i)
        if previous_generator is None:
            log.error(f"Failed to look up generator for block {i}. Ref List: {block_heights_list}")
            return None
        generator_arg_list.append(GeneratorArg(i, previous_generator, start, end))
    return BlockGenerator(generator, generator_arg_list)


def create_generator_args(generator_ref_list: List[SerializedProgram]) -> SerializedProgram:
    """
    `create_generator_args`: The format and contents of these arguments affect consensus.
    """
    gen_ref_list = [bytes(g) for g in generator_ref_list]
    return SerializedProgram.from_bytes(bytes(Program.to([DESERIALIZE_MOD, gen_ref_list])))


def create_compressed_generator(
    original_generator: GeneratorArg,
    compressed_cse_list: List[List[Union[List[uint64], List[Union[bytes, None, Program]]]]],
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
    return BlockGenerator(program, [original_generator])


def setup_generator_args(self: BlockGenerator):
    if not self.generator_args:
        args = NIL
    else:
        args = Program.from_bytes(bytes(create_generator_args(self.generator_refs())))
    return self.program, args


def run_generator(self: BlockGenerator) -> Tuple[int, SerializedProgram]:
    program, args = setup_generator_args(self)
    return GENERATOR_MOD.run_safe_with_cost(program, args)


def run_generator_unsafe(self: BlockGenerator) -> Tuple[int, SerializedProgram]:
    """This mode is meant for accepting possibly soft-forked transactions into the mempool"""
    program, args = setup_generator_args(self)
    return GENERATOR_MOD.run_with_cost(program, args)
