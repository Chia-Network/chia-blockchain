from __future__ import annotations

from dataclasses import dataclass
from typing import Any, List, Optional, Tuple, Type, Union

import pytest
from clvm.casts import int_from_bytes
from clvm.EvalError import EvalError

from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.condition_opcodes import ConditionOpcode
from chia.util.ints import uint32, uint64
from chia.wallet.conditions import (
    CONDITION_DRIVERS,
    CONDITION_DRIVERS_W_ABSTRACTIONS,
    AggSig,
    AggSigAmount,
    AggSigMe,
    AggSigParent,
    AggSigParentAmount,
    AggSigParentPuzzle,
    AggSigPuzzle,
    AggSigPuzzleAmount,
    AggSigUnsafe,
    AssertAnnouncement,
    AssertBeforeHeightAbsolute,
    AssertBeforeHeightRelative,
    AssertBeforeSecondsAbsolute,
    AssertBeforeSecondsRelative,
    AssertCoinAnnouncement,
    AssertConcurrentPuzzle,
    AssertConcurrentSpend,
    AssertHeightAbsolute,
    AssertHeightRelative,
    AssertMyAmount,
    AssertMyBirthHeight,
    AssertMyBirthSeconds,
    AssertMyCoinID,
    AssertMyParentID,
    AssertMyPuzzleHash,
    AssertPuzzleAnnouncement,
    AssertSecondsAbsolute,
    AssertSecondsRelative,
    Condition,
    ConditionValidTimes,
    CreateAnnouncement,
    CreateCoin,
    CreateCoinAnnouncement,
    CreatePuzzleAnnouncement,
    ReceiveMessage,
    Remark,
    ReserveFee,
    SendMessage,
    Softfork,
    Timelock,
    UnknownCondition,
    conditions_from_json_dicts,
    conditions_to_json_dicts,
    parse_conditions_non_consensus,
    parse_timelock_info,
)


@dataclass(frozen=True)
class ConditionSerializations:
    opcode: bytes
    program_args: Program
    json_keys: List[str]
    json_args: List[Any]

    @property
    def program(self) -> Program:
        prog: Program = Program.to(self.opcode).cons(self.program_args)
        return prog


HASH: bytes32 = bytes32([0] * 32)
HASH_HEX: str = HASH.hex()
PK: bytes = b"\xc0" + bytes(47)
PK_HEX: str = PK.hex()
AMT: int = 0
MSG: bytes = bytes(1)
MSG_HEX: str = MSG.hex()


def test_completeness() -> None:
    assert len(ConditionOpcode) == len(CONDITION_DRIVERS) == len(CONDITION_DRIVERS_W_ABSTRACTIONS)


