from __future__ import annotations

from dataclasses import dataclass, field
from functools import cached_property
from typing import TYPE_CHECKING, ClassVar, Generic, TypeVar, cast

from chia_rs import Coin, CoinSpend
from chia_rs.sized_bytes import bytes32

from chia.types.blockchain_format.program import Program
from chia.types.coin_spend import make_spend
from chia.wallet.lineage_proof import LineageProof
from chia.wallet.puzzles.puzzle_drivers import InnerPuzzle, OuterPuzzle, SmartCoin
from chia.wallet.puzzles.singleton_top_layer_v1_1 import (
    SINGLETON_LAUNCHER,
    SINGLETON_LAUNCHER_HASH,
    SINGLETON_MOD,
    SINGLETON_MOD_HASH,
    solution_for_singleton,
)


@dataclass(kw_only=True, frozen=True)
class SingletonCorePuzzles:
    singleton_mod: Program = field(default_factory=lambda: SINGLETON_MOD)
    singleton_mod_hash_pre_computed: bytes32 | None = SINGLETON_MOD_HASH
    singleton_launcher: Program = field(default_factory=lambda: SINGLETON_LAUNCHER)
    singleton_launcher_hash_pre_computed: bytes32 | None = SINGLETON_LAUNCHER_HASH

    @cached_property
    def singleton_mod_hash(self) -> bytes32:
        if self.singleton_mod_hash_pre_computed is not None:
            return self.singleton_mod_hash_pre_computed
        else:
            return self.singleton_mod.get_tree_hash()

    @cached_property
    def singleton_launcher_hash(self) -> bytes32:
        if self.singleton_launcher_hash_pre_computed is not None:
            return self.singleton_launcher_hash_pre_computed
        else:
            return self.singleton_launcher.get_tree_hash()


@dataclass(kw_only=True, frozen=True)
class SingletonStruct:
    launcher_id: bytes32
    singleton_puzzles: SingletonCorePuzzles = SingletonCorePuzzles()

    def to_program(self) -> Program:
        return Program.to(
            (
                self.singleton_puzzles.singleton_mod_hash,
                (self.launcher_id, self.singleton_puzzles.singleton_launcher_hash),
            )
        )

    def struct_hash(self) -> bytes32:
        return self.to_program().get_tree_hash()


_T_InnerPuzzle = TypeVar("_T_InnerPuzzle", bound=InnerPuzzle)


@dataclass(kw_only=True, frozen=True)
class SingletonPuzzle(Generic[_T_InnerPuzzle]):
    if TYPE_CHECKING:
        _outer_puzzle_protocol_check: ClassVar[OuterPuzzle[InnerPuzzle]] = cast("SingletonPuzzle[_T_InnerPuzzle]", None)

    singleton_struct: SingletonStruct
    inner_puzzle: _T_InnerPuzzle

    @property
    def puzzle(self) -> Program:
        return self.singleton_struct.singleton_puzzles.singleton_mod.curry(
            self.singleton_struct.to_program(),
            self.inner_puzzle.puzzle,
        )

    @property
    def puzzle_hash(self) -> bytes32:
        return self.puzzle.get_tree_hash()


@dataclass(kw_only=True, frozen=True)
class Singleton(SingletonPuzzle[_T_InnerPuzzle]):
    if TYPE_CHECKING:
        _smart_coin_protocol_check: ClassVar[SmartCoin] = cast("Singleton[_T_InnerPuzzle]", None)

    coin: Coin
    lineage_proof: LineageProof

    def solution(self, inner_solution: Program) -> Program:
        return solution_for_singleton(
            lineage_proof=self.lineage_proof,
            amount=self.coin.amount,
            inner_solution=inner_solution,
        )

    def action_spend(self, inner_solution: Program) -> CoinSpend:
        return make_spend(
            coin=self.coin,
            puzzle_reveal=self.puzzle,
            solution=self.solution(inner_solution),
        )
