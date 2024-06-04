from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, fields, replace
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple, Type, TypeVar, Union, final, get_type_hints

from chia_rs import G1Element
from clvm.casts import int_from_bytes, int_to_bytes

from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.condition_opcodes import ConditionOpcode
from chia.util.hash import std_hash
from chia.util.ints import uint8, uint32, uint64
from chia.util.streamable import Streamable, streamable

_T_Condition = TypeVar("_T_Condition", bound="Condition")


class Condition(Streamable, ABC):
    @abstractmethod
    def to_program(self) -> Program: ...

    @classmethod
    @abstractmethod
    def from_program(cls: Type[_T_Condition], program: Program) -> _T_Condition: ...


@final
@streamable
@dataclass(frozen=True)
class AggSigParent(Condition):
    pubkey: G1Element
    msg: bytes
    parent_id: Optional[bytes32] = None

    def to_program(self) -> Program:
        condition: Program = Program.to([ConditionOpcode.AGG_SIG_PARENT, self.pubkey.to_bytes(), self.msg])
        return condition

    @classmethod
    def from_program(cls, program: Program, parent_id: Optional[bytes32] = None) -> AggSigParent:
        return cls(
            G1Element.from_bytes(program.at("rf").as_atom()),
            program.at("rrf").as_atom(),
            parent_id,
        )


@final
@streamable
@dataclass(frozen=True)
class AggSigPuzzle(Condition):
    pubkey: G1Element
    msg: bytes
    puzzle_hash: Optional[bytes32] = None

    def to_program(self) -> Program:
        condition: Program = Program.to([ConditionOpcode.AGG_SIG_PUZZLE, self.pubkey.to_bytes(), self.msg])
        return condition

    @classmethod
    def from_program(cls, program: Program, puzzle_hash: Optional[bytes32] = None) -> AggSigPuzzle:
        return cls(
            G1Element.from_bytes(program.at("rf").as_atom()),
            program.at("rrf").as_atom(),
            puzzle_hash,
        )


@final
@streamable
@dataclass(frozen=True)
class AggSigAmount(Condition):
    pubkey: G1Element
    msg: bytes
    amount: Optional[uint64] = None

    def to_program(self) -> Program:
        condition: Program = Program.to([ConditionOpcode.AGG_SIG_AMOUNT, self.pubkey.to_bytes(), self.msg])
        return condition

    @classmethod
    def from_program(cls, program: Program, amount: Optional[uint64] = None) -> AggSigAmount:
        return cls(
            G1Element.from_bytes(program.at("rf").as_atom()),
            program.at("rrf").as_atom(),
            amount,
        )


@final
@streamable
@dataclass(frozen=True)
class AggSigPuzzleAmount(Condition):
    pubkey: G1Element
    msg: bytes
    puzzle_hash: Optional[bytes32] = None
    amount: Optional[uint64] = None

    def to_program(self) -> Program:
        condition: Program = Program.to([ConditionOpcode.AGG_SIG_PUZZLE_AMOUNT, self.pubkey.to_bytes(), self.msg])
        return condition

    @classmethod
    def from_program(
        cls,
        program: Program,
        puzzle_hash: Optional[bytes32] = None,
        amount: Optional[uint64] = None,
    ) -> AggSigPuzzleAmount:
        return cls(
            G1Element.from_bytes(program.at("rf").as_atom()),
            program.at("rrf").as_atom(),
            puzzle_hash,
            amount,
        )


@final
@streamable
@dataclass(frozen=True)
class AggSigParentAmount(Condition):
    pubkey: G1Element
    msg: bytes
    parent_id: Optional[bytes32] = None
    amount: Optional[uint64] = None

    def to_program(self) -> Program:
        condition: Program = Program.to([ConditionOpcode.AGG_SIG_PARENT_AMOUNT, self.pubkey.to_bytes(), self.msg])
        return condition

    @classmethod
    def from_program(
        cls,
        program: Program,
        parent_id: Optional[bytes32] = None,
        amount: Optional[uint64] = None,
    ) -> AggSigParentAmount:
        return cls(
            G1Element.from_bytes(program.at("rf").as_atom()),
            program.at("rrf").as_atom(),
            parent_id,
            amount,
        )


@final
@streamable
@dataclass(frozen=True)
class AggSigParentPuzzle(Condition):
    pubkey: G1Element
    msg: bytes
    parent_id: Optional[bytes32] = None
    puzzle_hash: Optional[bytes32] = None

    def to_program(self) -> Program:
        condition: Program = Program.to([ConditionOpcode.AGG_SIG_PARENT_PUZZLE, self.pubkey.to_bytes(), self.msg])
        return condition

    @classmethod
    def from_program(
        cls,
        program: Program,
        parent_id: Optional[bytes32] = None,
        puzzle_hash: Optional[bytes32] = None,
    ) -> AggSigParentPuzzle:
        return cls(
            G1Element.from_bytes(program.at("rf").as_atom()),
            program.at("rrf").as_atom(),
            parent_id,
            puzzle_hash,
        )


@final
@streamable
@dataclass(frozen=True)
class AggSigUnsafe(Condition):
    pubkey: G1Element
    msg: bytes

    def to_program(self) -> Program:
        condition: Program = Program.to([ConditionOpcode.AGG_SIG_UNSAFE, self.pubkey.to_bytes(), self.msg])
        return condition

    @classmethod
    def from_program(cls, program: Program) -> AggSigUnsafe:
        return cls(
            G1Element.from_bytes(program.at("rf").as_atom()),
            program.at("rrf").as_atom(),
        )


@final
@streamable
@dataclass(frozen=True)
class AggSigMe(Condition):
    pubkey: G1Element
    msg: bytes
    coin_id: Optional[bytes32] = None
    additional_data: Optional[bytes32] = None

    def to_program(self) -> Program:
        condition: Program = Program.to([ConditionOpcode.AGG_SIG_ME, self.pubkey.to_bytes(), self.msg])
        return condition

    @classmethod
    def from_program(
        cls,
        program: Program,
        coin_id: Optional[bytes32] = None,
        additional_data: Optional[bytes32] = None,
    ) -> AggSigMe:
        return cls(
            G1Element.from_bytes(program.at("rf").as_atom()),
            program.at("rrf").as_atom(),
            coin_id,
            additional_data,
        )


