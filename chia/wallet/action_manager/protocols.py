from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple, Type, Union

from blspy import G1Element
from typing_extensions import Protocol

from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_spend import CoinSpend
from chia.wallet.puzzle_drivers import Solver
from chia.wallet.wallet_protocol import WalletProtocol


class WalletAction(Protocol):
    @staticmethod
    def name() -> str:
        ...

    @classmethod
    def from_solver(cls, solver: Solver) -> "WalletAction":
        ...

    def to_solver(self) -> Solver:
        ...

    def augment(self, environment: Solver) -> "WalletAction":
        ...

    def de_alias(self) -> "WalletAction":
        ...


class ActionAlias(Protocol):
    @staticmethod
    def name() -> str:
        ...

    @classmethod
    def from_solver(cls, solver: Solver) -> "ActionAlias":
        ...

    def to_solver(self) -> Solver:
        ...

    def de_alias(self) -> WalletAction:
        ...

    @staticmethod
    def action_name() -> str:
        ...

    @classmethod
    def from_action(cls, action: WalletAction) -> "ActionAlias":
        ...

    def augment(self, environment: Solver) -> WalletAction:
        ...


class OuterDriver(Protocol):
    # TODO: This is not great, we should move the coin selection logic in here
    @staticmethod
    def get_wallet_class() -> Type[WalletProtocol]:
        ...

    @staticmethod
    def type() -> bytes32:
        ...

    def get_actions(self) -> Dict[str, Type[WalletAction]]:
        ...

    def get_aliases(self) -> Dict[str, Type[ActionAlias]]:
        ...

    async def construct_outer_puzzle(self, inner_puzzle: Program) -> Program:
        ...

    async def construct_outer_solution(
        self, actions: List[WalletAction], inner_solution: Program, environment: Solver, optimize: bool = False
    ) -> Program:
        ...

    async def check_and_modify_actions(
        self,
        coin: Coin,
        outer_actions: List[WalletAction],
        inner_actions: List[WalletAction],
        environment: Solver,
    ) -> Tuple[List[WalletAction], List[WalletAction], Solver]:
        ...

    @classmethod
    async def match_puzzle(
        cls, puzzle: Program, mod: Program, curried_args: Program
    ) -> Optional[Tuple[PuzzleDescription, Program]]:
        ...

    @classmethod
    async def match_solution(cls, solution: Program) -> Optional[Tuple[SolutionDescription, Program]]:
        ...

    @staticmethod
    def get_asset_types(request: Solver) -> List[Solver]:
        ...

    @staticmethod
    async def match_asset_types(asset_types: List[Solver]) -> bool:
        ...


class InnerDriver(Protocol):
    @staticmethod
    def type() -> bytes32:
        ...

    def get_actions(self) -> Dict[str, Type[WalletAction]]:
        ...

    def get_aliases(self) -> Dict[str, Type[ActionAlias]]:
        ...

    async def construct_inner_puzzle(self) -> Program:
        ...

    async def construct_inner_solution(
        self, actions: List[WalletAction], environment: Solver, optimize: bool = False
    ) -> Program:
        ...

    @classmethod
    async def match_puzzle(
        cls, puzzle: Program, mod: Program, curried_args: Program
    ) -> Optional[PuzzleDescription]:
        ...

    @classmethod
    async def match_solution(cls, solution: Program) -> Optional[SolutionDescription]:
        ...

@dataclass(frozen=True)
class PuzzleDescription:
    driver: Union[InnerDriver, OuterDriver]
    coin_description: Solver


@dataclass(frozen=True)
class SolutionDescription:
    actions: List[WalletAction]
    signatures_required: List[Tuple[G1Element, bytes, bool]]
    environment: Solver


@dataclass(frozen=True)
class SpendDescription:
    coin: Coin
    outer_puzzle_description: PuzzleDescription
    outer_solution_description: SolutionDescription
    inner_puzzle_description: PuzzleDescription
    inner_solution_description: SolutionDescription

    def get_all_actions(self) -> List[WalletAction]:
        return [*self.outer_solution_description.actions, *self.inner_solution_description.actions]

    def get_all_signatures(self) -> List[Tuple[G1Element, bytes, bool]]:
        return [
            *self.outer_solution_description.signatures_required,
            *self.inner_solution_description.signatures_required,
        ]

    def get_full_description(self) -> Solver:
        return Solver(
            {
                **self.inner_puzzle_description.coin_description.info,
                **self.outer_puzzle_description.coin_description.info,
            }
        )

    def get_full_environment(self) -> Solver:
        return Solver(
            {**self.inner_solution_description.environment.info, **self.outer_solution_description.environment.info}
        )
