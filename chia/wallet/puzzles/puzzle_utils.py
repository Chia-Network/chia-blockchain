from __future__ import annotations

from typing import Any, List

from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.condition_opcodes import ConditionOpcode
from chia.util.ints import uint64


def make_create_coin_condition(puzzle_hash: bytes32, amount: uint64, memos: List[bytes]) -> List[Any]:
    condition = [ConditionOpcode.CREATE_COIN, puzzle_hash, amount]
    if len(memos) > 0:
        condition.append(memos)
    return condition


def make_reserve_fee_condition(fee: uint64) -> List[Any]:
    return [ConditionOpcode.RESERVE_FEE, fee]


def make_assert_coin_announcement(announcement_hash: bytes32) -> List[bytes]:
    return [ConditionOpcode.ASSERT_COIN_ANNOUNCEMENT, announcement_hash]


def make_assert_puzzle_announcement(announcement_hash: bytes32) -> List[bytes]:
    return [ConditionOpcode.ASSERT_PUZZLE_ANNOUNCEMENT, announcement_hash]


def make_create_coin_announcement(message: bytes) -> List[bytes]:
    return [ConditionOpcode.CREATE_COIN_ANNOUNCEMENT, message]


def make_create_puzzle_announcement(message: bytes) -> List[bytes]:
    return [ConditionOpcode.CREATE_PUZZLE_ANNOUNCEMENT, message]
