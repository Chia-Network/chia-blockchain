from chia.types.blockchain_format.program import SerializedProgram
from chia.wallet.puzzles.load_clvm import load_clvm

uncurried_puzzle = load_clvm("decompress_block_spends.clvm", package_or_requirement=__name__)
deserialization_puzzle = load_clvm("chialisp_deserialisation.clvm", package_or_requirement=__name__)

DECOMPRESS_BLOCK_SPENDS = SerializedProgram.from_program(uncurried_puzzle.curry(deserialization_puzzle))
