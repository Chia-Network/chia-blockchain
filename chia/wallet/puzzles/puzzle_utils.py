from __future__ import annotations

from typing import List, Optional

from chia.types.blockchain_format.program import Program
from chia.types.condition_opcodes import ConditionOpcode


def make_create_coin_condition(puzzle_hash, amount, memos: Optional[List[bytes]]) -> Program:
    if memos is not None:
        condition: Program = Program.to([ConditionOpcode.CREATE_COIN, puzzle_hash, amount, memos])
    else:
        condition = Program.to([ConditionOpcode.CREATE_COIN, puzzle_hash, amount])
    return condition


def make_assert_aggsig_condition(pubkey) -> Program:
    condition: Program = Program.to([ConditionOpcode.AGG_SIG_UNSAFE, pubkey])
    return condition


def make_assert_my_coin_id_condition(coin_name) -> Program:
    condition: Program = Program.to([ConditionOpcode.ASSERT_MY_COIN_ID, coin_name])
    return condition


def make_assert_absolute_height_exceeds_condition(block_index) -> Program:
    condition: Program = Program.to([ConditionOpcode.ASSERT_HEIGHT_ABSOLUTE, block_index])
    return condition


def make_assert_relative_height_exceeds_condition(block_index) -> Program:
    condition: Program = Program.to([ConditionOpcode.ASSERT_HEIGHT_RELATIVE, block_index])
    return condition


def make_assert_absolute_seconds_exceeds_condition(time) -> Program:
    condition: Program = Program.to([ConditionOpcode.ASSERT_SECONDS_ABSOLUTE, time])
    return condition


def make_assert_relative_seconds_exceeds_condition(time) -> Program:
    condition: Program = Program.to([ConditionOpcode.ASSERT_SECONDS_RELATIVE, time])
    return condition


def make_reserve_fee_condition(fee) -> Program:
    condition: Program = Program.to([ConditionOpcode.RESERVE_FEE, fee])
    return condition


def make_assert_coin_announcement(announcement_hash) -> Program:
    condition: Program = Program.to([ConditionOpcode.ASSERT_COIN_ANNOUNCEMENT, announcement_hash])
    return condition


def make_assert_puzzle_announcement(announcement_hash) -> Program:
    condition: Program = Program.to([ConditionOpcode.ASSERT_PUZZLE_ANNOUNCEMENT, announcement_hash])
    return condition


def make_create_coin_announcement(message) -> Program:
    condition: Program = Program.to([ConditionOpcode.CREATE_COIN_ANNOUNCEMENT, message])
    return condition


def make_create_puzzle_announcement(message) -> Program:
    condition: Program = Program.to([ConditionOpcode.CREATE_PUZZLE_ANNOUNCEMENT, message])
    return condition


def make_assert_my_parent_id(parent_id) -> Program:
    condition: Program = Program.to([ConditionOpcode.ASSERT_MY_PARENT_ID, parent_id])
    return condition


def make_assert_my_puzzlehash(puzzlehash) -> Program:
    condition: Program = Program.to([ConditionOpcode.ASSERT_MY_PUZZLEHASH, puzzlehash])
    return condition


def make_assert_my_amount(amount) -> Program:
    condition: Program = Program.to([ConditionOpcode.ASSERT_MY_AMOUNT, amount])
    return condition
