from __future__ import annotations

from typing import List

from chia.types.condition_opcodes import ConditionOpcode


def make_create_coin_condition(puzzle_hash, amount, memos: List[bytes]) -> List:
    condition = [ConditionOpcode.CREATE_COIN, puzzle_hash, amount]
    if len(memos) > 0:
        condition.append(memos)
    return condition


def make_assert_aggsig_condition(pubkey):
    return [ConditionOpcode.AGG_SIG_UNSAFE, pubkey]


def make_assert_my_coin_id_condition(coin_name):
    return [ConditionOpcode.ASSERT_MY_COIN_ID, coin_name]


def make_assert_absolute_height_exceeds_condition(block_index):
    return [ConditionOpcode.ASSERT_HEIGHT_ABSOLUTE, block_index]


def make_assert_relative_height_exceeds_condition(block_index):
    return [ConditionOpcode.ASSERT_HEIGHT_RELATIVE, block_index]


def make_assert_absolute_seconds_exceeds_condition(time):
    return [ConditionOpcode.ASSERT_SECONDS_ABSOLUTE, time]


def make_assert_relative_seconds_exceeds_condition(time):
    return [ConditionOpcode.ASSERT_SECONDS_RELATIVE, time]


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


def make_assert_my_parent_id(parent_id):
    return [ConditionOpcode.ASSERT_MY_PARENT_ID, parent_id]


def make_assert_my_puzzlehash(puzzlehash):
    return [ConditionOpcode.ASSERT_MY_PUZZLEHASH, puzzlehash]


def make_assert_my_amount(amount):
    return [ConditionOpcode.ASSERT_MY_AMOUNT, amount]