@final
@streamable
@dataclass(frozen=True)
class CreateCoin(Condition):
    puzzle_hash: bytes32
    amount: uint64
    memos: Optional[List[bytes]] = None

    def to_program(self) -> Program:
        condition_args = [ConditionOpcode.CREATE_COIN, self.puzzle_hash, self.amount]
        if self.memos is not None:
            condition_args.append(self.memos)
        condition: Program = Program.to(condition_args)
        return condition

    @classmethod
    def from_program(cls, program: Program) -> CreateCoin:
        potential_memos: Program = program.at("rrr")
        return cls(
            bytes32(program.at("rf").as_atom()),
            uint64(program.at("rrf").as_int()),
            (
                None
                if potential_memos == Program.to(None)
                else [memo.as_atom() for memo in potential_memos.at("f").as_iter()]
            ),
        )


@final
@streamable
@dataclass(frozen=True)
class ReserveFee(Condition):
    amount: uint64

    def to_program(self) -> Program:
        condition: Program = Program.to([ConditionOpcode.RESERVE_FEE, self.amount])
        return condition

    @classmethod
    def from_program(cls, program: Program) -> ReserveFee:
        return cls(
            uint64(program.at("rf").as_int()),
        )


@final
@streamable
@dataclass(frozen=True)
class AssertCoinAnnouncement(Condition):
    msg: Optional[bytes32] = None
    asserted_id: Optional[bytes32] = None
    asserted_msg: Optional[bytes] = None

    def __post_init__(self) -> None:
        if self.msg is None and (self.asserted_id is None or self.asserted_msg is None):
            raise ValueError("Must specify either the complete announcement message or both of its components")

    @property
    def msg_calc(self) -> bytes32:
        if self.msg is None:
            # Our __post_init__ assures us these are not None
            return std_hash(self.asserted_id + self.asserted_msg)  # type: ignore[operator]
        else:
            return self.msg

    def corresponding_creation(self) -> CreateCoinAnnouncement:
        if self.asserted_msg is None:
            raise ValueError("Cannot create coin announcement creation without asserted_msg")
        else:
            return CreateCoinAnnouncement(self.asserted_msg, self.asserted_id)

    def to_program(self) -> Program:
        condition: Program = Program.to([ConditionOpcode.ASSERT_COIN_ANNOUNCEMENT, self.msg_calc])
        return condition

    @classmethod
    def from_program(
        cls,
        program: Program,
        asserted_id: Optional[bytes32] = None,
        asserted_msg: Optional[bytes] = None,
    ) -> AssertCoinAnnouncement:
        return cls(
            bytes32(program.at("rf").as_atom()),
            asserted_id,
            asserted_msg,
        )


@final
@streamable
@dataclass(frozen=True)
class CreateCoinAnnouncement(Condition):
    msg: bytes
    coin_id: Optional[bytes32] = None

    def corresponding_assertion(self) -> AssertCoinAnnouncement:
        if self.coin_id is None:
            raise ValueError("Cannot create coin announcement assertion without coin_id")
        else:
            return AssertCoinAnnouncement(asserted_id=self.coin_id, asserted_msg=self.msg)

    def to_program(self) -> Program:
        condition: Program = Program.to([ConditionOpcode.CREATE_COIN_ANNOUNCEMENT, self.msg])
        return condition

    @classmethod
    def from_program(cls, program: Program, coin_id: Optional[bytes32] = None) -> CreateCoinAnnouncement:
        return cls(
            program.at("rf").as_atom(),
            coin_id,
        )


@final
@streamable
@dataclass(frozen=True)
class AssertPuzzleAnnouncement(Condition):
    msg: Optional[bytes32] = None
    asserted_ph: Optional[bytes32] = None
    asserted_msg: Optional[bytes] = None

    def __post_init__(self) -> None:
        if self.msg is None and (self.asserted_ph is None or self.asserted_msg is None):
            raise ValueError("Must specify either the complete announcement message or both of its components")

    @property
    def msg_calc(self) -> bytes32:
        if self.msg is None:
            # Our __post_init__ assures us these are not None
            return std_hash(self.asserted_ph + self.asserted_msg)  # type: ignore[operator]
        else:
            return self.msg

    def corresponding_creation(self) -> CreatePuzzleAnnouncement:
        if self.asserted_msg is None:
            raise ValueError("Cannot create puzzle announcement creation without asserted_msg")
        else:
            return CreatePuzzleAnnouncement(self.asserted_msg, self.asserted_ph)

    def to_program(self) -> Program:
        condition: Program = Program.to([ConditionOpcode.ASSERT_PUZZLE_ANNOUNCEMENT, self.msg_calc])
        return condition

    @classmethod
    def from_program(
        cls,
        program: Program,
        asserted_ph: Optional[bytes32] = None,
        asserted_msg: Optional[bytes] = None,
    ) -> AssertPuzzleAnnouncement:
        return cls(
            bytes32(program.at("rf").as_atom()),
            asserted_ph,
            asserted_msg,
        )


@final
@streamable
@dataclass(frozen=True)
class CreatePuzzleAnnouncement(Condition):
    msg: bytes
    puzzle_hash: Optional[bytes32] = None

    def corresponding_assertion(self) -> AssertPuzzleAnnouncement:
        if self.puzzle_hash is None:
            raise ValueError("Cannot create puzzle announcement assertion without puzzle_hash")
        else:
            return AssertPuzzleAnnouncement(asserted_ph=self.puzzle_hash, asserted_msg=self.msg)

    def to_program(self) -> Program:
        condition: Program = Program.to([ConditionOpcode.CREATE_PUZZLE_ANNOUNCEMENT, self.msg])
        return condition

    @classmethod
    def from_program(cls, program: Program, puzzle_hash: Optional[bytes32] = None) -> CreatePuzzleAnnouncement:
        return cls(
            program.at("rf").as_atom(),
            puzzle_hash,
        )


@final
@streamable
@dataclass(frozen=True)
class SendMessage(Condition):
    mode: uint8
    msg: bytes
    args: Program

    def to_program(self) -> Program:
        condition: Program = Program.to([ConditionOpcode.SEND_MESSAGE, self.mode, self.msg, self.args])
        return condition

    @classmethod
    def from_program(cls, program: Program) -> SendMessage:
        return cls(
            uint8(program.at("rf").as_int()),
            program.at("rrf").as_atom(),
            program.at("rrrf"),
        )


