from typing_extensions import Protocol

from typing import Any, Callable, Dict, List


from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program
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


class OuterDriver(Protocol):
    def get_actions(self) -> Dict[str, Callable[[Any, Solver], WalletAction]]:
        ...

    def get_aliases(self) -> Dict[str, ActionAlias]:
        ...

    async def construct_outer_puzzle(self, inner_puzzle: Program) -> Program:
        ...

    async def construct_outer_solution(
        self, actions: List[WalletAction], inner_solution: Program, optimize: bool = False
    ) -> Program:
        ...

    async def check_and_modify_actions(
        self,
        coin: Coin,
        outer_actions: List[WalletAction],
        inner_actions: List[WalletAction],
    ) -> List[WalletAction]:
        ...


class InnerDriver(Protocol):
    def get_actions(self) -> Dict[str, Callable[[Any, Solver], WalletAction]]:
        ...

    def get_aliases(self) -> Dict[str, ActionAlias]:
        ...

    async def construct_inner_puzzle(self) -> Program:
        ...

    async def construct_inner_solution(self, actions: List[WalletAction], optimize: bool = False) -> Program:
        ...
