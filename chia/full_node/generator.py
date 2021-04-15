import logging
from typing import List, Optional
from chia.types.blockchain_format.program import Program, SerializedProgram
from chia.types.generator_types import BlockGenerator, GeneratorArg, GeneratorBlockCacheInterface
from chia.util.ints import uint32
from chia.wallet.puzzles.load_clvm import load_clvm

DESERIALIZE_MOD = load_clvm("chialisp_deserialisation.clvm", package_or_requirement="chia.wallet.puzzles")

log = logging.getLogger(__name__)


def create_block_generator(
    generator: SerializedProgram, block_heights_list: List[uint32], generator_block_cache: GeneratorBlockCacheInterface
) -> Optional[BlockGenerator]:
    """ `create_block_generator` will returns None if it fails to look up any referenced block """
    generator_arg_list: List[GeneratorArg] = []
    for i in block_heights_list:
        previous_generator = generator_block_cache.get_generator_for_block_height(i)
        if previous_generator is None:
            log.error(f"Failed to look up generator for block {i}. Ref List: {block_heights_list}")
            return None
        generator_arg_list.append(GeneratorArg(i, previous_generator))
    return BlockGenerator(generator, generator_arg_list)


def create_generator_args(generator_ref_list: List[SerializedProgram]) -> SerializedProgram:
    """
    `create_generator_args`: The format and contents of these arguments affect consensus.
    """
    gen_ref_list = [Program.from_bytes(bytes(g)) for g in generator_ref_list]
    return SerializedProgram.from_bytes(bytes(Program.to([DESERIALIZE_MOD, gen_ref_list])))