@final
@streamable
@dataclass(frozen=True)
class ReceiveMessage(Condition):
    mode: uint8
    msg: bytes
    args: Program

    def to_program(self) -> Program:
        condition: Program = Program.to([ConditionOpcode.RECEIVE_MESSAGE, self.mode, self.msg, self.args])
        return condition

    @classmethod
    def from_program(cls, program: Program) -> ReceiveMessage:
        return cls(
            uint8(program.at("rf").as_int()),
            program.at("rrf").as_atom(),
            program.at("rrrf"),
        )


@final
@streamable
@dataclass(frozen=True)
class AssertConcurrentSpend(Condition):
    coin_id: bytes32

    def to_program(self) -> Program:
        condition: Program = Program.to([ConditionOpcode.ASSERT_CONCURRENT_SPEND, self.coin_id])
        return condition

    @classmethod
    def from_program(cls, program: Program) -> AssertConcurrentSpend:
        return cls(
            bytes32(program.at("rf").as_atom()),
        )


@final
@streamable
@dataclass(frozen=True)
class AssertConcurrentPuzzle(Condition):
    puzzle_hash: bytes32

    def to_program(self) -> Program:
        condition: Program = Program.to([ConditionOpcode.ASSERT_CONCURRENT_PUZZLE, self.puzzle_hash])
        return condition

    @classmethod
    def from_program(cls, program: Program) -> AssertConcurrentPuzzle:
        return cls(
            bytes32(program.at("rf").as_atom()),
        )


@final
@streamable
@dataclass(frozen=True)
class AssertMyCoinID(Condition):
    coin_id: bytes32

    def to_program(self) -> Program:
        condition: Program = Program.to([ConditionOpcode.ASSERT_MY_COIN_ID, self.coin_id])
        return condition

    @classmethod
    def from_program(cls, program: Program) -> AssertMyCoinID:
        return cls(
            bytes32(program.at("rf").as_atom()),
        )


@final
@streamable
@dataclass(frozen=True)
class AssertMyParentID(Condition):
    coin_id: bytes32

    def to_program(self) -> Program:
        condition: Program = Program.to([ConditionOpcode.ASSERT_MY_PARENT_ID, self.coin_id])
        return condition

    @classmethod
    def from_program(cls, program: Program) -> AssertMyParentID:
        return cls(
            bytes32(program.at("rf").as_atom()),
        )


@final
@streamable
@dataclass(frozen=True)
class AssertMyPuzzleHash(Condition):
    puzzle_hash: bytes32

    def to_program(self) -> Program:
        condition: Program = Program.to([ConditionOpcode.ASSERT_MY_PUZZLEHASH, self.puzzle_hash])
        return condition

    @classmethod
    def from_program(cls, program: Program) -> AssertMyPuzzleHash:
        return cls(
            bytes32(program.at("rf").as_atom()),
        )


@final
@streamable
@dataclass(frozen=True)
class AssertMyAmount(Condition):
    amount: uint64

    def to_program(self) -> Program:
        condition: Program = Program.to([ConditionOpcode.ASSERT_MY_AMOUNT, self.amount])
        return condition

    @classmethod
    def from_program(cls, program: Program) -> AssertMyAmount:
        return cls(
            uint64(program.at("rf").as_int()),
        )


@final
@streamable
@dataclass(frozen=True)
class AssertMyBirthSeconds(Condition):
    seconds: uint64

    def to_program(self) -> Program:
        condition: Program = Program.to([ConditionOpcode.ASSERT_MY_BIRTH_SECONDS, self.seconds])
        return condition

    @classmethod
    def from_program(cls, program: Program) -> AssertMyBirthSeconds:
        return cls(
            uint64(program.at("rf").as_int()),
        )


@final
@streamable
@dataclass(frozen=True)
class AssertMyBirthHeight(Condition):
    height: uint32

    def to_program(self) -> Program:
        condition: Program = Program.to([ConditionOpcode.ASSERT_MY_BIRTH_HEIGHT, self.height])
        return condition

    @classmethod
    def from_program(cls, program: Program) -> AssertMyBirthHeight:
        return cls(
            uint32(program.at("rf").as_int()),
        )


@final
@streamable
@dataclass(frozen=True)
class AssertEphemeral(Condition):
    def to_program(self) -> Program:
        condition: Program = Program.to([ConditionOpcode.ASSERT_EPHEMERAL])
        return condition

    @classmethod
    def from_program(cls, program: Program) -> AssertEphemeral:
        return cls()


@final
@streamable
@dataclass(frozen=True)
class AssertSecondsRelative(Condition):
    seconds: uint64

    def to_program(self) -> Program:
        condition: Program = Program.to([ConditionOpcode.ASSERT_SECONDS_RELATIVE, self.seconds])
        return condition

    @classmethod
    def from_program(cls, program: Program) -> AssertSecondsRelative:
        return cls(
            uint64(program.at("rf").as_int()),
        )


@final
@streamable
@dataclass(frozen=True)
class AssertSecondsAbsolute(Condition):
    seconds: uint64

    def to_program(self) -> Program:
        condition: Program = Program.to([ConditionOpcode.ASSERT_SECONDS_ABSOLUTE, self.seconds])
        return condition

    @classmethod
    def from_program(cls, program: Program) -> AssertSecondsAbsolute:
        return cls(
            uint64(program.at("rf").as_int()),
        )


@final
@streamable
@dataclass(frozen=True)
class AssertHeightRelative(Condition):
    height: uint32

    def to_program(self) -> Program:
        condition: Program = Program.to([ConditionOpcode.ASSERT_HEIGHT_RELATIVE, self.height])
        return condition

    @classmethod
    def from_program(cls, program: Program) -> AssertHeightRelative:
        return cls(
            uint32(program.at("rf").as_int()),
        )


@final
@streamable
@dataclass(frozen=True)
class AssertHeightAbsolute(Condition):
    height: uint32

    def to_program(self) -> Program:
        condition: Program = Program.to([ConditionOpcode.ASSERT_HEIGHT_ABSOLUTE, self.height])
        return condition

    @classmethod
    def from_program(cls, program: Program) -> AssertHeightAbsolute:
        return cls(
            uint32(program.at("rf").as_int()),
        )


