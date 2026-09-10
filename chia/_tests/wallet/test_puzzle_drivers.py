from __future__ import annotations

from unittest import mock

import pytest
from attr import dataclass
from chia_rs.sized_bytes import bytes32

from chia.types.blockchain_format.program import Program, run
from chia.wallet import uncurried_puzzle as uncurried_puzzle_mod
from chia.wallet.conditions import Remark
from chia.wallet.puzzles.puzzle_drivers import (
    ACS_PH,
    NIL_HASH,
    ACSPuzzle,
    ACSSolution,
    NilPuzzle,
    NilSolution,
    P2Conditions,
    PuzzleBase,
    UnknownPuzzle,
    UnknownSolution,
)
from chia.wallet.uncurried_puzzle import uncurry_puzzle


def test_puzzle_base() -> None:
    @dataclass
    class SomePuzzleDriverWithoutOptimizedPuzzleHash(PuzzleBase):
        program: Program = Program.to(None)

    @dataclass
    class SomePuzzleDriverWithOptimizedPuzzleHash(PuzzleBase):
        program: Program = Program.to(None)
        tree_hash_optimized: bytes32 = bytes32.zeros

    without_optimized_hash = SomePuzzleDriverWithoutOptimizedPuzzleHash()
    with_optimized_hash = SomePuzzleDriverWithOptimizedPuzzleHash()

    assert without_optimized_hash.tree_hash == NIL_HASH
    with mock.patch.object(Program, "get_tree_hash") as tree_hash_patched:
        without_optimized_hash.tree_hash
        without_optimized_hash.tree_hash
        without_optimized_hash.tree_hash
        assert tree_hash_patched.call_count == 0

    with mock.patch.object(Program, "get_tree_hash") as tree_hash_patched:
        with_optimized_hash.tree_hash
        with_optimized_hash.tree_hash
        with_optimized_hash.tree_hash
        assert tree_hash_patched.call_count == 0
    assert with_optimized_hash.tree_hash == bytes32.zeros


def test_unknown_puzzle() -> None:
    # Test the None-ness of non-curried puzzles
    no_curry = Program.to("this is a program without curried params")
    unknown_puz = UnknownPuzzle(known_program=no_curry)
    assert unknown_puz.mod is None
    assert unknown_puz.curried_args is None
    assert unknown_puz.tree_hash == no_curry.get_tree_hash()

    # Test the most common utilities
    with_curry = Program.to("mod").curry("arg1", "arg2", "arg3")
    with_curry_hash = with_curry.get_tree_hash()
    unknown_puz_with_curry = UnknownPuzzle(known_program=with_curry)
    assert unknown_puz_with_curry.mod == Program.to("mod")
    assert unknown_puz_with_curry.curried_args == [Program.to("arg1"), Program.to("arg2"), Program.to("arg3")]
    assert unknown_puz_with_curry.tree_hash == with_curry_hash
    with (
        mock.patch.object(Program, "get_tree_hash") as tree_hash_patched,
        mock.patch.object(uncurried_puzzle_mod, "uncurry_puzzle") as uncurry_patched,
    ):
        unknown_puz_with_curry.mod
        unknown_puz_with_curry.curried_args
        unknown_puz_with_curry.mod
        unknown_puz_with_curry.curried_args
        unknown_puz_with_curry.mod
        unknown_puz_with_curry.curried_args
        assert uncurry_patched.call_count == 0
        unknown_puz_with_curry.tree_hash
        unknown_puz_with_curry.tree_hash
        unknown_puz_with_curry.tree_hash
        assert tree_hash_patched.call_count == 0

    # Test the transition from uncurried puzzle
    uncurried_puzzle = uncurry_puzzle(with_curry)
    with_curry_from_uncurried = UnknownPuzzle.from_uncurried(uncurried_puzzle)
    assert with_curry_from_uncurried.program == with_curry
    with mock.patch.object(Program, "curry") as curry_patched:
        with_curry_from_uncurried.program
        with_curry_from_uncurried.program
        with_curry_from_uncurried.program
        assert curry_patched.call_count == 0

    # Test using only a puzzle hash
    unknown_puz_zeros = UnknownPuzzle(known_tree_hash=bytes32.zeros)
    with mock.patch.object(Program, "get_tree_hash") as tree_hash_patched:
        unknown_puz_zeros.tree_hash
        unknown_puz_zeros.tree_hash
        unknown_puz_zeros.tree_hash
        assert tree_hash_patched.call_count == 0
    assert unknown_puz_zeros.tree_hash == bytes32.zeros
    with pytest.raises(ValueError, match="Attempting to access program when only tree hash is known"):
        unknown_puz_zeros.program

    # Check post init
    with pytest.raises(ValueError, match="Must specify either a program or tree hash that is unknown"):
        UnknownPuzzle(known_program=None, known_tree_hash=None)


def test_acs_puzzle() -> None:
    assert ACSPuzzle.match(unknown_puzzle=UnknownPuzzle(known_tree_hash=bytes32.zeros)) is None
    assert ACSPuzzle.match(unknown_puzzle=UnknownPuzzle(known_tree_hash=ACS_PH)) == ACSPuzzle()
    assert ACSSolution.match(unknown_solution=UnknownSolution(program=Program.to("not an ACS"))) is None
    assert ACSSolution.match(unknown_solution=UnknownSolution(program=Program.to(["not an ACS"]))) is None
    acs_solution = ACSSolution(conditions=[Remark(rest=Program.to("foo")), Remark(rest=Program.to("bar"))])
    assert (
        ACSSolution.match(unknown_solution=UnknownSolution(program=run(ACSPuzzle().program, acs_solution.program)))
        == acs_solution
    )


def test_nil_puzzle() -> None:
    assert NilPuzzle.match(unknown_puzzle=UnknownPuzzle(known_tree_hash=NIL_HASH)) == NilPuzzle()
    assert NilPuzzle.match(unknown_puzzle=UnknownPuzzle(known_program=Program.to("not a ()"))) is None
    assert NilSolution.match(unknown_solution=UnknownSolution(program=Program.to("not a ()"))) is None
    assert (
        NilSolution.match(unknown_solution=UnknownSolution(program=run(NilPuzzle().program, NilSolution().program)))
        == NilSolution()
    )


def test_p2_conditions() -> None:
    assert P2Conditions.match(unknown_puzzle=UnknownPuzzle(known_program=Program.to((1, None)))) == P2Conditions(
        conditions=[]
    )
    assert P2Conditions.match(unknown_puzzle=UnknownPuzzle(known_program=Program.NIL)) is None
    assert P2Conditions.match(unknown_puzzle=UnknownPuzzle(known_program=Program.to((2, None)))) is None
    assert P2Conditions.match(unknown_puzzle=UnknownPuzzle(known_program=Program.to((1, ["not a condition"])))) is None
    assert ACSSolution.match(
        unknown_solution=UnknownSolution(
            program=run(P2Conditions(conditions=[Remark(rest=Program.to("foo"))]).program, NilSolution().program)
        )
    ) == ACSSolution(conditions=[Remark(rest=Program.to("foo"))])