@pytest.mark.parametrize("abstractions", [True, False])
@pytest.mark.parametrize(
    "serializations",
    [
        ConditionSerializations(
            ConditionOpcode.AGG_SIG_PARENT, Program.to([PK, MSG]), ["pubkey", "msg"], [PK_HEX, MSG_HEX]
        ),
        ConditionSerializations(
            ConditionOpcode.AGG_SIG_PUZZLE, Program.to([PK, MSG]), ["pubkey", "msg"], [PK_HEX, MSG_HEX]
        ),
        ConditionSerializations(
            ConditionOpcode.AGG_SIG_AMOUNT, Program.to([PK, MSG]), ["pubkey", "msg"], [PK_HEX, MSG_HEX]
        ),
        ConditionSerializations(
            ConditionOpcode.AGG_SIG_PUZZLE_AMOUNT, Program.to([PK, MSG]), ["pubkey", "msg"], [PK_HEX, MSG_HEX]
        ),
        ConditionSerializations(
            ConditionOpcode.AGG_SIG_PARENT_AMOUNT, Program.to([PK, MSG]), ["pubkey", "msg"], [PK_HEX, MSG_HEX]
        ),
        ConditionSerializations(
            ConditionOpcode.AGG_SIG_PARENT_PUZZLE, Program.to([PK, MSG]), ["pubkey", "msg"], [PK_HEX, MSG_HEX]
        ),
        ConditionSerializations(
            ConditionOpcode.AGG_SIG_UNSAFE, Program.to([PK, MSG]), ["pubkey", "msg"], [PK_HEX, MSG_HEX]
        ),
        ConditionSerializations(
            ConditionOpcode.AGG_SIG_ME, Program.to([PK, MSG]), ["pubkey", "msg"], [PK_HEX, MSG_HEX]
        ),
        ConditionSerializations(
            ConditionOpcode.CREATE_COIN,
            Program.to([HASH, AMT, [MSG]]),
            ["puzzle_hash", "amount", "memos"],
            [HASH_HEX, AMT, [MSG_HEX]],
        ),
        ConditionSerializations(ConditionOpcode.RESERVE_FEE, Program.to([AMT]), ["amount"], [AMT]),
        ConditionSerializations(ConditionOpcode.CREATE_COIN_ANNOUNCEMENT, Program.to([MSG]), ["msg"], [MSG_HEX]),
        ConditionSerializations(ConditionOpcode.ASSERT_COIN_ANNOUNCEMENT, Program.to([HASH]), ["msg"], [HASH_HEX]),
        ConditionSerializations(ConditionOpcode.CREATE_PUZZLE_ANNOUNCEMENT, Program.to([MSG]), ["msg"], [MSG_HEX]),
        ConditionSerializations(ConditionOpcode.ASSERT_PUZZLE_ANNOUNCEMENT, Program.to([HASH]), ["msg"], [HASH_HEX]),
        ConditionSerializations(ConditionOpcode.ASSERT_CONCURRENT_SPEND, Program.to([HASH]), ["coin_id"], [HASH_HEX]),
        ConditionSerializations(
            ConditionOpcode.ASSERT_CONCURRENT_PUZZLE, Program.to([HASH]), ["puzzle_hash"], [HASH_HEX]
        ),
        ConditionSerializations(ConditionOpcode.ASSERT_MY_COIN_ID, Program.to([HASH]), ["coin_id"], [HASH_HEX]),
        ConditionSerializations(ConditionOpcode.ASSERT_MY_PARENT_ID, Program.to([HASH]), ["coin_id"], [HASH_HEX]),
        ConditionSerializations(ConditionOpcode.ASSERT_MY_PUZZLEHASH, Program.to([HASH]), ["puzzle_hash"], [HASH_HEX]),
        ConditionSerializations(ConditionOpcode.ASSERT_MY_AMOUNT, Program.to([AMT]), ["amount"], [AMT]),
        ConditionSerializations(ConditionOpcode.ASSERT_MY_BIRTH_SECONDS, Program.to([AMT]), ["seconds"], [AMT]),
        ConditionSerializations(ConditionOpcode.ASSERT_MY_BIRTH_HEIGHT, Program.to([AMT]), ["height"], [AMT]),
        ConditionSerializations(ConditionOpcode.ASSERT_EPHEMERAL, Program.to([]), [], []),
        ConditionSerializations(ConditionOpcode.ASSERT_SECONDS_RELATIVE, Program.to([AMT]), ["seconds"], [AMT]),
        ConditionSerializations(ConditionOpcode.ASSERT_SECONDS_ABSOLUTE, Program.to([AMT]), ["seconds"], [AMT]),
        ConditionSerializations(ConditionOpcode.ASSERT_HEIGHT_RELATIVE, Program.to([AMT]), ["height"], [AMT]),
        ConditionSerializations(ConditionOpcode.ASSERT_HEIGHT_ABSOLUTE, Program.to([AMT]), ["height"], [AMT]),
        ConditionSerializations(ConditionOpcode.ASSERT_BEFORE_SECONDS_RELATIVE, Program.to([AMT]), ["seconds"], [AMT]),
        ConditionSerializations(ConditionOpcode.ASSERT_BEFORE_SECONDS_ABSOLUTE, Program.to([AMT]), ["seconds"], [AMT]),
        ConditionSerializations(ConditionOpcode.ASSERT_BEFORE_HEIGHT_RELATIVE, Program.to([AMT]), ["height"], [AMT]),
        ConditionSerializations(ConditionOpcode.ASSERT_BEFORE_HEIGHT_ABSOLUTE, Program.to([AMT]), ["height"], [AMT]),
        ConditionSerializations(
            ConditionOpcode.SOFTFORK,
            Program.to([AMT, [-10, HASH]]),
            ["cost", "conditions"],
            [AMT, ["81f6", "a0" + HASH_HEX]],
        ),
        ConditionSerializations(ConditionOpcode.REMARK, Program.to([]), ["rest"], ["80"]),
        ConditionSerializations(
            ConditionOpcode.SEND_MESSAGE,
            Program.to([0x3F, b"foobar", Program.to(HASH)]),
            ["mode", "msg", "args"],
            ["63", "0x" + b"foobar".hex(), "a0" + HASH_HEX],
        ),
        ConditionSerializations(
            ConditionOpcode.RECEIVE_MESSAGE,
            Program.to([0x3F, b"foobar", Program.to(HASH)]),
            ["mode", "msg", "args"],
            ["63", "0x" + b"foobar".hex(), "a0" + HASH_HEX],
        ),
    ],
)
def test_condition_serialization(serializations: ConditionSerializations, abstractions: bool) -> None:
    condition_driver: Condition = parse_conditions_non_consensus([serializations.program], abstractions=abstractions)[0]
    if not abstractions:
        json = {
            "opcode": int_from_bytes(serializations.opcode),
            "args": {key: args for key, args in zip(serializations.json_keys, serializations.json_args)},
        }
        assert condition_driver == conditions_from_json_dicts([json])[0]
        assert condition_driver == conditions_from_json_dicts(conditions_to_json_dicts([condition_driver]))[0]
    assert not isinstance(condition_driver, UnknownCondition)
    as_program: Program = condition_driver.to_program()
    assert as_program.at("f").atom == serializations.opcode
    assert as_program == serializations.program
    assert condition_driver == condition_driver.__class__.from_json_dict(condition_driver.to_json_dict())