@final
@streamable
@dataclass(frozen=True)
class AssertBeforeSecondsRelative(Condition):
    seconds: uint64

    def to_program(self) -> Program:
        condition: Program = Program.to([ConditionOpcode.ASSERT_BEFORE_SECONDS_RELATIVE, self.seconds])
        return condition

    @classmethod
    def from_program(cls, program: Program) -> AssertBeforeSecondsRelative:
        return cls(
            uint64(program.at("rf").as_int()),
        )


@final
@streamable
@dataclass(frozen=True)
class AssertBeforeSecondsAbsolute(Condition):
    seconds: uint64

    def to_program(self) -> Program:
        condition: Program = Program.to([ConditionOpcode.ASSERT_BEFORE_SECONDS_ABSOLUTE, self.seconds])
        return condition

    @classmethod
    def from_program(cls, program: Program) -> AssertBeforeSecondsAbsolute:
        return cls(
            uint64(program.at("rf").as_int()),
        )


@final
@streamable
@dataclass(frozen=True)
class AssertBeforeHeightRelative(Condition):
    height: uint32

    def to_program(self) -> Program:
        condition: Program = Program.to([ConditionOpcode.ASSERT_BEFORE_HEIGHT_RELATIVE, self.height])
        return condition

    @classmethod
    def from_program(cls, program: Program) -> AssertBeforeHeightRelative:
        return cls(
            uint32(program.at("rf").as_int()),
        )


@final
@streamable
@dataclass(frozen=True)
class AssertBeforeHeightAbsolute(Condition):
    height: uint32

    def to_program(self) -> Program:
        condition: Program = Program.to([ConditionOpcode.ASSERT_BEFORE_HEIGHT_ABSOLUTE, self.height])
        return condition

    @classmethod
    def from_program(cls, program: Program) -> AssertBeforeHeightAbsolute:
        return cls(
            uint32(program.at("rf").as_int()),
        )


@final
@streamable
@dataclass(frozen=True)
class Softfork(Condition):
    cost: uint64
    conditions: List[Program]

    def to_program(self) -> Program:
        condition: Program = Program.to([ConditionOpcode.SOFTFORK, self.cost, self.conditions])
        return condition

    @classmethod
    def from_program(cls, program: Program) -> Softfork:
        return cls(
            uint64(program.at("rf").as_int()),
            list(program.at("rrf").as_iter()),
        )


@final
@streamable
@dataclass(frozen=True)
class Remark(Condition):
    rest: Program

    def to_program(self) -> Program:
        condition: Program = Program.to((ConditionOpcode.REMARK, self.rest))
        return condition

    @classmethod
    def from_program(cls, program: Program) -> Remark:
        return cls(
            program.at("r"),
        )


@final
@streamable
@dataclass(frozen=True)
class UnknownCondition(Condition):
    opcode: Program
    args: List[Program]

    def to_program(self) -> Program:
        return self.opcode.cons(Program.to(self.args))

    @classmethod
    def from_program(cls, program: Program) -> UnknownCondition:
        return cls(
            program.at("f"), [] if program.at("r") == Program.to(None) else [p for p in program.at("r").as_iter()]
        )


# Abstractions
@final
@streamable
@dataclass(frozen=True)
class AggSig(Condition):
    pubkey: G1Element
    msg: bytes
    opcode: bytes = ConditionOpcode.AGG_SIG_ME.value
    coin_id: Optional[bytes32] = None
    parent_id: Optional[bytes32] = None
    puzzle_hash: Optional[bytes32] = None
    amount: Optional[uint64] = None
    additional_data: Optional[bytes32] = None

    def to_program(self) -> Program:
        # We know we are an agg sig or we want to error
        return CONDITION_DRIVERS[self.opcode](self.pubkey.to_bytes(), self.msg).to_program()  # type: ignore[call-arg]

    @classmethod
    def from_program(cls, program: Program, **kwargs: Optional[Union[uint64, bytes32]]) -> AggSig:
        opcode: bytes = program.at("f").as_atom()
        condition_driver: Condition = CONDITION_DRIVERS[opcode].from_program(program, **kwargs)
        return cls(
            # We are either parsing an agg sig condition, all of which have these, or we want to error
            condition_driver.pubkey,  # type: ignore[attr-defined]
            condition_driver.msg,  # type: ignore[attr-defined]
            opcode,
            **{key: value for key, value in condition_driver.__dict__.items() if key not in ["pubkey", "msg"]},
        )


@final
@streamable
@dataclass(frozen=True)
class CreateAnnouncement(Condition):
    msg: bytes
    coin_not_puzzle: bool
    origin_id: Optional[bytes32] = None

    def corresponding_assertion(self) -> AssertAnnouncement:
        if self.origin_id is None:
            raise ValueError("Cannot create coin announcement assertion without origin_id")
        else:
            return AssertAnnouncement(self.coin_not_puzzle, asserted_origin_id=self.origin_id, asserted_msg=self.msg)

    def to_program(self) -> Program:
        if self.coin_not_puzzle:
            return CreateCoinAnnouncement(self.msg, self.origin_id).to_program()
        else:
            return CreatePuzzleAnnouncement(self.msg, self.origin_id).to_program()

    @classmethod
    def from_program(cls, program: Program, **kwargs: Optional[bytes32]) -> CreateAnnouncement:
        if program.at("f").as_atom() == ConditionOpcode.CREATE_COIN_ANNOUNCEMENT:
            coin_not_puzzle: bool = True
            condition: Union[CreateCoinAnnouncement, CreatePuzzleAnnouncement] = CreateCoinAnnouncement.from_program(
                program, **kwargs
            )
            assert isinstance(condition, CreateCoinAnnouncement)
            origin_id: Optional[bytes32] = condition.coin_id
        else:
            coin_not_puzzle = False
            condition = CreatePuzzleAnnouncement.from_program(program, **kwargs)
            assert isinstance(condition, CreatePuzzleAnnouncement)
            origin_id = condition.puzzle_hash
        return cls(
            condition.msg,
            coin_not_puzzle,
            origin_id,
        )


