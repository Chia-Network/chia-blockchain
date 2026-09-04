from __future__ import annotations

from dataclasses import dataclass
from functools import cached_property
from typing import Protocol, Self

from chia_rs.sized_bytes import bytes32
from typing_extensions import runtime_checkable

from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.serialized_program import SerializedProgram
from chia.wallet.uncurried_puzzle import UncurriedPuzzle, uncurry_puzzle


@runtime_checkable
class OptimizedPuzzleHashPuzzle(Protocol):
    @property
    def puzzle_hash_optimized(self) -> bytes32: ...


class PuzzleBase:
    """
    This is designed to be a base class to `Inner/OuterPuzzle`s which provides caching on the puzzle hash generation
    """

    pre_computed_puzzle_hash: bytes32 | None = None

    @property
    def puzzle_hash(self) -> bytes32:
        if self.pre_computed_puzzle_hash is None:
            if isinstance(self, OptimizedPuzzleHashPuzzle):
                object.__setattr__(self, "pre_computed_puzzle_hash", self.puzzle_hash_optimized)
            else:
                object.__setattr__(self, "pre_computed_puzzle_hash", self.puzzle.get_tree_hash())  # type: ignore[attr-defined]
        assert self.pre_computed_puzzle_hash is not None
        return self.pre_computed_puzzle_hash


@dataclass(kw_only=True, frozen=True)
class UnknownPuzzle(PuzzleBase):
    known_program: Program | SerializedProgram | None = None
    known_tree_hash: bytes32 | None = None
    _uncurried_puzzle: UncurriedPuzzle | None = None

    def __post_init__(self) -> None:
        if self.known_program is None and self.known_tree_hash is None and self._uncurried_puzzle is None:
            raise ValueError("Must specify either a puzzle or puzzle hash that is unknown")

    @property
    def puzzle(self) -> Program:
        if self.known_program is None:
            if self._uncurried_puzzle is None:
                raise ValueError("Attempting to access puzzle when only puzzle hash is known")
            return self._uncurried_puzzle.mod.curry(*self._uncurried_puzzle.args.as_iter())
        return (
            Program.from_serialized(self.known_program)
            if isinstance(self.known_program, SerializedProgram)
            else self.known_program
        )

    @property
    def puzzle_hash_optimized(self) -> bytes32:
        return self.known_tree_hash if self.known_tree_hash is not None else self.puzzle.get_tree_hash()

    @cached_property
    def _uncurry_result(self) -> UncurriedPuzzle:
        if self._uncurried_puzzle is not None:
            return self._uncurried_puzzle
        return uncurry_puzzle(self.puzzle)

    @cached_property
    def mod(self) -> Program | None:
        if self._uncurry_result.mod == self.puzzle:
            return None
        return self._uncurry_result.mod

    @cached_property
    def curried_args(self) -> list[Program] | None:
        if self.mod is None:
            return None
        return list(self._uncurry_result.args.as_iter())

    @classmethod
    def from_uncurried(cls, uncurried_puzzle: UncurriedPuzzle) -> Self:
        return cls(_uncurried_puzzle=uncurried_puzzle)

    @classmethod
    def match(cls, *, unknown_puzzle: UnknownPuzzle) -> Self | None:  # pragma: no cover
        raise NotImplementedError("UnknownPuzzles cannot match anything, they are for being matched")
