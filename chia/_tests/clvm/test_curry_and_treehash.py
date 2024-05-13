from __future__ import annotations

from typing import List

import pytest

from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.wallet.puzzles import p2_delegated_puzzle_or_hidden_puzzle  # import (puzzle_for_pk, puzzle_hash_for_pk, MOD)
from chia.wallet.util.curry_and_treehash import (
    calculate_hash_of_quoted_mod_hash,
    curry_and_treehash,
    shatree_atom,
    shatree_atom_list,
    shatree_int,
)


def test_curry_and_treehash() -> None:
    arbitrary_mod = p2_delegated_puzzle_or_hidden_puzzle.MOD
    arbitrary_mod_hash = arbitrary_mod.get_tree_hash()

    # we don't really care what `arbitrary_mod` is. We just need some code

    quoted_mod_hash = calculate_hash_of_quoted_mod_hash(arbitrary_mod_hash)

    for v in range(500):
        args = [v, v * v, v * v * v]
        # we don't really care about the arguments either
        puzzle = arbitrary_mod.curry(*args)
        puzzle_hash_via_curry = puzzle.get_tree_hash()
        hashed_args = [Program.to(_).get_tree_hash() for _ in args]
        puzzle_hash_via_f = curry_and_treehash(quoted_mod_hash, *hashed_args)
        assert puzzle_hash_via_curry == puzzle_hash_via_f


@pytest.mark.parametrize(
    "value", [[], [bytes32([3] * 32)], [bytes32([0] * 32), bytes32([1] * 32)], [bytes([1]), bytes([1, 2, 3])]]
)
def test_shatree_atom_list(value: List[bytes]) -> None:
    h1 = shatree_atom_list(value)
    h2 = Program.to(value).get_tree_hash()
    assert h1 == h2


@pytest.mark.parametrize("value", [0, -1, 1, 0x7F, 0x80, 100000000, -10000000])
def test_shatree_int(value: int) -> None:
    h1 = shatree_int(value)
    h2 = Program.to(value).get_tree_hash()
    assert h1 == h2


@pytest.mark.parametrize("value", [bytes([1] * 1), bytes([]), bytes([5] * 1000)])
def test_shatree_atom(value: bytes) -> None:
    h1 = shatree_atom(value)
    h2 = Program.to(value).get_tree_hash()
    assert h1 == h2
