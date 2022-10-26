from dataclasses import dataclass
from typing import List, Optional, Protocol, TypeVar

from clvm_tools.binutils import disassemble

from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.hash import std_hash
from chia.wallet.payment import Payment
from chia.wallet.puzzle_drivers import cast_to_int, Solver
from chia.wallet.trading.offer import ADD_WRAPPED_ANNOUNCEMENT, CURRY, OFFER_MOD_HASH
from chia.wallet.trading.wallet_actions import Condition, Graftroot, WalletAction
from chia.wallet.puzzles.puzzle_utils import (
    make_assert_coin_announcement,
    make_assert_puzzle_announcement,
    make_create_coin_announcement,
    make_create_coin_condition,
    make_create_puzzle_announcement,
    make_reserve_fee_condition,
)


class ActionAlias(Protocol):
    @staticmethod
    def name() -> str:
        ...

    @classmethod
    def from_solver(cls, solver: Solver) -> "WalletAction":
        ...

    def to_solver(self) -> Solver:
        ...

    def de_alias(self) -> WalletAction:
        ...


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

    def de_alias(self) -> WalletAction:
        return Condition(
            Program.to(
                make_create_coin_condition(
                    self.payment.puzzle_hash, self.payment.amount, [*self.hints, *self.payment.memos]
                )
            )
        )


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

    def de_alias(self) -> List[Program]:
        return Condition(Program.to(make_create_coin_condition(OFFER_MOD_HASH, self.amount, [])))


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

    def de_alias(self) -> List[Program]:
        return Condition(Program.to(make_reserve_fee_condition(self.amount)))


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

    def de_alias(self) -> List[Program]:
        if self.type == "puzzle":
            return Condition(Program.to(make_create_puzzle_announcement(self.data)))
        elif self.type == "coin":
            return Condition(Program.to(make_create_coin_announcement(self.data)))
        else:
            raise ValueError("Invalid announcement type")


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

    def de_alias(self) -> List[Program]:
        if self.type == "puzzle":
            return Condition(Program.to(make_assert_puzzle_announcement(std_hash(self.origin + self.data.as_python()))))
        elif self.type == "coin":
            return Condition(Program.to(make_assert_coin_announcement(std_hash(self.origin + self.data.as_python()))))
        else:
            raise ValueError("Invalid announcement type")


_T_RequestPayment = TypeVar("_T_RequestPayment", bound="RequestPayment")


@dataclass(frozen=True)
class RequestPayment:
    asset_types: List[Solver]
    nonce: Optional[bytes32]
    payments: List[Payment]

    @staticmethod
    def name() -> str:
        return "request_payment"

    @classmethod
    def from_solver(cls, solver: Solver) -> _T_RequestPayment:
        return cls(
            solver["asset_types"],
            bytes32(solver["nonce"]) if "nonce" in solver else None,
            [Payment(bytes32(p["puzhash"]), cast_to_int(p["amount"]), p["memos"]) for p in solver["payments"]],
        )

    def to_solver(self) -> Solver:
        solver_dict: Dict[str, Any] = {
            "type": self.name(),
            "asset_types": self.asset_types,
            "payments": [
                {
                    "puzhash": "0x" + p.puzzle_hash.hex(),
                    "amount": str(p.amount),
                    "memos": ["0x" + memo.hex() for memo in p.memos],
                }
                for p in self.payments
            ],
        }
        if self.nonce is not None:
            solver_dict["nonce"] = ("0x" + self.nonce.hex(),)
        return Solver(solver_dict)

    def de_alias(self) -> WalletAction:
        wrappers: List[Program] = []
        committed_args_list: List[Program] = []
        for fixed_typ in self.asset_types:
            committed_args: List[Any] = []
            _, wrapper, properties = REQUESTED_PAYMENT_PUZZLES[AssetType(fixed_typ["type"])]
            wrappers.append(wrapper)

            for prop in properties:
                if prop in fixed_typ:
                    committed_args.append(fixed_typ[prop])
                else:
                    committed_args.append(None)

            committed_args_list.append(Program.to(committed_args))

        NIL_LIST = Program.to([None] * len(wrappers))
        return Graftroot(
            CURRY.curry(
                ADD_WRAPPED_ANNOUNCEMENT.curry(
                    wrappers,
                    committed_args_list,
                    OFFER_MOD_HASH,
                    Program.to((self.nonce, [p.as_condition_args() for p in self.payments])),
                )
            ),
            Program.to([4, (1, NIL_LIST), 2]),  # (mod (inner_solution) (c NIL_LIST inner_solution))
        )
