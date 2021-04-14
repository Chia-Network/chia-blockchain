from dataclasses import dataclass
from typing import List, Tuple

from chia.types.blockchain_format.program import SerializedProgram
from chia.util.ints import uint32

# from chia.util.streamable import Streamable, streamable


class GeneratorBlockCacheInterface:
    def get_generator_for_block_height(self, uint32) -> SerializedProgram:
        # Requested block must be a transaction block
        pass


@dataclass(frozen=True)
class GeneratorArg:
    block_height: uint32
    generator: SerializedProgram


@dataclass(frozen=True)
class BlockGenerator:
    generator: SerializedProgram
    generator_args: List[GeneratorArg]

    def make_generator_args(self) -> SerializedProgram:
        """ `make_generator_args` is consensus-critical """

    def run(self) -> Tuple[int, SerializedProgram]:
        pass
