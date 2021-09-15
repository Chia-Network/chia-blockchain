from typing import Optional, List

from chia.full_node.bundle_tools import (
    simple_solution_generator,
    bundle_suitable_for_compression,
    detect_potential_template_generator,
    compressed_spend_bundle_solution,
)
from chia.types.block_compressor import BlockCompressorInterface
from chia.types.blockchain_format.program import SerializedProgram
from chia.types.generator_types import BlockGenerator, CompressorArg
from chia.types.spend_bundle import SpendBundle
from chia.util.ints import uint32


class StandardTransactionCompressor(BlockCompressorInterface):
    """
    Find an uncompressed block with `match_block`, then use that as a template to compress future blocks
    containing the "standard transaction" from the default wallet: p2_delegated_puzzle_or_hidden_puzzle
    """

    def do_scan(self) -> bool:
        return True

    def match_block(self, block_height: uint32, program: SerializedProgram) -> Optional[CompressorArg]:
        return detect_potential_template_generator(block_height, program)

    def can_compress(self, expected_output: SpendBundle) -> bool:
        return bundle_suitable_for_compression(expected_output)

    def compress(self, generator_args: List[CompressorArg], bundle: SpendBundle) -> BlockGenerator:
        assert len(generator_args) == 1
        return compressed_spend_bundle_solution(generator_args[0], bundle)
