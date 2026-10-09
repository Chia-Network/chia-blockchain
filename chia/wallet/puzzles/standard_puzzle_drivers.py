from __future__ import annotations

from dataclasses import dataclass, field
from functools import cached_property
from typing import Generic, TypeVar

from chia_rs import G1Element
from chia_rs.sized_bytes import bytes32

from chia.types.blockchain_format.program import Program
from chia.wallet.conditions import Condition
from chia.wallet.puzzles.p2_delegated_puzzle_or_hidden_puzzle import (
    DEFAULT_HIDDEN_PUZZLE,
    DEFAULT_HIDDEN_PUZZLE_HASH,
    MOD,
    QUOTED_MOD_HASH,
    calculate_synthetic_public_key,
)
from chia.wallet.puzzles.puzzle_drivers import (
    NilSolution,
    P2Conditions,
    Puzzle,
    PuzzleBase,
    Solution,
    UnknownPuzzle,
    UnknownSolution,
)
from chia.wallet.util.curry_and_treehash import curry_and_treehash, shatree_atom


@dataclass(kw_only=True, frozen=True)
class DefaultHiddenPuzzle(PuzzleBase):
    @property
    def program(self) -> Program:
        return DEFAULT_HIDDEN_PUZZLE

    @property
    def tree_hash_optimized(self) -> bytes32:
        return DEFAULT_HIDDEN_PUZZLE_HASH

    @classmethod
    def match(cls, *, unknown_puzzle: UnknownPuzzle) -> DefaultHiddenPuzzle | None:
        if (
            unknown_puzzle.known_tree_hash == DEFAULT_HIDDEN_PUZZLE_HASH
            or unknown_puzzle.known_program == DEFAULT_HIDDEN_PUZZLE
        ):
            return cls()
        return None


_T_Puzzle = TypeVar("_T_Puzzle", bound=Puzzle)
_T_HiddenPuzzleSolution = TypeVar("_T_HiddenPuzzleSolution", bound=Solution)


@dataclass(kw_only=True, frozen=True)
class StandardPuzzle(PuzzleBase, Generic[_T_Puzzle]):
    pre_known_synthetic_public_key: G1Element | None = None
    pre_known_original_public_key: G1Element | None = None
    hidden_puzzle: _T_Puzzle = field(default_factory=DefaultHiddenPuzzle)  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.pre_known_synthetic_public_key is None and self.pre_known_original_public_key is None:
            raise ValueError("Must specify either the synthetic or original pubkey to construct a StandardPuzzle")

    @cached_property
    def synthetic_public_key(self) -> G1Element:
        if self.pre_known_synthetic_public_key is None:
            assert self.pre_known_original_public_key is not None  # guarded by __post_init__
            object.__setattr__(
                self,
                "pre_known_synthetic_public_key",
                calculate_synthetic_public_key(self.pre_known_original_public_key, self.hidden_puzzle.tree_hash),
            )
            assert self.pre_known_synthetic_public_key is not None
        return self.pre_known_synthetic_public_key

    @property
    def program(self) -> Program:
        return MOD.curry(self.synthetic_public_key)

    @property
    def tree_hash_optimized(self) -> bytes32:
        public_key_hash = shatree_atom(bytes(self.synthetic_public_key))
        return curry_and_treehash(QUOTED_MOD_HASH, public_key_hash)

    @classmethod
    def match(cls, *, unknown_puzzle: UnknownPuzzle) -> StandardPuzzle[DefaultHiddenPuzzle] | None:
        if unknown_puzzle.mod == MOD:
            if unknown_puzzle.curried_args is None:
                return None
            list_of_args = [arg for arg in unknown_puzzle.curried_args]
            if len(list_of_args) != 1:
                return None
            return StandardPuzzle(
                pre_known_synthetic_public_key=G1Element.from_bytes(list_of_args[0].as_atom()),
                hidden_puzzle=DefaultHiddenPuzzle(),
            )
        return None

    def hidden_puzzle_solution(
        self, solution: _T_HiddenPuzzleSolution
    ) -> StandardPuzzleSolution[_T_Puzzle, _T_HiddenPuzzleSolution]:
        if self.pre_known_original_public_key is None:
            raise ValueError(
                "Must set `pre_known_original_public_key` on `StandardPuzzle` before you can exercise the hidden puzzle"
            )
        return StandardPuzzleSolution(
            original_public_key=self.pre_known_original_public_key,
            delegated_puzzle=self.hidden_puzzle,
            delegated_solution=solution,
        )


_T_Solution = TypeVar("_T_Solution", bound=Solution)


@dataclass(kw_only=True)
class StandardPuzzleSolution(Generic[_T_Puzzle, _T_Solution]):
    original_public_key: G1Element | None = None
    delegated_puzzle: _T_Puzzle
    delegated_solution: _T_Solution

    @classmethod
    def for_conditions(cls, conditions: list[Condition]) -> StandardPuzzleSolution[P2Conditions, NilSolution]:
        return StandardPuzzleSolution(
            delegated_puzzle=P2Conditions(conditions=conditions),
            delegated_solution=NilSolution(),
        )

    @property
    def program(self) -> Program:
        return Program.to([self.original_public_key, self.delegated_puzzle.program, self.delegated_solution.program])

    @classmethod
    def match(
        cls, *, unknown_solution: UnknownSolution
    ) -> StandardPuzzleSolution[UnknownPuzzle, UnknownSolution] | None:
        if unknown_solution.program.atom is not None:
            return None
        list_of_values = list(unknown_solution.program.as_iter())
        if len(list_of_values) != 3:
            return None
        return StandardPuzzleSolution(
            original_public_key=G1Element.from_bytes(list_of_values[0].as_atom())
            if list_of_values[0] != Program.to(None)
            else None,
            delegated_puzzle=UnknownPuzzle(known_program=list_of_values[1]),
            delegated_solution=UnknownSolution(program=list_of_values[2]),
        )
