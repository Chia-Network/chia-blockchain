from __future__ import annotations

import pytest

from chia.consensus.default_constants import DEFAULT_CONSTANTS
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32, bytes48
from chia.types.coin_spend import CoinSpend
from chia.util.errors import ValidationError
from chia.util.ints import uint64
from chia.wallet.util.compute_hints import HintedCoin, compute_spend_hints_and_additions
from chia.wallet.util.tx_config import (
    DEFAULT_COIN_SELECTION_CONFIG,
    DEFAULT_TX_CONFIG,
    CoinSelectionConfigLoader,
    TXConfigLoader,
)
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
    assert compute_spend_hints_and_additions(coin_spend)[0] == expected_dict

    not_hinted_coin = HintedCoin(Coin(parent_coin.coin.name(), bytes32([0] * 32), uint64(0)), None)
    assert compute_spend_hints_and_additions(
        CoinSpend(parent_coin.coin, Program.to(1), Program.to([[51, bytes32([0] * 32), 0, [["not", "a"], "hint"]]]))
    )[0] == {not_hinted_coin.coin.name(): not_hinted_coin}

    with pytest.raises(ValidationError):
        compute_spend_hints_and_additions(
            CoinSpend(
                parent_coin.coin, Program.to(1), Program.to([[51, bytes32([0] * 32), 0] for _ in range(0, 10000)])
            )
        )
    with pytest.raises(ValidationError):
        compute_spend_hints_and_additions(
            CoinSpend(
                parent_coin.coin, Program.to(1), Program.to([[50, bytes48([0] * 48), b""] for _ in range(0, 10000)])
            )
        )


def test_cs_config() -> None:
    default_cs_config = DEFAULT_COIN_SELECTION_CONFIG.to_json_dict()
    assert (
        CoinSelectionConfigLoader.from_json_dict({}).autofill(constants=DEFAULT_CONSTANTS).to_json_dict()
        == default_cs_config
    )
    assert DEFAULT_COIN_SELECTION_CONFIG.override(min_coin_amount=50).to_json_dict() == {
        **default_cs_config,
        "min_coin_amount": 50,
    }
    coin_to_exclude = CoinGenerator().get().coin
    coin_id_to_exclude = bytes32([0] * 32)
    assert CoinSelectionConfigLoader.from_json_dict(
        {
            "excluded_coins": [coin_to_exclude.to_json_dict()],
            "excluded_coin_ids": [coin_id_to_exclude.hex()],
        }
    ).autofill(constants=DEFAULT_CONSTANTS).to_json_dict() == {
        **default_cs_config,
        "excluded_coin_ids": ["0x" + coin_to_exclude.name().hex(), "0x" + coin_id_to_exclude.hex()],
    }
    assert CoinSelectionConfigLoader.from_json_dict(
        {
            "excluded_coins": [coin_to_exclude.to_json_dict()],
        }
    ).override(
        max_coin_amount=100
    ).autofill(constants=DEFAULT_CONSTANTS).to_json_dict() == {
        **default_cs_config,
        "excluded_coin_ids": ["0x" + coin_to_exclude.name().hex()],
        "max_coin_amount": 100,
    }


def test_tx_config() -> None:
    default_tx_config = DEFAULT_TX_CONFIG.to_json_dict()
    assert TXConfigLoader.from_json_dict({}).autofill(constants=DEFAULT_CONSTANTS).to_json_dict() == default_tx_config
    assert DEFAULT_TX_CONFIG.override(reuse_puzhash=True).to_json_dict() == {**default_tx_config, "reuse_puzhash": True}
    assert TXConfigLoader.from_json_dict({}).autofill(
        constants=DEFAULT_CONSTANTS, config={"reuse_public_key_for_change": {"1": True}}, logged_in_fingerprint=1
    ).to_json_dict() == {**default_tx_config, "reuse_puzhash": True}
