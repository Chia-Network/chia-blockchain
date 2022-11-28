from dataclasses import dataclass
from typing import List, TypeVar

from clvm_tools.binutils import disassemble

from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program
from chia.wallet.action_manager.protocols import WalletAction
from chia.wallet.puzzle_drivers import Solver


_T_Condition = TypeVar("_T_Condition", bound="Condition")


@dataclass(frozen=True)
class Condition:
    condition: Program

    @staticmethod
    def name() -> str:
        return "condition"

    @classmethod
    def from_solver(cls, solver: Solver) -> _T_Condition:
        return cls(Program.to(solver["condition"]))

    def to_solver(self) -> Solver:
        return Solver(
            {
                "type": self.name(),
                "condition": disassemble(self.condition),
            }
        )

    def augment(self, environment: Solver) -> WalletAction:
        return self


@dataclass(frozen=True)
class Graftroot:
    """
    The _wrapper members of this class take an inner puzzle/solution and return a new one to replace it
    """

    puzzle_wrapper: Program
    solution_wrapper: Program
    metadata: Program  # data to put in the spend but not sign (it can be deleted before hitting the chain)

    @staticmethod
    def name() -> str:
        return "graftroot"

    @classmethod
    def from_solver(cls, solver: Solver) -> _T_Condition:
        return cls(
            Program.to(solver["puzzle_wrapper"]), Program.to(solver["solution_wrapper"]), Program.to(solver["metadata"])
        )

    def to_solver(self) -> Solver:
        return Solver(
            {
                "type": self.name(),
                "puzzle_wrapper": disassemble(self.puzzle_wrapper),
                "solution_wrapper": disassemble(self.solution_wrapper),
                "metadata": disassemble(self.metadata),
            }
        )

    def augment(self, environment: Solver) -> WalletAction:
        if "graftroot_edits" in environment:
            for edit in environment["graftroot_edits"]:
                if edit["puzzle_wrapper"] == self.puzzle_wrapper:
                    return Graftroot.from_solver(edit)

        return self
