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
    def from_uncurried(cls, uncurried_puzzle: UncurriedPuzzle) -> Self:
        return cls(_uncurried_puzzle=uncurried_puzzle)
