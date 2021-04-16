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


def make_generator_args(generator_ref_list: List[SerializedProgram]) -> SerializedProgram:
    """
    `make_generator_args`: The format and contents of these arguments affect consensus.
    """
    gen_ref_list = [Program.from_bytes(bytes(g)) for g in generator_ref_list]
    gen_ref_tree = list_to_tree(gen_ref_list)
    return SerializedProgram.from_bytes(bytes(Program.to([DESERIALIZE_MOD, gen_ref_tree])))


def list_to_tree(items):
    """
    This recursively turns a python list into a minimal depth tree.
    [] => []
    [a] => a (a leaf node)
    [a_1, ..., a_n] => (list_to_tree(B_0), list_to_tree(B_1)) where len(B_0) - len(B_1) is 0 or 1
      and B_0 + B_1 is the original list
    [1, 2, 3, 4] => ((1, 2), (3, 4))
    """
    size = len(items)
    if size == 0:
        return []
    if size == 1:
        return items[0]
    halfway = (size + 1) // 2
    return (list_to_tree(items[:halfway]), list_to_tree(items[halfway:]))
