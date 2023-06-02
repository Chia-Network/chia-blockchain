from __future__ import annotations

from typing import List

from chia.types.blockchain_format.program import Program
from chia.types.condition_opcodes import ConditionOpcode


def make_create_coin_condition(puzzle_hash, amount, memos: List[bytes]) -> Program:
    condition = [ConditionOpcode.CREATE_COIN, puzzle_hash, amount]
    if len(memos) > 0:
        condition.append(memos)
    condition_after_memos: Program = Program.to(condition)
    return condition_after_memos


def make_assert_aggsig_condition(pubkey) -> Program:
    condition: Program = Program.to([ConditionOpcode.AGG_SIG_UNSAFE, pubkey])
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