def test_unknown_condition() -> None:
    unknown_condition: Condition = parse_conditions_non_consensus([Program.to([-10, HASH, AMT])])[0]
    assert unknown_condition == conditions_from_json_dicts([{"opcode": "81f6", "args": ["a0" + HASH_HEX, "80"]}])[0]
    assert unknown_condition == conditions_from_json_dicts([{"opcode": -10, "args": ["a0" + HASH_HEX, "80"]}])[0]
    with pytest.raises(ValueError, match="Invalid condition opcode"):
        conditions_from_json_dicts([{"opcode": bytes(32)}])
    assert unknown_condition == UnknownCondition(Program.to(-10), [Program.to(HASH), Program.to(AMT)])
    assert unknown_condition == UnknownCondition.from_program(unknown_condition.to_program())


@pytest.mark.parametrize(
    "drivers",
    [
        (CreateCoinAnnouncement, AssertCoinAnnouncement),
        (CreatePuzzleAnnouncement, AssertPuzzleAnnouncement),
        (CreateAnnouncement, AssertAnnouncement),
    ],
)
def test_announcement_inversions(
    drivers: Union[
        Tuple[Type[CreateCoinAnnouncement], Type[AssertCoinAnnouncement]],
        Tuple[Type[CreatePuzzleAnnouncement], Type[AssertPuzzleAnnouncement]],
        Tuple[Type[CreateAnnouncement], Type[AssertAnnouncement]],
    ]
) -> None:
    create_driver, assert_driver = drivers
    # mypy is not smart enough to understand that this `if` narrows down the potential types it could be
    # This leads to the large number of type ignores below
    if create_driver == CreateAnnouncement and assert_driver == AssertAnnouncement:
        with pytest.raises(ValueError, match="Must specify either"):
            assert_driver(True)  # type: ignore[arg-type]
        with pytest.raises(ValueError, match="Cannot create"):
            create_driver(MSG, True).corresponding_assertion()  # type: ignore[arg-type]
        with pytest.raises(ValueError, match="Cannot create"):
            assert_driver(True, MSG).corresponding_creation()  # type: ignore[arg-type]
        create_instance = create_driver(MSG, True, HASH)  # type: ignore[call-arg, arg-type]
        assert_instance = assert_driver(True, None, HASH, MSG)  # type: ignore[call-arg, arg-type]
    else:
        with pytest.raises(ValueError, match="Must specify either"):
            assert_driver()  # type: ignore[call-arg]
        with pytest.raises(ValueError, match="Cannot create"):
            create_driver(MSG).corresponding_assertion()  # type: ignore[call-arg]
        with pytest.raises(ValueError, match="Cannot create"):
            assert_driver(MSG).corresponding_creation()  # type: ignore[arg-type]
        create_instance = create_driver(MSG, HASH)  # type: ignore[arg-type]
        assert_instance = assert_driver(None, HASH, MSG)  # type: ignore[arg-type]
    assert_instance.to_program()  # Verifying that even without a specific message, we can still calculate the condition
    assert create_instance.corresponding_assertion() == assert_instance
    assert assert_instance.corresponding_creation() == create_instance


