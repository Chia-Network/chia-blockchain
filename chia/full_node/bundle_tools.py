from clvm import SExp
from clvm_tools import binutils

from chia.types.blockchain_format.program import SerializedProgram
from chia.types.generator_types import BlockGenerator, GeneratorArg
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


def best_solution_generator_from_template(bundle: SpendBundle, previous_generator: GeneratorArg) -> BlockGenerator:
    """
    Creates a compressed block generator, taking in a block that passes the checks below
    """
    # TODO: (adam): Implement this with actual compression.
    return simple_solution_program(bundle)


def detect_potential_template_generator(generator: SerializedProgram) -> bool:
    """
    If returns True, that means that generator has a standard transaction that is not compressed that we can use
    as a template for future blocks. This block will be compressed with the above code.
    """
    # TODO: (adam): Implement this with actual compression
    return False
