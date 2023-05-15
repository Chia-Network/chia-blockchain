from __future__ import annotations

import re
from random import shuffle
from secrets import token_bytes
from typing import Any, List

import pytest

from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_spend import CoinSpend
from chia.types.condition_opcodes import ConditionOpcode
from chia.util.ints import uint64
from chia.wallet.util.compute_hints import (
    hinted_coin_from_condition,
    hinted_coin_with_coin_id,
    hinted_coins_in_coin_spend,
)
from tests.util.misc import CoinGenerator, coin_creation_args

coin_generator = CoinGenerator()
parent_coin = coin_generator.get()
hinted_coins = [coin_generator.get(parent_coin.coin.name()) for _ in range(10)]


@pytest.mark.parametrize(
    "arguments, error",
    [
        ([ConditionOpcode.CREATE_COIN], "Not a hinted coin"),
        ([ConditionOpcode.CREATE_COIN, 1], "Not a hinted coin"),
        ([ConditionOpcode.CREATE_COIN, 1, 2], "Not a hinted coin"),
        ([ConditionOpcode.CREATE_COIN, 1, 2, 3, 4], "Not a hinted coin"),
        ([ConditionOpcode.RESERVE_FEE, 1, 2, 3], "Not a hinted coin"),
        ([ConditionOpcode.CREATE_COIN, 1, 2, 3], "Invalid coin: bad bytes32 initializer b'\\x01'"),
        ([ConditionOpcode.CREATE_COIN, bytes32(b"1" * 32), 2, []], "Invalid hint: index out of range"),
        ([ConditionOpcode.CREATE_COIN, bytes32(b"1" * 32), uint64(2), 3], "Invalid hint: bad bytes32 initializer 3"),
        (
            [ConditionOpcode.CREATE_COIN, bytes32(b"1" * 32), uint64(2), [3]],
            "Invalid hint: bad bytes32 initializer b'\\x03'",
        ),
    ],
)
def test_hinted_coin_from_condition_failures(arguments: List[Any], error: str) -> None:
    with pytest.raises(ValueError, match=re.escape(error)):
        hinted_coin_from_condition(Program.to(arguments), bytes32(b"0" * 32))


def test_hinted_coin_from_condition() -> None:
    hinted_coin = hinted_coins[0]
    parsed_hinted_coin = hinted_coin_from_condition(
        Program.to(coin_creation_args(hinted_coin)), hinted_coin.coin.parent_coin_info
    )
    assert parsed_hinted_coin == hinted_coin


@pytest.mark.parametrize(
    "solution_args",
    [
        [],
        [coin_creation_args(hinted_coins[0])],
        [coin_creation_args(hinted_coins[0]), coin_creation_args(hinted_coins[1])],
    ],
)
def test_hinted_coins_in_coin_spend_failure(solution_args: List[Any]) -> None:
    coin_spend = CoinSpend(
        hinted_coins[9].coin,
        Program.to(1),
        Program.to(solution_args),
    )
    with pytest.raises(ValueError, match="not found in coin_spend"):
        assert hinted_coin_with_coin_id(coin_spend, bytes32(token_bytes(32)))


def test_hinted_coin_with_coin_id() -> None:
    create_coin_args = [coin_creation_args(create_coin) for create_coin in hinted_coins]
    coin_spend = CoinSpend(
        parent_coin.coin,
        Program.to(1),
        Program.to(create_coin_args),
    )
    for hinted_coin, args in zip(hinted_coins, create_coin_args):
        assert hinted_coin_with_coin_id(coin_spend, hinted_coin.coin.name()) == hinted_coin


def test_hinted_coins_in_coin_spend_empty() -> None:
    coin_spend = CoinSpend(
        hinted_coins[0].coin,
        Program.to(1),
        Program.to([]),
    )
    with pytest.raises(StopIteration):
        next(hinted_coins_in_coin_spend(coin_spend))


def test_hinted_coins_in_coin_spend() -> None:
    create_coin_args_hinted = [coin_creation_args(create_coin) for create_coin in hinted_coins[0:5]]
    create_coin_args_not_hinted = [
        coin_creation_args(create_coin, include_hint=False) for create_coin in hinted_coins[5:]
    ]
    all_args = create_coin_args_hinted + create_coin_args_not_hinted
    shuffle(all_args)
    coin_spend = CoinSpend(
        parent_coin.coin,
        Program.to(1),
        Program.to(all_args),
    )
    assert set(hinted_coins_in_coin_spend(coin_spend)) == set(hinted_coins[0:5])
