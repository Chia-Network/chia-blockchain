from __future__ import annotations

from typing import Any

from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint64

from chia.types.condition_opcodes import ConditionOpcode


def make_create_coin_condition(puzzle_hash: bytes32, amount: uint64, memos: list[bytes]) -> list[Any]:
    condition = [ConditionOpcode.CREATE_COIN, puzzle_hash, amount]
    if len(memos) > 0:
        condition.append(memos)
    return condition


def make_reserve_fee_condition(fee: uint64) -> list[Any]:
    return [ConditionOpcode.RESERVE_FEE, fee]


def make_assert_coin_announcement(announcement_hash: bytes32) -> list[bytes]:
    return [ConditionOpcode.ASSERT_COIN_ANNOUNCEMENT, announcement_hash]


def make_assert_puzzle_announcement(announcement_hash: bytes32) -> list[bytes]:
    return [ConditionOpcode.ASSERT_PUZZLE_ANNOUNCEMENT, announcement_hash]


def make_create_coin_announcement(message: bytes) -> list[bytes]:
    return [ConditionOpcode.CREATE_COIN_ANNOUNCEMENT, message]


def make_create_puzzle_announcement(message: bytes) -> list[bytes]:
    return [ConditionOpcode.CREATE_PUZZLE_ANNOUNCEMENT, message]
