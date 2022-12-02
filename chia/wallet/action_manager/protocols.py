from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple, TypeVar, Union, runtime_checkable
from typing_extensions import Protocol

from blspy import G1Element

from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program
from chia.types.coin_spend import CoinSpend
from chia.wallet.puzzle_drivers import Solver


class WalletAction(Protocol):
    @staticmethod
    def name() -> str:
        ...

    @classmethod
    def from_solver(cls, solver: Solver) -> "WalletAction":
        ...

    def to_solver(self) -> Solver:
        ...


@runtime_checkable
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


_T_PuzzleSolutionDescription = TypeVar("_T_PuzzleSolutionDescription", bound="PuzzleSolutionDescription")


@runtime_checkable
class OuterDriver(Protocol):
    def get_actions(self) -> Dict[str, Callable[[Any, Solver], WalletAction]]:
        ...

    def get_aliases(self) -> Dict[str, ActionAlias]:
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
    async def match_spend(
        cls: Any, spend: CoinSpend, mod: Program, curried_args: Program
    ) -> Optional[Tuple[_T_PuzzleSolutionDescription, Program, Program]]:
        ...

    @staticmethod
    def get_asset_types(request: Solver) -> Solver:
        ...

    @staticmethod
    async def match_asset_types(asset_types: List[Solver]) -> bool:
        ...


@runtime_checkable
class InnerDriver(Protocol):
    def get_actions(self) -> Dict[str, Callable[[Any, Solver], WalletAction]]:
        ...

    def get_aliases(self) -> Dict[str, ActionAlias]:
        ...

    async def construct_inner_puzzle(self) -> Program:
        ...

    async def construct_inner_solution(
        self, actions: List[WalletAction], environment: Solver, optimize: bool = False
    ) -> Program:
        ...

    @staticmethod
    async def match_inner_puzzle_and_solution(
        cls,
        coin: Coin,
        puzzle: Program,
        solution: Program,
        mod: Program,
        curried_args: Program,
    ) -> Optional[_T_PuzzleSolutionDescription]:
        ...


@dataclass(frozen=True)
class PuzzleSolutionDescription:
    driver: Union[InnerDriver, OuterDriver]
    actions: List[WalletAction]
    signatures_required: List[Tuple[G1Element, bytes, bool]]
    coin_description: Solver
    environment: Solver


@dataclass(frozen=True)
class SpendDescription:
    coin: Coin
    outer_description: PuzzleSolutionDescription
    inner_description: PuzzleSolutionDescription

    def __post_init__(self) -> None:
        if not isinstance(self.outer_description.driver, OuterDriver):
            raise ValueError("Spend description created with wrong driver in outer description")
        if not isinstance(self.inner_description.driver, InnerDriver):
            raise ValueError("Spend description created with wrong driver in inner description")

    def get_all_actions(self) -> List[WalletAction]:
        return [*self.outer_description.actions, *self.inner_description.actions]

    def get_all_signatures(self) -> List[Tuple[G1Element, bytes, bool]]:
        return [*self.outer_description.signatures_required, *self.inner_description.signatures_required]

    def get_full_description(self) -> Solver:
        return Solver({**self.inner_description.coin_description.info, **self.outer_description.coin_description.info})

    def get_full_environment(self) -> Solver:
        return Solver({**self.inner_description.environment.info, **self.outer_description.environment.info})