@dataclass(frozen=True)
class TimelockInfo:
    drivers: List[Condition]
    parsed_info: ConditionValidTimes
    conditions_after: Optional[List[Condition]] = None


@pytest.mark.parametrize(
    "timelock_info",
    [
        TimelockInfo([AssertSecondsRelative(uint64(0))], ConditionValidTimes(min_secs_since_created=uint64(0))),
        TimelockInfo([AssertHeightRelative(uint32(0))], ConditionValidTimes(min_blocks_since_created=uint32(0))),
        TimelockInfo([AssertSecondsAbsolute(uint64(0))], ConditionValidTimes(min_time=uint64(0))),
        TimelockInfo([AssertHeightAbsolute(uint32(0))], ConditionValidTimes(min_height=uint32(0))),
        TimelockInfo([AssertBeforeSecondsRelative(uint64(0))], ConditionValidTimes(max_secs_after_created=uint64(0))),
        TimelockInfo([AssertBeforeHeightRelative(uint32(0))], ConditionValidTimes(max_blocks_after_created=uint32(0))),
        TimelockInfo([AssertBeforeSecondsAbsolute(uint64(0))], ConditionValidTimes(max_time=uint64(0))),
        TimelockInfo([AssertBeforeHeightAbsolute(uint32(0))], ConditionValidTimes(max_height=uint32(0))),
        TimelockInfo(
            [Timelock(True, True, True, uint64(0))],
            ConditionValidTimes(min_secs_since_created=uint64(0)),
            [AssertSecondsRelative(uint64(0))],
        ),
        TimelockInfo(
            [
                AssertSecondsAbsolute(uint64(0)),
                AssertSecondsAbsolute(uint64(10)),
                AssertBeforeSecondsAbsolute(uint64(20)),
                AssertBeforeSecondsAbsolute(uint64(10)),
            ],
            ConditionValidTimes(min_time=uint64(10), max_time=uint64(10)),
            [
                AssertSecondsAbsolute(uint64(10)),
                AssertBeforeSecondsAbsolute(uint64(10)),
            ],
        ),
    ],
)
def test_timelock_parsing(timelock_info: TimelockInfo) -> None:
    assert timelock_info.parsed_info == parse_timelock_info(
        [UnknownCondition(Program.to(None), []), *timelock_info.drivers]
    )
    assert timelock_info.parsed_info.to_conditions() == (
        timelock_info.conditions_after if timelock_info.conditions_after is not None else timelock_info.drivers
    )