@final
@streamable
@dataclass(frozen=True)
class AssertAnnouncement(Condition):
    coin_not_puzzle: bool
    msg: Optional[bytes32] = None
    asserted_origin_id: Optional[bytes32] = None
    asserted_msg: Optional[bytes] = None

    def __post_init__(self) -> None:
        if self.msg is None and (self.asserted_origin_id is None or self.asserted_msg is None):
            raise ValueError("Must specify either the complete announcement message or both of its components")

    @property
    def msg_calc(self) -> bytes32:
        if self.msg is None:
            # Our __post_init__ assures us these are not None
            return std_hash(self.asserted_origin_id + self.asserted_msg)  # type: ignore[operator]
        else:
            return self.msg

    def to_program(self) -> Program:
        if self.coin_not_puzzle:
            return AssertCoinAnnouncement(self.msg_calc, self.asserted_origin_id, self.asserted_msg).to_program()
        else:
            return AssertPuzzleAnnouncement(self.msg_calc, self.asserted_origin_id, self.asserted_msg).to_program()

    def corresponding_creation(self) -> CreateAnnouncement:
        if self.asserted_msg is None:
            raise ValueError("Cannot create coin announcement creation without asserted_msg")
        else:
            return CreateAnnouncement(self.asserted_msg, self.coin_not_puzzle, self.asserted_origin_id)

    @classmethod
    def from_program(cls, program: Program, **kwargs: Optional[bytes32]) -> AssertAnnouncement:
        if program.at("f").as_atom() == ConditionOpcode.ASSERT_COIN_ANNOUNCEMENT:
            coin_not_puzzle: bool = True
            condition: Union[AssertCoinAnnouncement, AssertPuzzleAnnouncement] = AssertCoinAnnouncement.from_program(
                program, **kwargs
            )
            assert isinstance(condition, AssertCoinAnnouncement)
            asserted_origin_id: Optional[bytes32] = condition.asserted_id
        else:
            coin_not_puzzle = False
            condition = AssertPuzzleAnnouncement.from_program(program, **kwargs)
            assert isinstance(condition, AssertPuzzleAnnouncement)
            asserted_origin_id = condition.asserted_ph
        return cls(
            coin_not_puzzle,
            condition.msg_calc,
            asserted_origin_id,
            condition.asserted_msg,
        )


TIMELOCK_TYPES = Union[
    AssertSecondsRelative,
    AssertHeightRelative,
    AssertSecondsAbsolute,
    AssertHeightAbsolute,
    AssertBeforeSecondsRelative,
    AssertBeforeHeightRelative,
    AssertBeforeSecondsAbsolute,
    AssertBeforeHeightAbsolute,
]


TIMELOCK_DRIVERS: Tuple[
    Type[TIMELOCK_TYPES],
    Type[TIMELOCK_TYPES],
    Type[TIMELOCK_TYPES],
    Type[TIMELOCK_TYPES],
    Type[TIMELOCK_TYPES],
    Type[TIMELOCK_TYPES],
    Type[TIMELOCK_TYPES],
    Type[TIMELOCK_TYPES],
] = (
    AssertSecondsRelative,
    AssertHeightRelative,
    AssertSecondsAbsolute,
    AssertHeightAbsolute,
    AssertBeforeSecondsRelative,
    AssertBeforeHeightRelative,
    AssertBeforeSecondsAbsolute,
    AssertBeforeHeightAbsolute,
)
SECONDS_TIMELOCK_DRIVERS: Set[Type[TIMELOCK_TYPES]] = {
    AssertSecondsRelative,
    AssertSecondsAbsolute,
    AssertBeforeSecondsRelative,
    AssertBeforeSecondsAbsolute,
}
HEIGHT_TIMELOCK_DRIVERS: Set[Type[TIMELOCK_TYPES]] = {
    AssertHeightRelative,
    AssertHeightAbsolute,
    AssertBeforeHeightRelative,
    AssertBeforeHeightAbsolute,
}
AFTER_TIMELOCK_DRIVERS: Set[Type[TIMELOCK_TYPES]] = {
    AssertSecondsRelative,
    AssertHeightRelative,
    AssertSecondsAbsolute,
    AssertHeightAbsolute,
}
BEFORE_TIMELOCK_DRIVERS: Set[Type[TIMELOCK_TYPES]] = {
    AssertBeforeSecondsRelative,
    AssertBeforeHeightRelative,
    AssertBeforeSecondsAbsolute,
    AssertBeforeHeightAbsolute,
}
RELATIVE_TIMELOCK_DRIVERS: Set[Type[TIMELOCK_TYPES]] = {
    AssertSecondsRelative,
    AssertHeightRelative,
    AssertBeforeSecondsRelative,
    AssertBeforeHeightRelative,
}
ABSOLUTE_TIMELOCK_DRIVERS: Set[Type[TIMELOCK_TYPES]] = {
    AssertSecondsAbsolute,
    AssertHeightAbsolute,
    AssertBeforeSecondsAbsolute,
    AssertBeforeHeightAbsolute,
}
TIMELOCK_DRIVERS_SET: Set[Type[TIMELOCK_TYPES]] = set(TIMELOCK_DRIVERS)


