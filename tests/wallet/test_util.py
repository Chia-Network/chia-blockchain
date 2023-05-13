from __future__ import annotations

import re
from random import shuffle
from secrets import token_bytes
from typing import Any, List

import pytest
from chia_rs import Coin

from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_spend import CoinSpend
from chia.types.condition_opcodes import ConditionOpcode
from chia.util.ints import uint64
from chia.wallet.util.compute_hints import (
    HintedCoin,
    hinted_coin_from_condition,
    hinted_coin_with_coin_id,
    hinted_coins_in_coin_spend,
)


def random_coin() -> Coin:
    return Coin(bytes32(token_bytes(32)), token_bytes(32), uint64.from_bytes(token_bytes(8)))


def creation_args(coin: Coin, include_hint: bool = True) -> List[Any]:
    memos = [bytes32(token_bytes(32))] if include_hint else []
    return [ConditionOpcode.CREATE_COIN, coin.puzzle_hash, coin.amount, memos]


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
    coin = random_coin()
    coin_creation_args = creation_args(coin)
    hinted_coin = HintedCoin(coin, coin_creation_args[-1][0])
    assert hinted_coin_from_condition(Program.to(coin_creation_args), coin.parent_coin_info) == hinted_coin


@pytest.mark.parametrize(
    "solution_args",
    [
        [],
        [creation_args(random_coin())],
        [creation_args(random_coin()), creation_args(random_coin())],
    ],
)
def test_hinted_coins_in_coin_spend_failure(solution_args: List[Any]) -> None:
    coin_spend = CoinSpend(
        random_coin(),
        Program.to(1),
        Program.to(solution_args),
    )
    with pytest.raises(ValueError, match="not found in coin_spend"):
        assert hinted_coin_with_coin_id(coin_spend, bytes32(token_bytes(32)))


def test_hinted_coin_with_coin_id() -> None:
    parent_coin = random_coin()
    create_coins = [Coin(parent_coin.name(), bytes32(token_bytes(32)), uint64(1)) for _ in range(5)]
    create_coin_args = [creation_args(create_coin) for create_coin in create_coins]
    coin_spend = CoinSpend(
        parent_coin,
        Program.to(1),
        Program.to(create_coin_args),
    )
    for coin, args in zip(create_coins, create_coin_args):
        assert hinted_coin_with_coin_id(coin_spend, coin.name()) == HintedCoin(coin, args[-1][0])


def test_hinted_coins_in_coin_spend_empty() -> None:
    coin_spend = CoinSpend(
        random_coin(),
        Program.to(1),
        Program.to([]),
    )
    with pytest.raises(StopIteration):
        next(hinted_coins_in_coin_spend(coin_spend))


def test_hinted_coins_in_coin_spend() -> None:
    parent_coin = random_coin()
    create_coins = [Coin(parent_coin.name(), bytes32(token_bytes(32)), uint64(1)) for _ in range(10)]
    create_coin_args_hinted = [creation_args(create_coin) for create_coin in create_coins[0:5]]
    hinted_coins = set(HintedCoin(coin, args[-1][0]) for coin, args in zip(create_coins[0:5], create_coin_args_hinted))
    create_coin_args_not_hinted = [creation_args(create_coin, include_hint=False) for create_coin in create_coins[5:]]
    all_args = create_coin_args_hinted + create_coin_args_not_hinted
    shuffle(all_args)
    coin_spend = CoinSpend(
        parent_coin,
        Program.to(1),
        Program.to(all_args),
    )
    assert set(hinted_coins_in_coin_spend(coin_spend)) == hinted_coins
