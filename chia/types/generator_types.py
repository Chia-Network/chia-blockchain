from dataclasses import dataclass
from typing import List
from chia.types.blockchain_format.program import SerializedProgram
from chia.util.ints import uint32
from chia.util.streamable import Streamable, streamable


class GeneratorBlockCacheInterface:
    def get_generator_for_block_height(self, height: uint32) -> SerializedProgram:
        # Requested block must be a transaction block
        pass


@dataclass(frozen=True)
@streamable
class GeneratorArg(Streamable):
    """`GeneratorArg` contains data from already-buried blocks in the blockchain"""

    block_height: uint32
    generator: SerializedProgram


@dataclass(frozen=True)
@streamable
class CompressorArg(Streamable):
    """`CompressorArg` is used as input to the Block Compressor"""

    block_height: uint32
    generator: SerializedProgram
    start: int
    end: int


@dataclass(frozen=True)
@streamable
class BlockGenerator(Streamable):
    program: SerializedProgram
    generator_args: List[GeneratorArg]

    def block_height_list(self) -> List[uint32]:
        return [a.block_height for a in self.generator_args]

    def generator_refs(self) -> List[SerializedProgram]:
        return [a.generator for a in self.generator_args]
