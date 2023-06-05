from __future__ import annotations

from typing import List

from chia.types.condition_opcodes import ConditionOpcode


def make_create_coin_condition(puzzle_hash, amount, memos: List[bytes]) -> List:
    condition = [ConditionOpcode.CREATE_COIN, puzzle_hash, amount]
    if len(memos) > 0:
        condition.append(memos)
    return condition


def make_reserve_fee_condition(fee):
    return [ConditionOpcode.RESERVE_FEE, fee]


def make_assert_coin_announcement(announcement_hash):
    return [ConditionOpcode.ASSERT_COIN_ANNOUNCEMENT, announcement_hash]


def make_assert_puzzle_announcement(announcement_hash):
    return [ConditionOpcode.ASSERT_PUZZLE_ANNOUNCEMENT, announcement_hash]


def make_create_coin_announcement(message):
    return [ConditionOpcode.CREATE_COIN_ANNOUNCEMENT, message]


def make_create_puzzle_announcement(message):
    return [ConditionOpcode.CREATE_PUZZLE_ANNOUNCEMENT, message]
