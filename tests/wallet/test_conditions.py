from __future__ import annotations

from dataclasses import dataclass

import pytest

from chia.types.blockchain_format.program import Program
from chia.types.condition_opcodes import ConditionOpcode
from chia.wallet.conditions import (
    CONDITION_DRIVERS,
    CONDITION_DRIVERS_W_ABSTRACTIONS,
    Condition,
    UnknownCondition,
    parse_conditions_non_consensus,
)


@dataclass(frozen=True)
class ConditionSerializations:
    opcode: bytes
    program_args: Program

    @property
    def program(self) -> Program:
        prog: Program = Program.to(self.opcode).cons(self.program_args)
        return prog


HASH: bytes = bytes(32)
PK: bytes = b"\xc0" + bytes(47)
AMT: int = 0
MSG: bytes = bytes(1)


def test_completeness() -> None:
    assert len(ConditionOpcode) == len(CONDITION_DRIVERS) == len(CONDITION_DRIVERS_W_ABSTRACTIONS)


@pytest.mark.parametrize("abstractions", [True, False])
@pytest.mark.parametrize(
    "serializations",
    [
        ConditionSerializations(ConditionOpcode.AGG_SIG_PARENT, Program.to([PK, MSG])),
        ConditionSerializations(ConditionOpcode.AGG_SIG_PUZZLE, Program.to([PK, MSG])),
        ConditionSerializations(ConditionOpcode.AGG_SIG_AMOUNT, Program.to([PK, MSG])),
        ConditionSerializations(ConditionOpcode.AGG_SIG_PUZZLE_AMOUNT, Program.to([PK, MSG])),
        ConditionSerializations(ConditionOpcode.AGG_SIG_PARENT_AMOUNT, Program.to([PK, MSG])),
        ConditionSerializations(ConditionOpcode.AGG_SIG_PARENT_PUZZLE, Program.to([PK, MSG])),
        ConditionSerializations(ConditionOpcode.AGG_SIG_UNSAFE, Program.to([PK, MSG])),
        ConditionSerializations(ConditionOpcode.AGG_SIG_ME, Program.to([PK, MSG])),
        ConditionSerializations(ConditionOpcode.CREATE_COIN, Program.to([HASH, AMT, [MSG]])),
        ConditionSerializations(ConditionOpcode.RESERVE_FEE, Program.to([AMT])),
        ConditionSerializations(ConditionOpcode.CREATE_COIN_ANNOUNCEMENT, Program.to([MSG])),
        ConditionSerializations(ConditionOpcode.ASSERT_COIN_ANNOUNCEMENT, Program.to([HASH])),
        ConditionSerializations(ConditionOpcode.CREATE_PUZZLE_ANNOUNCEMENT, Program.to([MSG])),
        ConditionSerializations(ConditionOpcode.ASSERT_PUZZLE_ANNOUNCEMENT, Program.to([HASH])),
        ConditionSerializations(ConditionOpcode.ASSERT_CONCURRENT_SPEND, Program.to([HASH])),
        ConditionSerializations(ConditionOpcode.ASSERT_CONCURRENT_PUZZLE, Program.to([HASH])),
        ConditionSerializations(ConditionOpcode.ASSERT_MY_COIN_ID, Program.to([HASH])),
        ConditionSerializations(ConditionOpcode.ASSERT_MY_PARENT_ID, Program.to([HASH])),
        ConditionSerializations(ConditionOpcode.ASSERT_MY_PUZZLEHASH, Program.to([HASH])),
        ConditionSerializations(ConditionOpcode.ASSERT_MY_AMOUNT, Program.to([AMT])),
        ConditionSerializations(ConditionOpcode.ASSERT_MY_BIRTH_SECONDS, Program.to([AMT])),
        ConditionSerializations(ConditionOpcode.ASSERT_MY_BIRTH_HEIGHT, Program.to([AMT])),
        ConditionSerializations(ConditionOpcode.ASSERT_EPHEMERAL, Program.to([])),
        ConditionSerializations(ConditionOpcode.ASSERT_SECONDS_RELATIVE, Program.to([AMT])),
        ConditionSerializations(ConditionOpcode.ASSERT_SECONDS_ABSOLUTE, Program.to([AMT])),
        ConditionSerializations(ConditionOpcode.ASSERT_HEIGHT_RELATIVE, Program.to([AMT])),
        ConditionSerializations(ConditionOpcode.ASSERT_HEIGHT_ABSOLUTE, Program.to([AMT])),
        ConditionSerializations(ConditionOpcode.ASSERT_BEFORE_SECONDS_RELATIVE, Program.to([AMT])),
        ConditionSerializations(ConditionOpcode.ASSERT_BEFORE_SECONDS_ABSOLUTE, Program.to([AMT])),
        ConditionSerializations(ConditionOpcode.ASSERT_BEFORE_HEIGHT_RELATIVE, Program.to([AMT])),
        ConditionSerializations(ConditionOpcode.ASSERT_BEFORE_HEIGHT_ABSOLUTE, Program.to([AMT])),
        ConditionSerializations(ConditionOpcode.SOFTFORK, Program.to([AMT, [-10, HASH]])),
        ConditionSerializations(ConditionOpcode.REMARK, Program.to([])),
    ],
)
def test_condition_serialization(serializations: ConditionSerializations, abstractions: bool) -> None:
    condition_driver: Condition = parse_conditions_non_consensus([serializations.program], abstractions=abstractions)[0]
    assert not isinstance(condition_driver, UnknownCondition)
    as_program: Program = condition_driver.to_program()
    assert as_program.at("f").atom == serializations.opcode
    assert as_program == serializations.program
    assert condition_driver == condition_driver.__class__.from_json_dict(condition_driver.to_json_dict())


def test_unknown_condition() -> None:
    assert parse_conditions_non_consensus([Program.to([-10, HASH, AMT])])[0] == UnknownCondition(
        Program.to(-10), [Program.to(HASH), Program.to(AMT)]
    )
