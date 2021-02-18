from clvm_tools import binutils
from clvm import SExp

from src.types.blockchain_format.program import SerializedProgram
from src.types.spend_bundle import SpendBundle


def best_solution_program(bundle: SpendBundle) -> SerializedProgram:
    """
    This could potentially do a lot of clever and complicated compression
    optimizations in conjunction with choosing the set of SpendBundles to include.

    For now, we just quote the solutions we know.
    """
    r = []
    for coin_solution in bundle.coin_solutions:
        entry = [coin_solution.coin.name(), coin_solution.solution]
        r.append(entry)
    return SerializedProgram.from_bytes(SExp.to((binutils.assemble("#q"), r)).as_bin())
