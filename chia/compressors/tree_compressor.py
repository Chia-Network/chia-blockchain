from typing import Optional, List

from block_compression import compress_generator

from chia.full_node.bundle_tools import spend_bundle_to_coin_spend_entry_list
from chia.types.block_compressor import BlockCompressorInterface
from chia.types.blockchain_format.program import SerializedProgram
from chia.types.generator_types import BlockGenerator, CompressorArg
from chia.types.spend_bundle import SpendBundle
from chia.util.ints import uint32


class TreeCompressor(BlockCompressorInterface):
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
        output = spend_bundle_to_coin_spend_entry_list(bundle)
        new_program = compress_generator(output)
        return BlockGenerator(SerializedProgram.from_bytes(new_program), [])
