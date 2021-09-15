from typing import Optional, List

from chia.full_node.bundle_tools import simple_solution_generator
from chia.types.block_compressor import BlockCompressorInterface
from chia.types.blockchain_format.program import SerializedProgram
from chia.types.generator_types import BlockGenerator, CompressorArg
from chia.types.spend_bundle import SpendBundle
from chia.util.ints import uint32


class SimpleCompressor(BlockCompressorInterface):
    """
    Simply quotes the desired output program
    """

    def do_scan(self) -> bool:
        return False

    def match_block(self, block_height: uint32, program: SerializedProgram) -> Optional[CompressorArg]:
        return None

    def can_compress(self, expected_output: SpendBundle) -> bool:
        return True

    def compress(self, generator_args: List[CompressorArg], bundle: SpendBundle) -> BlockGenerator:
        assert len(generator_args) == 0
        return simple_solution_generator(bundle)