TIMELOCK_OPCODES: Set[bytes] = {
    ConditionOpcode.ASSERT_SECONDS_RELATIVE.value,
    ConditionOpcode.ASSERT_HEIGHT_RELATIVE.value,
    ConditionOpcode.ASSERT_SECONDS_ABSOLUTE.value,
    ConditionOpcode.ASSERT_HEIGHT_ABSOLUTE.value,
    ConditionOpcode.ASSERT_BEFORE_SECONDS_RELATIVE.value,
    ConditionOpcode.ASSERT_BEFORE_HEIGHT_RELATIVE.value,
    ConditionOpcode.ASSERT_BEFORE_SECONDS_ABSOLUTE.value,
    ConditionOpcode.ASSERT_BEFORE_HEIGHT_ABSOLUTE.value,
}
SECONDS_TIMELOCK_OPCODES: Set[bytes] = {
    ConditionOpcode.ASSERT_SECONDS_RELATIVE.value,
    ConditionOpcode.ASSERT_SECONDS_ABSOLUTE.value,
    ConditionOpcode.ASSERT_BEFORE_SECONDS_RELATIVE.value,
    ConditionOpcode.ASSERT_BEFORE_SECONDS_ABSOLUTE.value,
}
HEIGHT_TIMELOCK_OPCODES: Set[bytes] = {
    ConditionOpcode.ASSERT_HEIGHT_RELATIVE.value,
    ConditionOpcode.ASSERT_HEIGHT_ABSOLUTE.value,
    ConditionOpcode.ASSERT_BEFORE_HEIGHT_RELATIVE.value,
    ConditionOpcode.ASSERT_BEFORE_HEIGHT_ABSOLUTE.value,
}
AFTER_TIMELOCK_OPCODES: Set[bytes] = {
    ConditionOpcode.ASSERT_SECONDS_RELATIVE.value,
    ConditionOpcode.ASSERT_HEIGHT_RELATIVE.value,
    ConditionOpcode.ASSERT_SECONDS_ABSOLUTE.value,
    ConditionOpcode.ASSERT_HEIGHT_ABSOLUTE.value,
}
BEFORE_TIMELOCK_OPCODES: Set[bytes] = {
    ConditionOpcode.ASSERT_BEFORE_SECONDS_RELATIVE.value,
    ConditionOpcode.ASSERT_BEFORE_HEIGHT_RELATIVE.value,
    ConditionOpcode.ASSERT_BEFORE_SECONDS_ABSOLUTE.value,
    ConditionOpcode.ASSERT_BEFORE_HEIGHT_ABSOLUTE.value,
}
RELATIVE_TIMELOCK_OPCODES: Set[bytes] = {
    ConditionOpcode.ASSERT_SECONDS_RELATIVE.value,
    ConditionOpcode.ASSERT_HEIGHT_RELATIVE.value,
    ConditionOpcode.ASSERT_BEFORE_SECONDS_RELATIVE.value,
    ConditionOpcode.ASSERT_BEFORE_HEIGHT_RELATIVE.value,
}
ABSOLUTE_TIMELOCK_OPCODES: Set[bytes] = {
    ConditionOpcode.ASSERT_SECONDS_ABSOLUTE.value,
    ConditionOpcode.ASSERT_HEIGHT_ABSOLUTE.value,
    ConditionOpcode.ASSERT_BEFORE_SECONDS_ABSOLUTE.value,
    ConditionOpcode.ASSERT_BEFORE_HEIGHT_ABSOLUTE.value,
}


@final
@streamable
@dataclass(frozen=True)
class Timelock(Condition):
    after_not_before: bool
    relative_not_absolute: bool
    seconds_not_height: bool
    timestamp: uint64

    def to_program(self) -> Program:
        if self.after_not_before:
            potential_drivers = TIMELOCK_DRIVERS_SET - BEFORE_TIMELOCK_DRIVERS
        else:
            potential_drivers = TIMELOCK_DRIVERS_SET - AFTER_TIMELOCK_DRIVERS

        if self.relative_not_absolute:
            potential_drivers -= ABSOLUTE_TIMELOCK_DRIVERS
        else:
            potential_drivers -= RELATIVE_TIMELOCK_DRIVERS

        if self.seconds_not_height:
            potential_drivers -= HEIGHT_TIMELOCK_DRIVERS
        else:
            potential_drivers -= SECONDS_TIMELOCK_DRIVERS

        driver: Type[TIMELOCK_TYPES] = next(iter(potential_drivers))

        if self.seconds_not_height:
            # Semantics here mean that we're assuredly passing a uint64 to a class that expects it
            return driver(self.timestamp).to_program()  # type: ignore[arg-type]
        else:
            # Semantics here mean that we're assuredly passing a uint32 to a class that expects it
            return driver(uint32(self.timestamp)).to_program()  # type: ignore[arg-type]

    @classmethod
    def from_program(cls, program: Program) -> Timelock:
        opcode: bytes = program.at("f").as_atom()
        if opcode in AFTER_TIMELOCK_OPCODES:
            after_not_before = True
        else:
            after_not_before = False

        if opcode in RELATIVE_TIMELOCK_OPCODES:
            relative_not_absolute = True
        else:
            relative_not_absolute = False

        if opcode in SECONDS_TIMELOCK_OPCODES:
            seconds_not_height = True
        else:
            seconds_not_height = False

        return cls(
            after_not_before,
            relative_not_absolute,
            seconds_not_height,
            uint64(program.at("rf").as_int()),
        )


