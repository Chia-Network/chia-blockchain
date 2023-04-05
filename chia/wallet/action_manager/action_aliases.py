from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Type, TypeVar

from clvm_tools.binutils import disassemble

from chia.types.announcement import Announcement
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.hash import std_hash
from chia.util.ints import uint64
from chia.wallet.action_manager.protocols import WalletAction
from chia.wallet.action_manager.wallet_actions import Condition, Graftroot
from chia.wallet.payment import Payment
from chia.wallet.puzzle_drivers import Solver, cast_to_int
from chia.wallet.puzzles.load_clvm import load_clvm
from chia.wallet.puzzles.puzzle_utils import (
    make_assert_coin_announcement,
    make_assert_puzzle_announcement,
    make_create_coin_announcement,
    make_create_coin_condition,
    make_create_puzzle_announcement,
    make_reserve_fee_condition,
)
from chia.wallet.trading.offer import OFFER_MOD, OFFER_MOD_HASH

ADD_WRAPPED_ANNOUNCEMENT = load_clvm("add_wrapped_announcement.clsp")
CURRY = load_clvm("curry.clsp")

_T_DirectPayment = TypeVar("_T_DirectPayment", bound="DirectPayment")
_T_OfferedAmount = TypeVar("_T_OfferedAmount", bound="OfferedAmount")
_T_Fee = TypeVar("_T_Fee", bound="Fee")
_T_MakeAnnouncement = TypeVar("_T_MakeAnnouncement", bound="MakeAnnouncement")
_T_AssertAnnouncement = TypeVar("_T_AssertAnnouncement", bound="AssertAnnouncement")
_T_RequestPayment = TypeVar("_T_RequestPayment", bound="RequestPayment")


