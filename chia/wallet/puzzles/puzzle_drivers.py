from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from functools import cached_property
from typing import TYPE_CHECKING, ClassVar, Protocol, TypeVar, cast

from chia_rs import Coin
from chia_rs.sized_bytes import bytes32
from typing_extensions import Self, runtime_checkable

from chia.types.blockchain_format.program import Program
from chia.wallet.conditions import Condition, parse_conditions_non_consensus
from chia.wallet.uncurried_puzzle import UncurriedPuzzle, uncurry_puzzle


class Puzzle(Protocol):
    @property
    def program(self) -> Program: ...

    @property
    def tree_hash(self) -> bytes32: ...

    @classmethod
    def match(cls, *, unknown_puzzle: UnknownPuzzle) -> Puzzle | None: ...


_T_Puzzle_co = TypeVar("_T_Puzzle_co", bound=Puzzle, covariant=True)


class OuterPuzzle(Puzzle, Protocol[_T_Puzzle_co]):
    @property
    def inner_puzzle(self) -> _T_Puzzle_co: ...


class Solution(Protocol):
    @property
    def program(self) -> Program: ...

    @classmethod
    def match(cls, *, unknown_solution: UnknownSolution) -> Solution | None: ...


class SmartCoin(Puzzle, Protocol):
    @property
    def coin(self) -> Coin: ...


@runtime_checkable
class OptimizedPuzzleHashPuzzle(Protocol):
    @property
    def tree_hash_optimized(self) -> bytes32: ...


class PuzzleWithPuzzleHash:
    """
    This is designed to be a base class to `Inner/OuterPuzzle`s which provides caching on the puzzle hash generation
    """

    pre_computed_puzzle_hash: bytes32 | None = None

    @property
    def tree_hash(self) -> bytes32:
        if self.pre_computed_puzzle_hash is None:
            if isinstance(self, OptimizedPuzzleHashPuzzle):
                object.__setattr__(self, "pre_computed_puzzle_hash", self.tree_hash_optimized)
            else:
                object.__setattr__(self, "pre_computed_puzzle_hash", self.program.get_tree_hash())  # type: ignore[attr-defined]
        assert self.pre_computed_puzzle_hash is not None
        return self.pre_computed_puzzle_hash


@dataclass(kw_only=True, frozen=True)
class UnknownPuzzle(PuzzleWithPuzzleHash):
    if TYPE_CHECKING:
        _protocol_check: ClassVar[Puzzle] = cast("UnknownPuzzle", None)

    known_program: Program | None = None
    known_tree_hash: bytes32 | None = None

    def __post_init__(self) -> None:
        if self.known_program is None and self.known_tree_hash is None:
            raise ValueError("Must specify either a puzzle or puzzle hash that is unknown")

    @property
    def program(self) -> Program:
        if self.known_program is None:
            raise ValueError("Attempting to access puzzle when only puzzle hash is known")
        return self.known_program

    @property
    def tree_hash_optimized(self) -> bytes32:
        return self.known_tree_hash if self.known_tree_hash is not None else self.program.get_tree_hash()

    @cached_property
    def _uncurry_result(self) -> UncurriedPuzzle:
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
    def match(cls, *, unknown_puzzle: UnknownPuzzle) -> Self | None:  # pragma: no cover
        raise NotImplementedError("UnknownPuzzles cannot match anything, they are for being matched")


@dataclass
class UnknownSolution:
    if TYPE_CHECKING:
        _protocol_check: ClassVar[Solution] = cast("UnknownSolution", None)

    program: Program

    @classmethod
    def match(cls, *, unknown_solution: UnknownSolution) -> Self | None:  # pragma: no cover
        raise NotImplementedError("UnknownPuzzles cannot match anything, they are for being matched")


@dataclass(kw_only=True, frozen=True)
class P2Conditions(PuzzleWithPuzzleHash):
    if TYPE_CHECKING:
        _protocol_check: ClassVar[Puzzle] = cast("P2Conditions", None)

    conditions: Sequence[Condition]

    @property
    def program(self) -> Program:
        return Program.to((1, [cond.to_program() for cond in self.conditions]))

    @classmethod
    def match(cls, *, unknown_puzzle: UnknownPuzzle) -> Self | None:
        if unknown_puzzle.program.at("f") != Program.to(1):
            return None

        try:
            return cls(conditions=parse_conditions_non_consensus(unknown_puzzle.program.at("r").as_iter()))
        except Exception:
            return None


ACS = Program.to(1)
ACS_PH = ACS.get_tree_hash()


@dataclass(kw_only=True, frozen=True)
class ACSPuzzle(PuzzleWithPuzzleHash):
    if TYPE_CHECKING:
        _protocol_check: ClassVar[Puzzle] = cast("ACSPuzzle", None)

    @property
    def program(self) -> Program:
        return ACS

    @classmethod
    def match(cls, *, unknown_puzzle: UnknownPuzzle) -> Self | None:
        if unknown_puzzle.program == ACS:
            return cls()
        return None


@dataclass(kw_only=True, frozen=True)
class ACSSolution:
    if TYPE_CHECKING:
        _protocol_check: ClassVar[Solution] = cast("ACSSolution", None)

    conditions: Sequence[Condition]

    @property
    def program(self) -> Program:
        return Program.to([cond.to_program() for cond in self.conditions])

    @classmethod
    def match(cls, *, unknown_solution: UnknownSolution) -> Self | None:
        try:
            return cls(conditions=parse_conditions_non_consensus(unknown_solution.program.as_iter()))
        except Exception:
            return None


NIL_HASH = Program.NIL.get_tree_hash()


@dataclass(kw_only=True, frozen=True)
class NilPuzzle(PuzzleWithPuzzleHash):
    if TYPE_CHECKING:
        _protocol_check: ClassVar[Puzzle] = cast("NilPuzzle", None)

    @property
    def program(self) -> Program:
        return Program.NIL

    @property
    def tree_hash_optimized(self) -> bytes32:
        return NIL_HASH

    @classmethod
    def match(cls, *, unknown_puzzle: UnknownPuzzle) -> Self | None:
        if unknown_puzzle.program == Program.NIL:
            return cls()
        return None


@dataclass(kw_only=True, frozen=True)
class NilSolution:
    if TYPE_CHECKING:
        _protocol_check: ClassVar[Solution] = cast("NilSolution", None)

    @property
    def program(self) -> Program:
        return Program.NIL

    @classmethod
    def match(cls, *, unknown_solution: UnknownSolution) -> Self | None:
        if unknown_solution.program == Program.NIL:
            return cls()
        return None


@dataclass
class DelegatedPuzzleAndSolution:
    puzzle: Puzzle
    solution: Solution