CONDITION_DRIVERS: Dict[bytes, Type[Condition]] = {
    ConditionOpcode.AGG_SIG_PARENT.value: AggSigParent,
    ConditionOpcode.AGG_SIG_PUZZLE.value: AggSigPuzzle,
    ConditionOpcode.AGG_SIG_AMOUNT.value: AggSigAmount,
    ConditionOpcode.AGG_SIG_PUZZLE_AMOUNT.value: AggSigPuzzleAmount,
    ConditionOpcode.AGG_SIG_PARENT_AMOUNT.value: AggSigParentAmount,
    ConditionOpcode.AGG_SIG_PARENT_PUZZLE.value: AggSigParentPuzzle,
    ConditionOpcode.AGG_SIG_UNSAFE.value: AggSigUnsafe,
    ConditionOpcode.AGG_SIG_ME.value: AggSigMe,
    ConditionOpcode.CREATE_COIN.value: CreateCoin,
    ConditionOpcode.RESERVE_FEE.value: ReserveFee,
    ConditionOpcode.CREATE_COIN_ANNOUNCEMENT.value: CreateCoinAnnouncement,
    ConditionOpcode.ASSERT_COIN_ANNOUNCEMENT.value: AssertCoinAnnouncement,
    ConditionOpcode.CREATE_PUZZLE_ANNOUNCEMENT.value: CreatePuzzleAnnouncement,
    ConditionOpcode.ASSERT_PUZZLE_ANNOUNCEMENT.value: AssertPuzzleAnnouncement,
    ConditionOpcode.SEND_MESSAGE.value: SendMessage,
    ConditionOpcode.RECEIVE_MESSAGE.value: ReceiveMessage,
    ConditionOpcode.ASSERT_CONCURRENT_SPEND.value: AssertConcurrentSpend,
    ConditionOpcode.ASSERT_CONCURRENT_PUZZLE.value: AssertConcurrentPuzzle,
    ConditionOpcode.ASSERT_MY_COIN_ID.value: AssertMyCoinID,
    ConditionOpcode.ASSERT_MY_PARENT_ID.value: AssertMyParentID,
    ConditionOpcode.ASSERT_MY_PUZZLEHASH.value: AssertMyPuzzleHash,
    ConditionOpcode.ASSERT_MY_AMOUNT.value: AssertMyAmount,
    ConditionOpcode.ASSERT_MY_BIRTH_SECONDS.value: AssertMyBirthSeconds,
    ConditionOpcode.ASSERT_MY_BIRTH_HEIGHT.value: AssertMyBirthHeight,
    ConditionOpcode.ASSERT_EPHEMERAL.value: AssertEphemeral,
    ConditionOpcode.ASSERT_SECONDS_RELATIVE.value: AssertSecondsRelative,
    ConditionOpcode.ASSERT_SECONDS_ABSOLUTE.value: AssertSecondsAbsolute,
    ConditionOpcode.ASSERT_HEIGHT_RELATIVE.value: AssertHeightRelative,
    ConditionOpcode.ASSERT_HEIGHT_ABSOLUTE.value: AssertHeightAbsolute,
    ConditionOpcode.ASSERT_BEFORE_SECONDS_RELATIVE.value: AssertBeforeSecondsRelative,
    ConditionOpcode.ASSERT_BEFORE_SECONDS_ABSOLUTE.value: AssertBeforeSecondsAbsolute,
    ConditionOpcode.ASSERT_BEFORE_HEIGHT_RELATIVE.value: AssertBeforeHeightRelative,
    ConditionOpcode.ASSERT_BEFORE_HEIGHT_ABSOLUTE.value: AssertBeforeHeightAbsolute,
    ConditionOpcode.SOFTFORK.value: Softfork,
    ConditionOpcode.REMARK.value: Remark,
}
DRIVERS_TO_OPCODES: Dict[Type[Condition], bytes] = {v: k for k, v in CONDITION_DRIVERS.items()}


CONDITION_DRIVERS_W_ABSTRACTIONS: Dict[bytes, Type[Condition]] = {
    ConditionOpcode.AGG_SIG_PARENT.value: AggSig,
    ConditionOpcode.AGG_SIG_PUZZLE.value: AggSig,
    ConditionOpcode.AGG_SIG_AMOUNT.value: AggSig,
    ConditionOpcode.AGG_SIG_PUZZLE_AMOUNT.value: AggSig,
    ConditionOpcode.AGG_SIG_PARENT_AMOUNT.value: AggSig,
    ConditionOpcode.AGG_SIG_PARENT_PUZZLE.value: AggSig,
    ConditionOpcode.AGG_SIG_UNSAFE.value: AggSig,
    ConditionOpcode.AGG_SIG_ME.value: AggSig,
    ConditionOpcode.CREATE_COIN.value: CreateCoin,
    ConditionOpcode.RESERVE_FEE.value: ReserveFee,
    ConditionOpcode.CREATE_COIN_ANNOUNCEMENT.value: CreateAnnouncement,
    ConditionOpcode.ASSERT_COIN_ANNOUNCEMENT.value: AssertAnnouncement,
    ConditionOpcode.CREATE_PUZZLE_ANNOUNCEMENT.value: CreateAnnouncement,
    ConditionOpcode.ASSERT_PUZZLE_ANNOUNCEMENT.value: AssertAnnouncement,
    ConditionOpcode.SEND_MESSAGE.value: SendMessage,
    ConditionOpcode.RECEIVE_MESSAGE.value: ReceiveMessage,
    ConditionOpcode.ASSERT_CONCURRENT_SPEND.value: AssertConcurrentSpend,
    ConditionOpcode.ASSERT_CONCURRENT_PUZZLE.value: AssertConcurrentPuzzle,
    ConditionOpcode.ASSERT_MY_COIN_ID.value: AssertMyCoinID,
    ConditionOpcode.ASSERT_MY_PARENT_ID.value: AssertMyParentID,
    ConditionOpcode.ASSERT_MY_PUZZLEHASH.value: AssertMyPuzzleHash,
    ConditionOpcode.ASSERT_MY_AMOUNT.value: AssertMyAmount,
    ConditionOpcode.ASSERT_MY_BIRTH_SECONDS.value: AssertMyBirthSeconds,
    ConditionOpcode.ASSERT_MY_BIRTH_HEIGHT.value: AssertMyBirthHeight,
    ConditionOpcode.ASSERT_EPHEMERAL.value: AssertEphemeral,
    ConditionOpcode.ASSERT_SECONDS_RELATIVE.value: Timelock,
    ConditionOpcode.ASSERT_SECONDS_ABSOLUTE.value: Timelock,
    ConditionOpcode.ASSERT_HEIGHT_RELATIVE.value: Timelock,
    ConditionOpcode.ASSERT_HEIGHT_ABSOLUTE.value: Timelock,
    ConditionOpcode.ASSERT_BEFORE_SECONDS_RELATIVE.value: Timelock,
    ConditionOpcode.ASSERT_BEFORE_SECONDS_ABSOLUTE.value: Timelock,
    ConditionOpcode.ASSERT_BEFORE_HEIGHT_RELATIVE.value: Timelock,
    ConditionOpcode.ASSERT_BEFORE_HEIGHT_ABSOLUTE.value: Timelock,
    ConditionOpcode.SOFTFORK.value: Softfork,
    ConditionOpcode.REMARK.value: Remark,
}


def parse_conditions_non_consensus(
    conditions: Iterable[Program],
    abstractions: bool = True,  # Use abstractions like *Announcement or Timelock instead of specific condition class
) -> List[Condition]:
    driver_dictionary: Dict[bytes, Type[Condition]] = (
        CONDITION_DRIVERS_W_ABSTRACTIONS if abstractions else CONDITION_DRIVERS
    )
    final_condition_list: List[Condition] = []
    for condition in conditions:
        try:
            final_condition_list.append(driver_dictionary[condition.at("f").as_atom()].from_program(condition))
        except Exception:
            final_condition_list.append(UnknownCondition.from_program(condition))

    return final_condition_list


