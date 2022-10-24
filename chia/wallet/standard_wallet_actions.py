from dataclasses import dataclass
from typing import List, TypeVar

from clvm_tools.binutils import disassemble

from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.hash import std_hash
from chia.wallet.payment import Payment
from chia.wallet.puzzle_drivers import cast_to_int, Solver
from chia.wallet.trading.offer import OFFER_MOD_HASH
from chia.wallet.puzzles.puzzle_utils import (
    make_assert_coin_announcement,
    make_assert_puzzle_announcement,
    make_create_coin_announcement,
    make_create_coin_condition,
    make_create_puzzle_announcement,
    make_reserve_fee_condition,
)

_T_DirectPayment = TypeVar("_T_DirectPayment", bound="DirectPayment")


@dataclass(frozen=True)
class DirectPayment:
    payment: Payment
    hints: List[bytes]

    @staticmethod
    def name() -> str:
        return "direct_payment"

    @classmethod
    def from_solver(cls, solver: Solver) -> _T_DirectPayment:
        return cls(
            Payment(
                solver["puzhash"], cast_to_int(solver_amount["amount"]), solver["memos"] if "memos" in solver else []
            ),
            solver["hints"] if "hints" in solver else [],
        )

    def to_solver(self) -> Solver:
        return Solver(
            {
                "type": self.name(),
                "payment": {
                    "puzhash": "0x" + self.payment.puzzle_hash.hex(),
                    "amount": str(self.payment.amount),
                    "hints": ["0x" + hint.hex() for hint in self.hints],
                    "memos": ["0x" + memo.hex() for memo in self.payment.memos],
                },
            }
        )

    def get_amount(self) -> int:
        return self.payment.amount

    def conditions(self) -> List[Program]:
        return [
            make_create_coin_condition(
                self.payment.puzzle_hash, self.payment.amount, [*self.hints, *self.payment.memos]
            )
        ]

    def get_action_solver(self) -> Solver:
        return Solver({})


_T_OfferedAmount = TypeVar("_T_OfferedAmount", bound="OfferedAmount")


@dataclass(frozen=True)
class OfferedAmount:
    amount: int

    @staticmethod
    def name() -> str:
        return "offered_amount"

    @classmethod
    def from_solver(cls, solver: Solver) -> _T_OfferedAmount:
        return cls(cast_to_int(solver["amount"]))

    def to_solver(self) -> Solver:
        return Solver(
            {
                "type": self.name(),
                "amount": str(self.amount),
            }
        )

    def get_amount(self) -> int:
        return self.amount

    def conditions(self) -> List[Program]:
        return [make_create_coin_condition(OFFER_MOD_HASH, self.amount, [])]

    def get_action_solver(self) -> Solver:
        return Solver({})


_T_Fee = TypeVar("_T_Fee", bound="Fee")


@dataclass(frozen=True)
class Fee:
    amount: int

    @staticmethod
    def name() -> str:
        return "fee"

    @classmethod
    def from_solver(cls, solver: Solver) -> _T_Fee:
        return cls(cast_to_int(solver["amount"]))

    def to_solver(self) -> Solver:
        return Solver(
            {
                "type": self.name(),
                "amount": str(self.amount),
            }
        )

    def get_amount(self) -> int:
        return self.amount

    def conditions(self) -> List[Program]:
        return [make_reserve_fee_condition(self.amount)]

    def get_action_solver(self) -> Solver:
        return Solver({})


_T_MakeAnnouncement = TypeVar("_T_MakeAnnouncement", bound="MakeAnnouncement")


@dataclass(frozen=True)
class MakeAnnouncement:
    type: str
    data: Program

    @staticmethod
    def name() -> str:
        return "make_announcement"

    def __post_init__(self) -> None:
        if self.type not in ["coin", "puzzle"]:
            raise ValueError(f"Invalid announcement type {self.type}")

    @classmethod
    def from_solver(cls, solver: Solver) -> _T_MakeAnnouncement:
        return cls(solver["announcement_type"], Program.to(solver["announcement_data"]))

    def to_solver(self) -> Solver:
        return Solver(
            {
                "type": self.name(),
                "announcement_type": self.type,
                "announcement_data": disassemble(self.data),
            }
        )

    def get_amount(self) -> int:
        return 0

    def conditions(self) -> List[Program]:
        if self.type == "puzzle":
            return [make_create_puzzle_announcement(self.data)]
        elif self.type == "coin":
            return [make_create_coin_announcement(self.data)]
        else:
            raise ValueError("Invalid announcement type")

    def get_action_solver(self) -> Solver:
        return Solver({})


_T_AssertAnnouncement = TypeVar("_T_AssertAnnouncement", bound="AssertAnnouncement")


@dataclass(frozen=True)
class AssertAnnouncement:
    type: str
    origin: bytes32
    data: Program

    @staticmethod
    def name() -> str:
        return "assert_announcement"

    def __post_init__(self) -> None:
        if self.type not in ["coin", "puzzle"]:
            raise ValueError(f"Invalid announcement type {self.type}")

    @classmethod
    def from_solver(cls, solver: Solver) -> _T_AssertAnnouncement:
        return cls(solver["announcement_type"], bytes32(solver["origin"]), Program.to(solver["announcement_data"]))

    def to_solver(self) -> Solver:
        return Solver(
            {
                "type": self.name(),
                "announcement_type": self.type,
                "origin": "0x" + self.origin,
                "announcement_data": disassemble(self.data),
            }
        )

    def get_amount(self) -> int:
        return 0

    def conditions(self) -> List[Program]:
        if self.type == "puzzle":
            return [make_assert_puzzle_announcement(std_hash(self.origin + self.data.as_python()))]
        elif self.type == "coin":
            return [make_assert_coin_announcement(std_hash(self.origin + self.data.as_python()))]
        else:
            raise ValueError("Invalid announcement type")

    def get_action_solver(self) -> Solver:
        return Solver({})


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

    def get_amount(self) -> int:
        return 0

    def conditions(self) -> List[Program]:
        if self.type == "puzzle":
            return [make_create_puzzle_announcement(self.data)]
        elif self.type == "coin":
            return [make_create_coin_announcement(self.data)]
        else:
            raise ValueError("Invalid announcement type")

    def get_action_solver(self) -> Solver:
        return Solver({})
