from __future__ import annotations

from dataclasses import dataclass, field
from functools import cached_property
from typing import TYPE_CHECKING, ClassVar, cast

from chia_rs import Coin, CoinSpend, G1Element
from chia_rs.sized_bytes import bytes32
from typing_extensions import Self

from chia.types.blockchain_format.program import Program
from chia.types.coin_spend import make_spend
from chia.wallet.conditions import Condition
from chia.wallet.puzzles.p2_delegated_puzzle_or_hidden_puzzle import (
    DEFAULT_HIDDEN_PUZZLE,
    DEFAULT_HIDDEN_PUZZLE_HASH,
    MOD,
    QUOTED_MOD_HASH,
    calculate_synthetic_public_key,
)
from chia.wallet.puzzles.puzzle_drivers import InnerPuzzle, PuzzleWithPuzzleHash, UnknownPuzzle
from chia.wallet.util.curry_and_treehash import curry_and_treehash, shatree_atom


@dataclass(kw_only=True)
class HiddenPuzzleInfo(PuzzleWithPuzzleHash):
    puzzle: Program = field(default_factory=lambda: DEFAULT_HIDDEN_PUZZLE)
    pre_computed_puzzle_hash: bytes32 | None = field(default=DEFAULT_HIDDEN_PUZZLE_HASH, kw_only=True)


@dataclass(kw_only=True)
class StandardPuzzle(PuzzleWithPuzzleHash):
    if TYPE_CHECKING:
        _protocol_check: ClassVar[InnerPuzzle] = cast("StandardPuzzle", None)

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
            self.pre_known_synthetic_public_key = calculate_synthetic_public_key(
                self.pre_known_original_public_key, self.hidden_puzzle_info.puzzle_hash
            )
        return self.pre_known_synthetic_public_key

    @property
    def puzzle(self) -> Program:
        return MOD.curry(self.synthetic_public_key)

    @property
    def puzzle_hash_optimized(self) -> bytes32:
        public_key_hash = shatree_atom(bytes(self.synthetic_public_key))
        return curry_and_treehash(QUOTED_MOD_HASH, public_key_hash)

    @classmethod
    def match(cls, *, unknown_puzzle: UnknownPuzzle, solution: object | None = None) -> Self | None:
        if unknown_puzzle.mod == MOD:
            if unknown_puzzle.curried_args is None:
                return None
            list_of_args = [arg for arg in unknown_puzzle.curried_args]
            if len(list_of_args) != 1:
                return None
            original_public_key = None
            hidden_puzzle_info = HiddenPuzzleInfo()
            if solution is not None:
                if not isinstance(solution, StandardPuzzleSolution):
                    raise ValueError("Trying to match a standard puzzle without a standard puzzle solution")
                if solution.original_public_key is not None:
                    original_public_key = solution.original_public_key
                    hidden_puzzle_info.puzzle = solution.puzzle_reveal
                    hidden_puzzle_info.pre_computed_puzzle_hash = None
            return cls(
                pre_known_synthetic_public_key=G1Element.from_bytes(list_of_args[0].as_atom()),
                pre_known_original_public_key=original_public_key,
                hidden_puzzle_info=hidden_puzzle_info,
            )
        return None


@dataclass(kw_only=True)
class StandardPuzzleSolution:
    original_public_key: G1Element | None = None
    puzzle_reveal: Program
    delegated_solution: Program

    def as_program(self) -> Program:
        return Program.to([self.original_public_key, self.puzzle_reveal, self.delegated_solution])

    @classmethod
    def match(cls, solution: Program) -> Self | None:
        if solution.atom is not None:
            return None
        list_of_values = list(solution.as_iter())
        if len(list_of_values) != 3:
            return None
        return cls(
            original_public_key=G1Element.from_bytes(list_of_values[0].as_atom())
            if list_of_values[0] != Program.to(None)
            else None,
            puzzle_reveal=list_of_values[1],
            delegated_solution=list_of_values[2],
        )


@dataclass(kw_only=True)
class StandardXCHCoin(StandardPuzzle):
    coin: Coin

    def spend(self, conditions: list[Condition]) -> CoinSpend:
        return self.spend_delegated(
            delegated_puzzle=Program.to((1, [cond.to_program() for cond in conditions])),
            delegated_solution=Program.NIL,
        )

    def spend_delegated(self, delegated_puzzle: Program, delegated_solution: Program) -> CoinSpend:
        return make_spend(
            self.coin,
            self.puzzle,
            StandardPuzzleSolution(puzzle_reveal=delegated_puzzle, delegated_solution=delegated_solution).as_program(),
        )

    def spend_hidden(self, hidden_puzzle_solution: Program) -> CoinSpend:
        if self.pre_known_original_public_key is None:
            raise ValueError(
                "Must set `pre_known_original_public_key` on `StandardPuzzle` before you can exercise the hidden puzzle"
            )
        return make_spend(
            self.coin,
            self.puzzle,
            StandardPuzzleSolution(
                original_public_key=self.pre_known_original_public_key,
                puzzle_reveal=self.hidden_puzzle_info.puzzle,
                delegated_solution=hidden_puzzle_solution,
            ).as_program(),
        )
