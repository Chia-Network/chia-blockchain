from clvm import SExp
from clvm_tools import binutils

from chia.types.blockchain_format.program import SerializedProgram
from chia.types.generator_types import BlockGenerator
from chia.types.spend_bundle import SpendBundle


def simple_solution_program(bundle: SpendBundle) -> BlockGenerator:
    """
    This could potentially do a lot of clever and complicated compression
    optimizations in conjunction with choosing the set of SpendBundles to include.

    For now, we just quote the solutions we know.
    """
    r = []
    for coin_solution in bundle.coin_solutions:
        entry = [
            [coin_solution.coin.parent_coin_info, coin_solution.coin.amount],
            [coin_solution.puzzle_reveal, coin_solution.solution],
        ]
        r.append(entry)

    block_program = SerializedProgram.from_bytes(SExp.to((binutils.assemble("#q"), r)).as_bin())
    g = BlockGenerator(block_program, [])
    return g


# TODO: best_solution_program needs the previous generator as an argument
def best_solution_generator(bundle: SpendBundle) -> BlockGenerator:
    return simple_solution_program(bundle)
