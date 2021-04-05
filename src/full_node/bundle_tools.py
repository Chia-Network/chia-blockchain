from clvm import SExp
from clvm_tools import binutils

from chia.types.blockchain_format.program import SerializedProgram
from chia.types.spend_bundle import SpendBundle


def best_solution_program(bundle: SpendBundle) -> SerializedProgram:
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
    return SerializedProgram.from_bytes(SExp.to((binutils.assemble("#q"), r)).as_bin())
