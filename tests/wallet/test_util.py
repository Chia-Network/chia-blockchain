from __future__ import annotations

import re
from typing import Any, List

import pytest

from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_spend import CoinSpend
from chia.wallet.util.compute_hints import compute_hint_for_coin
from tests.util.misc import CoinGenerator, coin_creation_args

coin_generator = CoinGenerator()
parent_coin = coin_generator.get()
hinted_coins = [coin_generator.get(parent_coin.coin.name()) for _ in range(10)]


@pytest.mark.parametrize(
    "solution_args, coin_name, expected_error",
    [
        ([], bytes32(32 * b"0"), f"{bytes32(32 * b'0')} not found"),
        ([coin_creation_args(hinted_coins[0])], bytes32(32 * b"0"), f"{bytes32(32 * b'0')} not found"),
        (
            [coin_creation_args(hinted_coins[0], False)],
            hinted_coins[0].coin.name(),
            f"No hint found for {hinted_coins[0].coin.name()}",
        ),
        (
            [coin_creation_args(hinted_coins[0]), coin_creation_args(hinted_coins[1], False)],
            bytes32(32 * b"0"),
            f"{bytes32(32 * b'0')} not found",
        ),
    ],
)
def test_compute_hint_for_coin_failure(solution_args: List[Any], coin_name: bytes32, expected_error: str) -> None:
    coin_spend = CoinSpend(
        parent_coin.coin,
        Program.to(1),
        Program.to(solution_args),
    )
    with pytest.raises(ValueError, match=re.escape(expected_error + f" in {coin_spend}")):
        assert compute_hint_for_coin(coin_name, coin_spend)


def test_compute_hint_for_coin() -> None:
    create_coin_args = [coin_creation_args(create_coin) for create_coin in hinted_coins]
    coin_spend = CoinSpend(
        parent_coin.coin,
        Program.to(1),
        Program.to(create_coin_args),
    )
    for hinted_coin, args in zip(hinted_coins, create_coin_args):
        assert compute_hint_for_coin(hinted_coin.coin.name(), coin_spend) == hinted_coin.hint