@pytest.mark.parametrize(
    "cond",
    [
        AggSigParent,
        AggSigPuzzle,
        AggSigAmount,
        AggSigPuzzleAmount,
        AggSigParentAmount,
        AggSigParentPuzzle,
        AggSigUnsafe,
        AggSigMe,
        CreateCoin,
        ReserveFee,
        AssertCoinAnnouncement,
        CreateCoinAnnouncement,
        AssertPuzzleAnnouncement,
        CreatePuzzleAnnouncement,
        AssertConcurrentSpend,
        AssertConcurrentPuzzle,
        AssertMyCoinID,
        AssertMyParentID,
        AssertMyPuzzleHash,
        AssertMyAmount,
        AssertMyBirthSeconds,
        AssertMyBirthHeight,
        AssertSecondsRelative,
        AssertSecondsAbsolute,
        AssertHeightRelative,
        AssertHeightAbsolute,
        AssertBeforeSecondsRelative,
        AssertBeforeSecondsAbsolute,
        AssertBeforeHeightRelative,
        AssertBeforeHeightAbsolute,
        Softfork,
        Remark,
        UnknownCondition,
        AggSig,
        CreateAnnouncement,
        AssertAnnouncement,
        Timelock,
        SendMessage,
        ReceiveMessage,
    ],
)
@pytest.mark.parametrize(
    "prg",
    [
        bytes([0x80]),
        bytes([0xFF, 0x80, 0xFF, 0xFF, 0xFF, 0x80, 0x80, 0x80, 0x80]),
        bytes([0xFF, 0x80, 0xFF, 0xFF, 0x80, 0x80, 0xFF, 0x80, 0x80]),
        bytes([0xFF, 0x80, 0xFF, 0xFF, 0x80, 0x80, 0xFF, 0x80, 0xFF, 0x80, 0x80]),
        bytes([0xFF, 0x80, 0xFF, 0xFF, 0x80, 0x80, 0xFF, 0x80, 0xFF, 0x80, 0xFF, 0x80, 0x80]),
    ],
)
def test_invalid_condition(
    cond: Type[
        Union[
            AggSigParent,
            AggSigPuzzle,
            AggSigAmount,
            AggSigPuzzleAmount,
            AggSigParentAmount,
            AggSigParentPuzzle,
            AggSigUnsafe,
            AggSigMe,
            CreateCoin,
            ReserveFee,
            AssertCoinAnnouncement,
            CreateCoinAnnouncement,
            AssertPuzzleAnnouncement,
            CreatePuzzleAnnouncement,
            AssertConcurrentSpend,
            AssertConcurrentPuzzle,
            AssertMyCoinID,
            AssertMyParentID,
            AssertMyPuzzleHash,
            AssertMyAmount,
            AssertMyBirthSeconds,
            AssertMyBirthHeight,
            AssertSecondsRelative,
            AssertSecondsAbsolute,
            AssertHeightRelative,
            AssertHeightAbsolute,
            AssertBeforeSecondsRelative,
            AssertBeforeSecondsAbsolute,
            AssertBeforeHeightRelative,
            AssertBeforeHeightAbsolute,
            Softfork,
            Remark,
            UnknownCondition,
            AggSig,
            CreateAnnouncement,
            AssertAnnouncement,
            Timelock,
            SendMessage,
            ReceiveMessage,
        ]
    ],
    prg: bytes,
) -> None:
    if (cond == Remark or cond == UnknownCondition) and prg != b"\x80":
        pytest.skip("condition takes arbitrary arguments")

    with pytest.raises((ValueError, EvalError, KeyError)):
        cond.from_program(Program.from_bytes(prg))
