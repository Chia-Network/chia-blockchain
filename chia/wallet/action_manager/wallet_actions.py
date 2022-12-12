from __future__ import annotations

from dataclasses import dataclass
from typing import Type, TypeVar

from clvm_tools.binutils import disassemble

from chia.types.blockchain_format.program import Program
from chia.wallet.puzzle_drivers import Solver

_T_Condition = TypeVar("_T_Condition", bound="Condition")
_T_Graftroot = TypeVar("_T_Graftroot", bound="Graftroot")

"""
See chia/wallet/protocols.py for descriptions of the methods on the following classes (WalletAction)
"""
@dataclass(frozen=True)
class Condition:
    condition: Program

    @staticmethod
    def name() -> str:
        return "condition"

    @classmethod
    def from_solver(cls: Type[_T_Condition], solver: Solver) -> "Condition":
        return cls(Program.to(solver["condition"]))

    def to_solver(self) -> Solver:
        return Solver(
            {
                "type": self.name(),
                "condition": disassemble(self.condition),
            }
        )

    def augment(self, environment: Solver) -> "Condition":
        return Condition(self.condition)

    def de_alias(self) -> "Condition":
        return Condition(self.condition)


@dataclass(frozen=True)
class Graftroot:
    """
    A graftroot action is the request to sign a puzzle to execute, some of whose parameters can be supplied later.
    This is useful for things like requested payments in which you may not know everything about the asset you are
    requesting, just that it needs match a certain format.

    In order to have multiple graftroot requirements in the standard inner puzzle (p2_delegated_puzzle_or_hidden_puzzle)
    in which there is only one "delegated_puzzle" (another name for graftroot) slot, each graftroot action must be
    able to take another graftroot action as it's "inner" puzzle. The innermost puzzle will likely be a quoted list of
    conditions.

    The *_wrapper members of this class take an inner puzzle/solution and return a wrapped puzzle to replace it
    """

    puzzle_wrapper: Program
    solution_wrapper: Program
    metadata: Program  # data to put in the spend but not sign (it can be deleted before hitting the chain)

    @staticmethod
    def name() -> str:
        return "graftroot"

    @classmethod
    def from_solver(cls: Type[_T_Graftroot], solver: Solver) -> "Graftroot":
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

    def augment(self, environment: Solver) -> "Graftroot":
        if "graftroot_edits" in environment:
            # The idea here is that you can just up and replace an existing graftroot
            # Changing the puzzle wrapper would result in an invalid signature,
            # so we use that as the hook to determine which graftroot we are editing
            for edit in environment["graftroot_edits"]:
                if edit["puzzle_wrapper"] == self.puzzle_wrapper:
                    return Graftroot.from_solver(edit)

        return Graftroot(self.puzzle_wrapper, self.solution_wrapper, self.metadata)

    def de_alias(self) -> "Graftroot":
        return Graftroot(self.puzzle_wrapper, self.solution_wrapper, self.metadata)