@dataclass(frozen=True)
class DirectPayment:
    """An alias for CREATE_COIN"""

    payment: Payment
    hints: List[bytes]  # Hints are just additional memos that are guaranteed to get prepended

    @staticmethod
    def name() -> str:
        return "direct_payment"

    @classmethod
    def from_solver(cls: Type[_T_DirectPayment], solver: Solver) -> _T_DirectPayment:
        payment = solver["payment"]
        return cls(
            Payment(
                payment["puzhash"],
                uint64(cast_to_int(payment["amount"])),
                payment["memos"] if "memos" in payment else [],
            ),
            payment["hints"] if "hints" in payment else [],
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

    @staticmethod
    def action_name() -> str:
        return str(Condition.name())

    @classmethod
    def from_action(cls: Type[_T_DirectPayment], action: WalletAction) -> _T_DirectPayment:
        if not isinstance(action, Condition):
            raise ValueError("Can only parse a DirectPayment from Condition")

        puzzle_hash: bytes32 = bytes32(action.condition.at("rf").as_python())
        # Question: should we deliberately make this offer hash exception?  Maybe aliasing can go multiple levels?
        if action.condition.first() != Program.to(51) or puzzle_hash == OFFER_MOD_HASH:
            raise ValueError("Tried to parse a condition that was not a direct payment")

        memos: List[bytes] = (
            action.condition.at("rrrf").as_python() if action.condition.at("rrr") != Program.to(None) else []
        )

        return cls(
            Payment(puzzle_hash, uint64(action.condition.at("rrf").as_int()), memos),
            [],
        )

    def augment(self, environment: Solver) -> "DirectPayment":
        return DirectPayment(self.payment, self.hints)


@dataclass(frozen=True)
class OfferedAmount:
    """An alias for a CREATE_COIN that goes to the offer ph w/ no memos"""

    amount: int

    @staticmethod
    def name() -> str:
        return "offered_amount"

    @classmethod
    def from_solver(cls: Type[_T_OfferedAmount], solver: Solver) -> _T_OfferedAmount:
        return cls(cast_to_int(solver["amount"]))

    def to_solver(self) -> Solver:
        return Solver(
            {
                "type": self.name(),
                "amount": str(self.amount),
            }
        )

    def de_alias(self) -> Condition:
        return Condition(Program.to(make_create_coin_condition(OFFER_MOD_HASH, self.amount, [])))

    @staticmethod
    def action_name() -> str:
        return str(Condition.name())

    @classmethod
    def from_action(cls: Type[_T_OfferedAmount], action: WalletAction) -> _T_OfferedAmount:
        if not isinstance(action, Condition):
            raise ValueError("Can only parse a OfferedAmount from Condition")

        puzzle_hash: bytes32 = bytes32(action.condition.at("rf").as_python())
        if puzzle_hash != OFFER_MOD_HASH:
            raise ValueError("Tried to parse a condition that was not an offer payment")

        return cls(action.condition.at("rrf").as_int())

    def augment(self, environment: Solver) -> "OfferedAmount":
        return OfferedAmount(self.amount)


@dataclass(frozen=True)
class Fee:
    """An alias for RESERVE_FEE"""

    amount: int

    @staticmethod
    def name() -> str:
        return "fee"

    @classmethod
    def from_solver(cls: Type[_T_Fee], solver: Solver) -> _T_Fee:
        return cls(cast_to_int(solver["amount"]))

    def to_solver(self) -> Solver:
        return Solver(
            {
                "type": self.name(),
                "amount": str(self.amount),
            }
        )

    def de_alias(self) -> Condition:
        return Condition(Program.to(make_reserve_fee_condition(self.amount)))

    @staticmethod
    def action_name() -> str:
        return str(Condition.name())

    @classmethod
    def from_action(cls: Type[_T_Fee], action: WalletAction) -> _T_Fee:
        if not isinstance(action, Condition):
            raise ValueError("Can only parse a Fee from Condition")

        if action.condition.first() != Program.to(52):
            raise ValueError("Tried to parse a condition that was not a RESERVE_FEE")

        return cls(action.condition.at("rf").as_int())

    def augment(self, environment: Solver) -> "Fee":
        return Fee(self.amount)


@dataclass(frozen=True)
class MakeAnnouncement:
    """An alias for CREATE_*_ANNOUNCEMENT"""

    type: str  # coin | puzzle  # maybe should be enum?
    data: Program

    @staticmethod
    def name() -> str:
        return "make_announcement"

    def __post_init__(self) -> None:
        if self.type not in ["coin", "puzzle"]:
            raise ValueError(f"Invalid announcement type {self.type}")

    @classmethod
    def from_solver(cls: Type[_T_MakeAnnouncement], solver: Solver) -> _T_MakeAnnouncement:
        return cls(solver["announcement_type"], Program.to(solver["announcement_data"]))

    def to_solver(self) -> Solver:
        return Solver(
            {
                "type": self.name(),
                "announcement_type": self.type,
                "announcement_data": disassemble(self.data),
            }
        )

    def de_alias(self) -> Condition:
        if self.type == "puzzle":
            return Condition(Program.to(make_create_puzzle_announcement(self.data)))
        elif self.type == "coin":
            return Condition(Program.to(make_create_coin_announcement(self.data)))
        else:
            raise ValueError("Invalid announcement type")

    @staticmethod
    def action_name() -> str:
        return str(Condition.name())

    @classmethod
    def from_action(cls: Type[_T_MakeAnnouncement], action: WalletAction) -> _T_MakeAnnouncement:
        if not isinstance(action, Condition):
            raise ValueError("Can only parse a MakeAnnouncement from Condition")

        if action.condition.first() not in (Program.to(60), Program.to(62)):
            raise ValueError("Tried to parse a condition that was not a CREATE_*_ANNOUNCEMENT")

        return cls("coin" if action.condition.first() == Program.to(60) else "puzzle", action.condition.at("rf"))

    def augment(self, environment: Solver) -> "MakeAnnouncement":
        return MakeAnnouncement(self.type, self.data)


@dataclass(frozen=True)
class AssertAnnouncement:
    """An alias for ASSERT_*_ANNOUNCEMENT"""

    type: str
    # Maybe you know origin & data, but it's possible you only know hash(origin + data), in which case that will be data
    data: bytes
    origin: Optional[bytes32] = None

    @staticmethod
    def name() -> str:
        return "assert_announcement"

    def __post_init__(self) -> None:
        if self.type not in ["coin", "puzzle"]:
            raise ValueError(f"Invalid announcement type {self.type}")

    @classmethod
    def from_solver(cls: Type[_T_AssertAnnouncement], solver: Solver) -> _T_AssertAnnouncement:
        if "origin" in solver:
            data = solver["announcement_data"]
            origin = bytes32(solver["origin"])
        else:
            data = bytes32(solver["announcement_data"])
            origin = None
        return cls(solver["announcement_type"], data, origin)

    def to_solver(self) -> Solver:
        if self.origin is not None:
            origin_dict = {
                "origin": "0x" + self.origin.hex(),
            }
        else:
            origin_dict = {}
        return Solver(
            {
                **{
                    "type": self.name(),
                    "announcement_type": self.type,
                    "announcement_data": "0x" + self.data.hex(),
                },
                **origin_dict,
            }
        )

    def de_alias(self) -> Condition:
        data: bytes32 = bytes32(self.data) if self.origin is None else std_hash(self.origin + self.data)
        if self.type == "puzzle":
            return Condition(Program.to(make_assert_puzzle_announcement(data)))
        elif self.type == "coin":
            return Condition(Program.to(make_assert_coin_announcement(data)))
        else:
            raise ValueError("Invalid announcement type")

    @staticmethod
    def action_name() -> str:
        return str(Condition.name())

    @classmethod
    def from_action(cls: Type[_T_AssertAnnouncement], action: WalletAction) -> _T_AssertAnnouncement:
        if not isinstance(action, Condition):
            raise ValueError("Can only parse a AssertAnnouncement from Condition")

        if action.condition.first() not in (Program.to(61), Program.to(63)):
            raise ValueError("Tried to parse a condition that was not an ASSERT_*_ANNOUNCEMENT")

        return cls(
            "coin" if action.condition.first() == Program.to(61) else "puzzle", action.condition.at("rf").as_python()
        )

    def augment(self, environment: Solver) -> "AssertAnnouncement":
        return AssertAnnouncement(self.type, self.data, self.origin)


@dataclass(frozen=True)
class RequestPayment:
    """
    This is an alias for a graftroot action to request a payment that matches a format specified by "asset types"
    (For a full description of how asset types work see chia/wallet/puzzles/add_wrapped_announcement.clsp)

    It also takes an optional nonce to prevent a replay attack where two equivalent requests made by different coins
    could both be satisfied by only one completed payment. Two coins who request the same payments (or payments that
    may be a subset of each other) should use different nonces.

    In the case where the requested payment type is entirely specific (no solvable information), we do not pay the
    overhead for this relatively large program, we instead simplify the graftroot to a puzzle which simply prepends
    the inevitable condition to the output of the inner puzzle.
    """

    asset_types: List[Solver]
    nonce: Optional[bytes32]
    payments: List[Payment]

    @staticmethod
    def name() -> str:
        return "request_payment"

    @classmethod
    def from_solver(cls: Type[_T_RequestPayment], solver: Solver) -> _T_RequestPayment:
        return cls(
            solver["asset_types"],
            bytes32(solver["nonce"]) if "nonce" in solver else None,
            [Payment(bytes32(p["puzhash"]), uint64(cast_to_int(p["amount"])), p["memos"]) for p in solver["payments"]],
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
            solver_dict["nonce"] = "0x" + self.nonce.hex()
        return Solver(solver_dict)

    def de_alias(self) -> Graftroot:
        return Graftroot(
            self.construct_puzzle_wrapper(),
            Program.to(None),
            self.construct_metadata(),
        )

    def construct_announcement_assertion(self) -> Announcement:
        puzzle_reveal: Program = OFFER_MOD
        for typ in self.asset_types:
            puzzle_reveal = Program.to(
                # (a (q . mod) environment)
                [
                    2,
                    (1, typ["mod"]),
                    RequestPayment.build_environment(
                        typ["solution_template"], typ["committed_args"], typ["committed_args"], puzzle_reveal
                    ),
                ]
            )
        return Announcement(
            puzzle_reveal.get_tree_hash(),
            Program.to((self.nonce, [p.as_condition_args() for p in self.payments])).get_tree_hash(),
        )

    def construct_metadata(self) -> Program:
        metadata: Program = Program.to(
            (
                (self.nonce, [p.as_condition_args() for p in self.payments]),  # payment information
                # asset types
                [
                    [typ["mod"] for typ in self.asset_types],
                    [typ["solution_template"] for typ in self.asset_types],
                    [typ["committed_args"] for typ in self.asset_types],
                ],
            )
        )
        return metadata

    def construct_puzzle_wrapper(self) -> Program:
        if self.check_for_optimization():
            announcement: Announcement = self.construct_announcement_assertion()
            assertion: Program = Program.to([63, announcement.name()])
            # Return a program which runs the innerpuz with whatever solution exists for it, then prepends a condition
            # (mod (inner_puz) (qq (c (q . assertion) (a (q . (unquote inner_puz)) 1))))
            # (c (q . 4) (c (q 1 . "assertion") (c (c (q . 2) (c (c (q . 1) 2) (q 1))) ())))
            wrapper: Program = Program.to(
                [4, (1, 4), [4, (1, (1, assertion)), [4, [4, (1, 2), [4, [4, (1, 1), 2], [1, 1]]], []]]]
            )
            return wrapper
        else:
            # For optimization, the chialisp takes the already treehashed committed arguments
            # At this level, it makes more sense to be dealing with the pre-hashed arguments
            # So before we pass our committed args to the chialisp, we walk the tree and hash everything that is a leaf
            # (which we determine from the template)
            def walk_tree_and_hash_curried(tree: Program, template: Program) -> Program:
                if template.atom is None:
                    new_tree: Program = walk_tree_and_hash_curried(tree.first(), template.first()).cons(
                        walk_tree_and_hash_curried(tree.rest(), template.rest())
                    )
                elif template == Program.to(1):
                    new_tree = Program.to(tree.get_tree_hash())
                else:
                    new_tree = tree

                return new_tree

            return CURRY.curry(
                ADD_WRAPPED_ANNOUNCEMENT.curry(
                    [bytes32(Program.to(typ["mod"]).get_tree_hash()) for typ in self.asset_types],
                    [typ["solution_template"] for typ in self.asset_types],
                    [
                        walk_tree_and_hash_curried(typ["committed_args"], typ["solution_template"])
                        for typ in self.asset_types
                    ],
                    OFFER_MOD_HASH,
                    Program.to((self.nonce, [p.as_condition_args() for p in self.payments])).get_tree_hash(),
                )
            )

    def construct_solution_wrapper(self, solved_args: List[Program]) -> Program:
        if self.check_for_optimization():
            solution_wrapper: Program = Program.to(2)  # return exactly the solution
        else:
            solution_wrapper = Program.to([4, 2, [1, solved_args]])  # (c (f solution) (q solved_args))

        return solution_wrapper

    def check_for_optimization(self) -> bool:
        """
        If we're specifically requesting asset types that are fully complete, we can simplify this graftroot down to the
        condition it will invariably produce
        """
        return not any(["-1" in typ.info["solution_template"] for typ in self.asset_types])

    @classmethod
    def build_environment(
        cls, template: Program, committed_values: Program, solved_values: Program, puzzle_reveal: Program
    ) -> Program:
        """
        This method is a python implementation of what the chialisp does to construct the environment
        (with the small exception that it constructs the tree, not the treehash)
        """
        if template.atom is None:
            environment: Program = Program.to(
                [
                    4,
                    RequestPayment.build_environment(
                        template.first(), committed_values.first(), solved_values.first(), puzzle_reveal
                    ),
                    RequestPayment.build_environment(
                        template.rest(), committed_values.rest(), solved_values.rest(), puzzle_reveal
                    ),
                ]
            )
        elif template == Program.to(1):
            environment = Program.to((1, committed_values))
        elif template == Program.to(-1):
            environment = Program.to((1, solved_values))
        elif template == Program.to(0):
            environment = Program.to((1, puzzle_reveal))
        elif template == Program.to("$"):
            environment = Program.to(1)
        else:
            raise ValueError(f"Invalid atom in solution template: {template}")

        return environment

    @staticmethod
    def action_name() -> str:
        return str(Graftroot.name())

    @classmethod
    def from_action(cls: Type[_T_RequestPayment], action: WalletAction) -> _T_RequestPayment:
        if not isinstance(action, Graftroot):
            raise ValueError("Can only parse a RequestPayment from Graftroot")

        nonce_and_payments = action.metadata.first()
        nonce: Optional[bytes32] = (
            None if nonce_and_payments.first() == Program.to(None) else bytes32(nonce_and_payments.first().as_python())
        )
        payments: List[Payment] = [
            Payment.from_condition(Program.to((51, condition))) for condition in nonce_and_payments.rest().as_iter()
        ]
        mods: Program = action.metadata.at("rf")
        solution_templates: Program = action.metadata.at("rrf")
        committed_args: Program = action.metadata.at("rrrf")
        asset_types: List[Solver] = [
            Solver(
                {
                    "mod": disassemble(mod),
                    "solution_template": disassemble(template),
                    "committed_args": disassemble(committed),
                }
            )
            for mod, template, committed in zip(mods.as_iter(), solution_templates.as_iter(), committed_args.as_iter())
        ]

        return cls(asset_types, nonce, payments)

    def augment(self, environment: Solver) -> Graftroot:
        if "payment_types" in environment:
            # To complete this graftroot from the environment, we will simply ask for the asset types again,
            # this time with solved_args. If everything else matches this instance (types, nonce, payments),
            # that's how we know to use the specified solved args.
            for payment_type in environment["payment_types"]:
                nonce: Optional[bytes32] = (
                    None
                    if "nonce" not in payment_type or payment_type["nonce"] == Program.to(None)
                    else bytes32(payment_type["nonce"])
                )
                payments: List[Payment] = [
                    Payment(bytes32(p["puzhash"]), uint64(cast_to_int(p["amount"])), p["memos"])
                    for p in payment_type["payments"]
                ]
                asset_types: List[Solver] = payment_type["asset_types"] if "asset_types" in payment_type else []
                if (
                    nonce == self.nonce
                    and set(payments) == set(self.payments)
                    and len(asset_types) == len(self.asset_types)
                ):
                    solved_args: List[Program] = []
                    for new_type, static_type in zip(asset_types, self.asset_types):
                        if new_type["mod"] == static_type["mod"]:
                            solved_args.append(new_type["solved_args"])
                        else:
                            break
                    else:
                        return Graftroot(
                            self.construct_puzzle_wrapper(),
                            self.construct_solution_wrapper(solved_args),
                            self.construct_metadata(),
                        )
                    continue

        return Graftroot(
            self.construct_puzzle_wrapper(),
            # nothing specified means it will get optimized so it doesn't matter what we pass here
            self.construct_solution_wrapper([]),
            self.construct_metadata(),
        )
