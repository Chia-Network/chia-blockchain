from __future__ import annotations

from chia.types.blockchain_format.program import Program
from chia.types.coin_spend import CoinSpend
from chia.wallet.util.compute_hints import compute_spend_hints_and_additions
from tests.util.misc import CoinGenerator, coin_creation_args


def test_compute_spend_hints_and_additions() -> None:
    coin_generator = CoinGenerator()
    parent_coin = coin_generator.get()
    hinted_coins = [coin_generator.get(parent_coin.coin.name(), include_hint=i % 2 == 0) for i in range(10)]
    create_coin_args = [coin_creation_args(create_coin) for create_coin in hinted_coins]
    coin_spend = CoinSpend(
        parent_coin.coin,
        Program.to(1),
        Program.to(create_coin_args),
    )
    expected_dict = {hinted_coin.coin.name(): hinted_coin for hinted_coin in hinted_coins}
    assert compute_spend_hints_and_additions(coin_spend) == expected_dict
