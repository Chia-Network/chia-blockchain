from typing import List, Protocol

from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program
from chia.wallet.puzzle_drivers import Solver
from chia.wallet.trading.spend_dependencies import SpendDependency


class WalletAction(Protocol):
    @staticmethod
    def name() -> str:
        ...

    @classmethod
    def from_solver(cls, solver: Solver) -> "WalletAction":
        ...

    def to_solver(self) -> Solver:
        ...

    def get_amount(self) -> int:
        ...

    def conditions(self) -> List[Program]:
        ...

    def get_action_solver(self) -> Solver:
        ...
