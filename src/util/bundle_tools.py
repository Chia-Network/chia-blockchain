from clvm_tools import binutils

from src.types.hashable.Program import Program
from src.types.hashable.SpendBundle import SpendBundle


def best_solution_program(bundle: SpendBundle) -> Program:
    """
    This could potentially do a lot of clever and complicated compression
    optimizations in conjunction with choosing the set of SpendBundles to include.

    For now, we just quote the solutions we know.
    """
    r = []
    for coin_solution in bundle.coin_solutions:
        entry = [coin_solution.coin.name(), coin_solution.solution]
        r.append(entry)
    return Program.to([binutils.assemble("#q"), r])
