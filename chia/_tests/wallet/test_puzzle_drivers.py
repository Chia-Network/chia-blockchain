from __future__ import annotations

from unittest import mock

import pytest
from attr import dataclass
from chia_rs.sized_bytes import bytes32

from chia.types.blockchain_format.program import Program, run
from chia.wallet.conditions import Remark
from chia.wallet.puzzles.puzzle_drivers import (
    ACS_PH,
    NIL_HASH,
    ACSPuzzle,
    ACSSolution,
    NilPuzzle,
    NilSolution,
    P2Conditions,
    PuzzleWithPuzzleHash,
    UnknownPuzzle,
    UnknownSolution,
)


def test_puzzle_with_puzzle_hash() -> None:
    @dataclass
    class SomePuzzleDriverWithoutOptimizedPuzzleHash(PuzzleWithPuzzleHash):
        @property
        def puzzle(self) -> Program:
            return Program.to("cache me")

    @dataclass
    class SomePuzzleDriverWithOptimizedPuzzleHash(PuzzleWithPuzzleHash):
        @property
        def puzzle(self) -> Program:
            return Program.to("unused")

        @property
        def puzzle_hash_optimized(self) -> bytes32:
            return bytes32.zeros

    without_optimized_hash = SomePuzzleDriverWithoutOptimizedPuzzleHash()
    assert without_optimized_hash.puzzle_hash == Program.to("cache me").get_tree_hash()
    with mock.patch.object(Program, "get_tree_hash") as tree_hash_patched:
        # Already cached from the assertion above
        without_optimized_hash.puzzle_hash
        without_optimized_hash.puzzle_hash
        assert tree_hash_patched.call_count == 0

    fresh = SomePuzzleDriverWithoutOptimizedPuzzleHash()
    with mock.patch.object(Program, "get_tree_hash", return_value=bytes32(b"\x01" * 32)) as tree_hash_patched:
        assert fresh.puzzle_hash == bytes32(b"\x01" * 32)
        fresh.puzzle_hash
        assert tree_hash_patched.call_count == 1

    with_optimized_hash = SomePuzzleDriverWithOptimizedPuzzleHash()
    with mock.patch.object(Program, "get_tree_hash") as tree_hash_patched:
        with_optimized_hash.puzzle_hash
        with_optimized_hash.puzzle_hash
        with_optimized_hash.puzzle_hash
        assert tree_hash_patched.call_count == 0
    assert with_optimized_hash.puzzle_hash == bytes32.zeros


def test_unknown_puzzle() -> None:
    # Test the None-ness of non-curried puzzles
    no_curry = Program.to("this is a program without curried params")
    unknown_puz = UnknownPuzzle(known_puzzle=no_curry)
    assert unknown_puz.mod is None
    assert unknown_puz.curried_args is None
    assert unknown_puz.puzzle_hash == no_curry.get_tree_hash()

    # Test the most common utilities
    with_curry = Program.to("mod").curry("arg1", "arg2", "arg3")
    with_curry_hash = with_curry.get_tree_hash()
    unknown_puz_with_curry = UnknownPuzzle(known_puzzle=with_curry)
    assert unknown_puz_with_curry.mod == Program.to("mod")
    assert list(unknown_puz_with_curry.curried_args or []) == [
        Program.to("arg1"),
        Program.to("arg2"),
        Program.to("arg3"),
    ]
    assert unknown_puz_with_curry.puzzle_hash == with_curry_hash

    # Test using only a puzzle hash
    unknown_puz_zeros = UnknownPuzzle(known_puzzle_hash=bytes32.zeros)
    with mock.patch.object(Program, "get_tree_hash") as tree_hash_patched:
        unknown_puz_zeros.puzzle_hash
        unknown_puz_zeros.puzzle_hash
        unknown_puz_zeros.puzzle_hash
        assert tree_hash_patched.call_count == 0
    assert unknown_puz_zeros.puzzle_hash == bytes32.zeros
    with pytest.raises(ValueError, match="Attempting to access puzzle when only puzzle hash is known"):
        _ = unknown_puz_zeros.puzzle

    # Check post init
    with pytest.raises(ValueError, match="Must specify either a puzzle or puzzle hash that is unknown"):
        UnknownPuzzle(known_puzzle=None, known_puzzle_hash=None)


def test_acs_puzzle() -> None:
    assert ACSPuzzle.match(unknown_puzzle=UnknownPuzzle(known_puzzle=Program.to(0))) is None
    assert ACSPuzzle.match(unknown_puzzle=UnknownPuzzle(known_puzzle=Program.to(1))) == ACSPuzzle()
    # Atoms are treated as an empty condition list by the parser
    assert ACSSolution.match(unknown_solution=UnknownSolution(solution=Program.to("not an ACS"))) == ACSSolution(
        conditions=[]
    )
    assert ACSSolution.match(unknown_solution=UnknownSolution(solution=Program.to(["not an ACS"]))) is None
    acs_solution = ACSSolution(conditions=[Remark(rest=Program.to("foo")), Remark(rest=Program.to("bar"))])
    assert (
        ACSSolution.match(unknown_solution=UnknownSolution(solution=run(ACSPuzzle().puzzle, acs_solution.as_program())))
        == acs_solution
    )
    assert ACS_PH == Program.to(1).get_tree_hash()
    assert NIL_HASH == Program.NIL.get_tree_hash()


def test_nil_puzzle() -> None:
    assert NilPuzzle.match(unknown_puzzle=UnknownPuzzle(known_puzzle=Program.NIL)) == NilPuzzle()
    assert NilPuzzle.match(unknown_puzzle=UnknownPuzzle(known_puzzle=Program.to("not a ()"))) is None
    assert NilSolution.match(unknown_solution=UnknownSolution(solution=Program.to("not a ()"))) is None
    assert (
        NilSolution.match(
            unknown_solution=UnknownSolution(solution=run(NilPuzzle().puzzle, NilSolution().as_program()))
        )
        == NilSolution()
    )


def test_p2_conditions() -> None:
    assert P2Conditions.match(unknown_puzzle=UnknownPuzzle(known_puzzle=Program.to((1, None)))) == P2Conditions(
        conditions=[]
    )
    assert P2Conditions.match(unknown_puzzle=UnknownPuzzle(known_puzzle=Program.to((2, None)))) is None
    assert P2Conditions.match(unknown_puzzle=UnknownPuzzle(known_puzzle=Program.to((1, ["not a condition"])))) is None
    assert ACSSolution.match(
        unknown_solution=UnknownSolution(
            solution=run(P2Conditions(conditions=[Remark(rest=Program.to("foo"))]).puzzle, NilSolution().as_program())
        )
    ) == ACSSolution(conditions=[Remark(rest=Program.to("foo"))])