def conditions_from_json_dicts(conditions: Iterable[Dict[str, Any]]) -> List[Condition]:
    final_condition_list: List[Condition] = []
    for condition in conditions:
        opcode_specified: Union[str, int] = condition["opcode"]
        if isinstance(opcode_specified, str):
            try:
                opcode: bytes = ConditionOpcode[opcode_specified]
            except KeyError:
                final_condition_list.append(UnknownCondition.from_json_dict(condition))
                continue
        elif isinstance(opcode_specified, int):
            opcode = int_to_bytes(opcode_specified)
        else:
            raise ValueError(f"Invalid condition opcode {opcode_specified}")

        try:
            final_condition_list.append(CONDITION_DRIVERS[opcode].from_json_dict(condition["args"]))
        except Exception:
            condition["opcode"] = Program.to(opcode)
            final_condition_list.append(UnknownCondition.from_json_dict(condition))

    return final_condition_list


def conditions_to_json_dicts(conditions: Iterable[Condition]) -> List[Dict[str, Any]]:
    return [
        {
            "opcode": int_from_bytes(DRIVERS_TO_OPCODES[condition.__class__]),
            "args": condition.to_json_dict(),
        }
        for condition in conditions
    ]


@streamable
@dataclass(frozen=True)
class ConditionValidTimes(Streamable):
    min_secs_since_created: Optional[uint64] = None  # ASSERT_SECONDS_RELATIVE
    min_time: Optional[uint64] = None  # ASSERT_SECONDS_ABSOLUTE
    min_blocks_since_created: Optional[uint32] = None  # ASSERT_HEIGHT_RELATIVE
    min_height: Optional[uint32] = None  # ASSERT_HEIGHT_ABSOLUTE
    max_secs_after_created: Optional[uint64] = None  # ASSERT_BEFORE_SECONDS_RELATIVE
    max_time: Optional[uint64] = None  # ASSERT_BEFORE_SECONDS_ABSOLUTE
    max_blocks_after_created: Optional[uint32] = None  # ASSERT_BEFORE_HEIGHT_RELATIVE
    max_height: Optional[uint32] = None  # ASSERT_BEFORE_HEIGHT_ABSOLUTE

    def to_conditions(self) -> List[Condition]:
        final_condition_list: List[Condition] = []
        if self.min_secs_since_created is not None:
            final_condition_list.append(AssertSecondsRelative(self.min_secs_since_created))
        if self.min_time is not None:
            final_condition_list.append(AssertSecondsAbsolute(self.min_time))
        if self.min_blocks_since_created is not None:
            final_condition_list.append(AssertHeightRelative(self.min_blocks_since_created))
        if self.min_height is not None:
            final_condition_list.append(AssertHeightAbsolute(self.min_height))
        if self.max_secs_after_created is not None:
            final_condition_list.append(AssertBeforeSecondsRelative(self.max_secs_after_created))
        if self.max_time is not None:
            final_condition_list.append(AssertBeforeSecondsAbsolute(self.max_time))
        if self.max_blocks_after_created is not None:
            final_condition_list.append(AssertBeforeHeightRelative(self.max_blocks_after_created))
        if self.max_height is not None:
            final_condition_list.append(AssertBeforeHeightAbsolute(self.max_height))

        return final_condition_list


condition_valid_times_hints = get_type_hints(ConditionValidTimes)
condition_valid_times_types: Dict[str, Type[int]] = {}
for field in fields(ConditionValidTimes):
    hint = condition_valid_times_hints[field.name]
    [type_] = [type_ for type_ in hint.__args__ if type_ is not type(None)]
    condition_valid_times_types[field.name] = type_


# Properties of the dataclass above, grouped by their property
SECONDS_PROPERTIES: Set[str] = {"min_secs_since_created", "min_time", "max_secs_after_created", "max_time"}
HEIGHT_PROPERTIES: Set[str] = {"min_blocks_since_created", "min_height", "max_blocks_after_created", "max_height"}
AFTER_PROPERTIES: Set[str] = {"min_blocks_since_created", "min_height", "min_secs_since_created", "min_time"}
BEFORE_PROPERTIES: Set[str] = {"max_blocks_after_created", "max_height", "max_secs_after_created", "max_time"}
RELATIVE_PROPERTIES: Set[str] = {
    "min_blocks_since_created",
    "min_secs_since_created",
    "max_secs_after_created",
    "max_blocks_after_created",
}
ABSOLUTE_PROPERTIES: Set[str] = {"min_time", "max_time", "min_height", "max_height"}
ALL_PROPERTIES: Set[str] = SECONDS_PROPERTIES | HEIGHT_PROPERTIES


def parse_timelock_info(conditions: Iterable[Condition]) -> ConditionValidTimes:
    valid_times: ConditionValidTimes = ConditionValidTimes()
    properties: Set[str] = ALL_PROPERTIES.copy()
    for condition in conditions:
        if isinstance(condition, TIMELOCK_DRIVERS):
            timelock: Timelock = Timelock.from_program(condition.to_program())
        elif isinstance(condition, Timelock):
            timelock = condition
        else:
            # Something about python 3.9 makes this be not covered but on 3.10+ it is covered
            # https://github.com/nedbat/coveragepy/issues/1530
            continue  # pragma: no cover

        properties_left = properties.copy()
        min_not_max: bool = True
        if timelock.after_not_before:
            min_not_max = False
            properties_left -= BEFORE_PROPERTIES
        else:
            properties_left -= AFTER_PROPERTIES

        if timelock.seconds_not_height:
            properties_left -= HEIGHT_PROPERTIES
        else:
            properties_left -= SECONDS_PROPERTIES

        if timelock.relative_not_absolute:
            properties_left -= ABSOLUTE_PROPERTIES
        else:
            properties_left -= RELATIVE_PROPERTIES

        assert len(properties_left) == 1
        final_property: str = next(iter(properties_left))
        current_value: Optional[int] = getattr(valid_times, final_property)
        if current_value is not None:
            if min_not_max:
                new_value: int = min(current_value, timelock.timestamp)
            else:
                new_value = max(current_value, timelock.timestamp)
        else:
            new_value = timelock.timestamp

        final_type = condition_valid_times_types[final_property]
        replacement: Dict[str, int] = {final_property: final_type(new_value)}
        # the type is enforced above
        valid_times = replace(valid_times, **replacement)  # type: ignore[arg-type]

    return valid_times
