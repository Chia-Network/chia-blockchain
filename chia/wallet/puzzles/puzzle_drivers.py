from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from functools import cached_property
from typing import TYPE_CHECKING, ClassVar, Protocol, TypeVar, cast

from chia_rs import Coin
from chia_rs.sized_bytes import bytes32
from typing_extensions import Self, runtime_checkable

from chia.types.blockchain_format.program import Program
from chia.wallet.uncurried_puzzle import UncurriedPuzzle, uncurry_puzzle


class InnerPuzzle(Protocol):
    @property
    def puzzle(self) -> Program: ...

    @property
    def puzzle_hash(self) -> bytes32: ...

    @classmethod
    def match(cls, *, unknown_puzzle: UnknownPuzzle, solution: object | None = None) -> InnerPuzzle | None: ...


_T_InnerPuzzle_co = TypeVar("_T_InnerPuzzle_co", bound=InnerPuzzle, covariant=True)


class OuterPuzzle(InnerPuzzle, Protocol[_T_InnerPuzzle_co]):
    @property
    def inner_puzzle(self) -> _T_InnerPuzzle_co: ...


class Solution(Protocol):
    def as_program(self) -> Program: ...

    @classmethod
    def match(cls, *, unknown_solution: UnknownSolution) -> Solution | None: ...


class SmartCoin(InnerPuzzle, Protocol):
    @property
    def coin(self) -> Coin: ...


@runtime_checkable
class OptimizedPuzzleHashPuzzle(Protocol):
    @property
    def puzzle_hash_optimized(self) -> bytes32: ...


@dataclass
class PuzzleWithPuzzleHash:
    """
    This is designed to be a base class to `Inner/OuterPuzzle`s which provides caching on the puzzle hash generation
    """

    pre_computed_puzzle_hash: bytes32 | None = field(default=None, kw_only=True)

    @property
    def puzzle_hash(self) -> bytes32:
        if self.pre_computed_puzzle_hash is None:
            if isinstance(self, OptimizedPuzzleHashPuzzle):
                self.pre_computed_puzzle_hash = self.puzzle_hash_optimized
            else:
                self.pre_computed_puzzle_hash = self.puzzle.get_tree_hash()  # type: ignore[attr-defined]
        return self.pre_computed_puzzle_hash


@dataclass(kw_only=True)
class UnknownPuzzle(PuzzleWithPuzzleHash):
    if TYPE_CHECKING:
        _protocol_check: ClassVar[InnerPuzzle] = cast("UnknownPuzzle", None)

    known_puzzle: Program | None = None
    known_puzzle_hash: bytes32 | None = None

    def __post_init__(self) -> None:
        if self.known_puzzle is None and self.known_puzzle_hash is None:
            raise ValueError("Must specify either a puzzle or puzzle hash that is unknown")

    @property
    def puzzle(self) -> Program:
        if self.known_puzzle is None:
            raise ValueError("Attempting to access puzzle when only puzzle hash is known")
        return self.known_puzzle

    @property
    def puzzle_hash_optimized(self) -> bytes32:
        return self.known_puzzle_hash if self.known_puzzle_hash is not None else self.puzzle.get_tree_hash()

    @cached_property
    def _uncurry_result(self) -> UncurriedPuzzle:
        return uncurry_puzzle(self.puzzle)

    @cached_property
    def mod(self) -> Program | None:
        if self._uncurry_result.mod == self.puzzle:
            return None
        return self._uncurry_result.mod

    @cached_property
    def curried_args(self) -> Iterator[Program] | None:
        if self.mod is None:
            return None
        return self._uncurry_result.args.as_iter()

    @classmethod
    def match(cls, *, unknown_puzzle: UnknownPuzzle, solution: object | None = None) -> Self | None:  # pragma: no cover
        raise NotImplementedError("UnknownPuzzles cannot match anything, they are for being matched")


@dataclass
class UnknownSolution:
    if TYPE_CHECKING:
        _protocol_check: ClassVar[Solution] = cast("UnknownSolution", None)

    solution: Program

    def as_program(self) -> Program:
        return self.solution

    @classmethod
    def match(cls, *, unknown_solution: UnknownSolution) -> Self | None:  # pragma: no cover
        raise NotImplementedError("UnknownPuzzles cannot match anything, they are for being matched")


@dataclass
class DelegatedPuzzleAndSolution:
    puzzle: InnerPuzzle
    solution: Solution
