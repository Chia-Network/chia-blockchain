from __future__ import annotations

from unittest import mock

from chia.types.blockchain_format.program import Program
from chia.wallet.puzzles.puzzle_drivers import UnknownPuzzle


def test_unknown_puzzle() -> None:
    no_curry = Program.to("this is a program without curried params")
    unknown_puz = UnknownPuzzle(no_curry)
    assert unknown_puz.mod is None
    assert unknown_puz.curried_args is None
    assert unknown_puz.puzzle_hash == no_curry.get_tree_hash()

    with mock.patch.object(Program, "get_tree_hash") as tree_hash_patched:
        unknown_puz.puzzle_hash
        assert tree_hash_patched.call_count == 0
