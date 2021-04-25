from typing import List, Any
from chia.util.condition_tools import ConditionOpcode


def make_create_coin_condition(puzzle_hash, amount) -> List[Any]:
    return [ConditionOpcode.CREATE_COIN, puzzle_hash, amount]


def make_assert_aggsig_condition(pubkey) -> List[Any]:
    return [ConditionOpcode.AGG_SIG_UNSAFE, pubkey]


def make_assert_my_coin_id_condition(coin_name) -> List[Any]:
    return [ConditionOpcode.ASSERT_MY_COIN_ID, coin_name]


def make_assert_absolute_height_exceeds_condition(block_index) -> List[Any]:
    return [ConditionOpcode.ASSERT_HEIGHT_ABSOLUTE, block_index]


def make_assert_relative_height_exceeds_condition(block_index) -> List[Any]:
    return [ConditionOpcode.ASSERT_HEIGHT_RELATIVE, block_index]


def make_assert_absolute_seconds_exceeds_condition(time) -> List[Any]:
    return [ConditionOpcode.ASSERT_SECONDS_ABSOLUTE, time]


def make_assert_relative_seconds_exceeds_condition(time) -> List[Any]:
    return [ConditionOpcode.ASSERT_SECONDS_RELATIVE, time]


def make_reserve_fee_condition(fee) -> List[Any]:
    return [ConditionOpcode.RESERVE_FEE, fee]

def make_assert_coin_announcement(announcement_hash) -> List[Any]:
    return [ConditionOpcode.ASSERT_COIN_ANNOUNCEMENT, announcement_hash]

def make_assert_puzzle_announcement(announcement_hash) -> List[Any]:
    return [ConditionOpcode.ASSERT_PUZZLE_ANNOUNCEMENT, announcement_hash]


def make_create_coin_announcement(message) -> List[Any]:
    return [ConditionOpcode.CREATE_COIN_ANNOUNCEMENT, message]


def make_create_puzzle_announcement(message) -> List[Any]:
    return [ConditionOpcode.CREATE_PUZZLE_ANNOUNCEMENT, message]


def make_assert_my_parent_id(parent_id) -> List[Any]:
    return [ConditionOpcode.ASSERT_MY_PARENT_ID, parent_id]


def make_assert_my_puzzlehash(puzzlehash) -> List[Any]:
    return [ConditionOpcode.ASSERT_MY_PUZZLEHASH, puzzlehash]


def make_assert_my_amount(amount) -> List[Any]:
    return [ConditionOpcode.ASSERT_MY_AMOUNT, amount]
