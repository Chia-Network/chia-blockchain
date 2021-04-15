import re
from typing import Optional, Tuple

from clvm import SExp
from clvm_tools import binutils

from chia.types.blockchain_format.program import SerializedProgram
from chia.types.generator_types import BlockGenerator, GeneratorArg
from chia.types.spend_bundle import SpendBundle
from chia.util.byte_types import hexstr_to_bytes


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


STANDARD_TRANSACTION_PUZZLE_PATTERN = re.compile(
    r"""ff02ffff01ff02ffff01ff02ffff03ff0bffff01ff02ffff03ffff09ff05ffff1dff0bffff1effff0bff0bffff02ff06ffff04ff02ffff04ff17ff8080808080808080ffff01ff02ff17ff2f80ffff01ff088080ff0180ffff01ff04ffff04ff04ffff04ff05ffff04ffff02ff06ffff04ff02ffff04ff17ff80808080ff80808080ffff02ff17ff2f808080ff0180ffff04ffff01ff32ff02ffff03ffff07ff0580ffff01ff0bffff0102ffff02ff06ffff04ff02ffff04ff09ff80808080ffff02ff06ffff04ff02ffff04ff0dff8080808080ffff01ff0bffff0101ff058080ff0180ff018080ffff04ffff01(b0[a-f0-9]{96})ff018080"""  # noqa
)


# match_standard_transaction_anywhere
def _match_standard_transaction_at_any_index(generator_body: bytes) -> Optional[Tuple[int, int]]:
    "Return (start, end) of match, or None if pattern could not be found"
    m = STANDARD_TRANSACTION_PUZZLE_PATTERN.search(generator_body.hex())
    if m:
        assert m.start() % 2 == 0 and m.end() % 2 == 0
        return (m.start() // 2, m.end() // 2)
    else:
        return None


def _match_standard_transaction_exactly_and_return_pubkey(transaction: bytes) -> Optional[bytes]:
    m = STANDARD_TRANSACTION_PUZZLE_PATTERN.fullmatch(transaction.hex())
    return None if m is None else hexstr_to_bytes(m.group(1))


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
    return _match_standard_transaction_at_any_index(bytes(generator)) is not None
