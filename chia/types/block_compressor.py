from typing import Optional, List

from chia.types.blockchain_format.program import SerializedProgram
from chia.types.generator_types import CompressorArg, BlockGenerator
from chia.types.spend_bundle import SpendBundle
from chia.util.ints import uint32


class BlockCompressorInterface:
    """
    Implement this interface to be loaded as a candidate block compressor when a block is farmed.
    Interface limitation: This interface is not suitable to scan for multiple `generator_args`
    @richardkiss: could change do_scan to scan_until() -> int, returning number of args to scan for?
    """

    def do_scan(self) -> bool:
        """
        Return True if this compressor requests a scan for input blocks at startup.
        A True return implies that generator reference arguments len > 0
        """
        pass

    def match_block(self, block_height: uint32, program: SerializedProgram) -> Optional[CompressorArg]:
        """
        Return a CompressorArg context object if this block is suitable
        as an input block to compress future blocks with this compressor.
        """
        pass

    # def can_compress(self, expected_output: SerializedProgram) -> bool:
    def can_compress(self, expected_output: SpendBundle) -> bool:
        """
        Return True if this compressor can compress expected_output
        """
        pass

    # def compress(self, expected_output: SerializedProgram) -> SerializedProgram:
    # def compress(self, bundle: SpendBundle) -> BlockGenerator:
    def compress(self, generator_args: List[CompressorArg], bundle: SpendBundle) -> BlockGenerator:
        """
        Return a program that produces expected_output when run.
        """
        pass
