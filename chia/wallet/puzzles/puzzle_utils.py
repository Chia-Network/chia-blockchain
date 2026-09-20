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
