from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from functools import cached_property
from typing import Protocol

from chia_rs.sized_bytes import bytes32
from typing_extensions import runtime_checkable

from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.serialized_program import SerializedProgram
from chia.wallet.conditions import Condition, parse_conditions_non_consensus
from chia.wallet.uncurried_puzzle import UncurriedPuzzle, uncurry_puzzle


class Puzzle(Protocol):
    @property
    def program(self) -> Program: ...

    @property
    def tree_hash(self) -> bytes32: ...

    @classmethod
    def match(cls, *, unknown_puzzle: UnknownPuzzle) -> Puzzle | None: ...


class Solution(Protocol):
    @property
    def program(self) -> Program: ...

    @classmethod
    def match(cls, *, unknown_solution: UnknownSolution) -> Solution | None: ...


@runtime_checkable
class OptimizedPuzzleHashPuzzle(Protocol):
    @property
    def tree_hash_optimized(self) -> bytes32: ...


class PuzzleBase:
    """
    This is designed to be a base class to `Inner/OuterPuzzle`s which provides caching on the puzzle hash generation
    """

    pre_computed_tree_hash: bytes32 | None = None

    @property
    def tree_hash(self) -> bytes32:
        if self.pre_computed_tree_hash is None:
            if isinstance(self, OptimizedPuzzleHashPuzzle):
                object.__setattr__(self, "pre_computed_tree_hash", self.tree_hash_optimized)
            else:
                object.__setattr__(self, "pre_computed_tree_hash", self.program.get_tree_hash())  # type: ignore[attr-defined]
        assert self.pre_computed_tree_hash is not None
        return self.pre_computed_tree_hash


@dataclass(kw_only=True, frozen=True)
class UnknownPuzzle(PuzzleBase):
    known_program: Program | SerializedProgram | None = None
    known_tree_hash: bytes32 | None = None
    _uncurried_puzzle: UncurriedPuzzle | None = None

    def __post_init__(self) -> None:
        if self.known_program is None and self.known_tree_hash is None and self._uncurried_puzzle is None:
            raise ValueError("Must specify either a program or tree hash that is unknown")

    @property
    def program(self) -> Program:
        if self.known_program is None:
            if self._uncurried_puzzle is None:
                raise ValueError("Attempting to access program when only tree hash is known")
            known_program = self._uncurried_puzzle.mod.curry(*self._uncurried_puzzle.args.as_iter())
            object.__setattr__(self, "known_program", known_program)
            return known_program
        return (
            Program.from_serialized(self.known_program)
            if isinstance(self.known_program, SerializedProgram)
            else self.known_program
        )

    @property
    def tree_hash_optimized(self) -> bytes32:
        return self.known_tree_hash if self.known_tree_hash is not None else self.program.get_tree_hash()

    @cached_property
    def _uncurry_result(self) -> UncurriedPuzzle:
        if self._uncurried_puzzle is not None:
            return self._uncurried_puzzle
        return uncurry_puzzle(self.program)

    @cached_property
    def mod(self) -> Program | None:
        if self._uncurry_result.mod == self.program:
            return None
        return self._uncurry_result.mod

    @cached_property
    def curried_args(self) -> list[Program] | None:
        if self.mod is None:
            return None
        return list(self._uncurry_result.args.as_iter())

    @classmethod
    def from_uncurried(cls, uncurried_puzzle: UncurriedPuzzle) -> UnknownPuzzle:
        return cls(_uncurried_puzzle=uncurried_puzzle)

    @classmethod
    def match(cls, *, unknown_puzzle: UnknownPuzzle) -> UnknownPuzzle | None:  # pragma: no cover
        raise NotImplementedError("UnknownPuzzles cannot match anything, they are for being matched")


@dataclass(frozen=True)
class UnknownSolution:
    program: Program

    @classmethod
    def match(cls, *, unknown_solution: UnknownSolution) -> UnknownSolution | None:  # pragma: no cover
        raise NotImplementedError("UnknownPuzzles cannot match anything, they are for being matched")


@dataclass(frozen=True)
class DelegatedPuzzleAndSolution:
    puzzle: Puzzle
    solution: Solution


@dataclass(kw_only=True, frozen=True)
class P2Conditions(PuzzleBase):
    conditions: Sequence[Condition]

    @property
    def program(self) -> Program:
        return Program.to((1, [cond.to_program() for cond in self.conditions]))

    @classmethod
    def match(cls, *, unknown_puzzle: UnknownPuzzle) -> P2Conditions | None:
        if unknown_puzzle.program.atom is not None or unknown_puzzle.program.at("f") != Program.to(1):
            return None

        try:
            return cls(conditions=parse_conditions_non_consensus(unknown_puzzle.program.at("r").as_iter()))
        except Exception:
            return None


ACS = Program.to(1)
ACS_PH = ACS.get_tree_hash()


@dataclass(kw_only=True, frozen=True)
class ACSPuzzle(PuzzleBase):
    program: Program = field(init=False, default_factory=lambda: ACS)
    tree_hash_optimized: bytes32 = field(init=False, default=ACS_PH)

    @classmethod
    def match(cls, *, unknown_puzzle: UnknownPuzzle) -> ACSPuzzle | None:
        if unknown_puzzle.tree_hash == ACS_PH:
            return cls()
        return None


@dataclass(kw_only=True, frozen=True)
class ACSSolution:
    conditions: Sequence[Condition]

    @property
    def program(self) -> Program:
        return Program.to([cond.to_program() for cond in self.conditions])

    @classmethod
    def match(cls, *, unknown_solution: UnknownSolution) -> ACSSolution | None:
        if unknown_solution.program.atom is not None and unknown_solution.program != Program.NIL:
            return None
        try:
            return cls(conditions=parse_conditions_non_consensus(unknown_solution.program.as_iter()))
        except Exception:
            return None


NIL_HASH = Program.NIL.get_tree_hash()


@dataclass(kw_only=True, frozen=True)
class NilPuzzle(PuzzleBase):
    program: Program = field(init=False, default_factory=lambda: Program.NIL)
    tree_hash_optimized: bytes32 = field(init=False, default=NIL_HASH)

    @classmethod
    def match(cls, *, unknown_puzzle: UnknownPuzzle) -> NilPuzzle | None:
        if unknown_puzzle.tree_hash == NIL_HASH:
            return cls()
        return None


@dataclass(kw_only=True, frozen=True)
class NilSolution:
    program: Program = field(init=False, default_factory=lambda: Program.NIL)

    @classmethod
    def match(cls, *, unknown_solution: UnknownSolution) -> NilSolution | None:
        if unknown_solution.program == Program.NIL:
            return cls()
        return None
