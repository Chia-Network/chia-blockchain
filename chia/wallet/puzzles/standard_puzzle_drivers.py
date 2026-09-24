from __future__ import annotations

from dataclasses import dataclass, field
from functools import cached_property
from typing import TYPE_CHECKING, ClassVar, cast

from chia_rs import Coin, G1Element
from chia_rs.sized_bytes import bytes32
from typing_extensions import Self

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
    SmartCoin,
    Solution,
    UnknownPuzzle,
    UnknownSolution,
)
from chia.wallet.util.curry_and_treehash import curry_and_treehash, shatree_atom


@dataclass(kw_only=True, frozen=True)
class HiddenPuzzleInfo(PuzzleBase):
    program: Program = field(default_factory=lambda: DEFAULT_HIDDEN_PUZZLE)
    pre_computed_puzzle_hash: bytes32 | None = field(default=DEFAULT_HIDDEN_PUZZLE_HASH, kw_only=True)


@dataclass(kw_only=True, frozen=True)
class StandardPuzzle(PuzzleBase):
    if TYPE_CHECKING:
        _protocol_check: ClassVar[Puzzle] = cast("StandardPuzzle", None)

    pre_known_synthetic_public_key: G1Element | None = None
    pre_known_original_public_key: G1Element | None = None
    hidden_puzzle_info: HiddenPuzzleInfo = field(default_factory=HiddenPuzzleInfo)

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
                calculate_synthetic_public_key(self.pre_known_original_public_key, self.hidden_puzzle_info.tree_hash),
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
    def match(cls, *, unknown_puzzle: UnknownPuzzle) -> StandardPuzzle | None:
        if unknown_puzzle.mod == MOD:
            if unknown_puzzle.curried_args is None:
                return None
            list_of_args = [arg for arg in unknown_puzzle.curried_args]
            if len(list_of_args) != 1:
                return None
            return cls(
                pre_known_synthetic_public_key=G1Element.from_bytes(list_of_args[0].as_atom()),
            )
        return None

    def hidden_puzzle_solution(self, solution: Program) -> StandardPuzzleSolution:
        if self.pre_known_original_public_key is None:
            raise ValueError(
                "Must set `pre_known_original_public_key` on `StandardPuzzle` before you can exercise the hidden puzzle"
            )
        return StandardPuzzleSolution(
            original_public_key=self.pre_known_original_public_key,
            delegated_puzzle=self.hidden_puzzle_info.program,
            delegated_solution=solution,
        )


@dataclass(kw_only=True)
class StandardPuzzleSolution:
    if TYPE_CHECKING:
        _protocol_check: ClassVar[Solution] = cast("StandardPuzzleSolution", None)

    original_public_key: G1Element | None = None
    delegated_puzzle: Program
    delegated_solution: Program

    @classmethod
    def for_conditions(cls, conditions: list[Condition]) -> Self:
        return cls(
            delegated_puzzle=P2Conditions(conditions=conditions).program,
            delegated_solution=NilSolution().program,
        )

    @property
    def program(self) -> Program:
        return Program.to([self.original_public_key, self.delegated_puzzle, self.delegated_solution])

    @classmethod
    def match(cls, *, unknown_solution: UnknownSolution) -> StandardPuzzleSolution | None:
        if unknown_solution.program.atom is not None:
            return None
        list_of_values = list(unknown_solution.program.as_iter())
        if len(list_of_values) != 3:
            return None
        return StandardPuzzleSolution(
            original_public_key=G1Element.from_bytes(list_of_values[0].as_atom())
            if list_of_values[0] != Program.to(None)
            else None,
            delegated_puzzle=list_of_values[1],
            delegated_solution=list_of_values[2],
        )


@dataclass(kw_only=True, frozen=True)
class StandardXCHCoin(StandardPuzzle):
    if TYPE_CHECKING:
        _protocol_check_2: ClassVar[SmartCoin] = cast("StandardXCHCoin", None)

    coin: Coin
