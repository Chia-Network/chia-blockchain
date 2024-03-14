from __future__ import annotations

from typing import Any, Dict, List, Tuple

import pytest

from chia._tests.util.misc import CoinGenerator, coin_creation_args
from chia.consensus.default_constants import DEFAULT_CONSTANTS
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32, bytes48
from chia.types.coin_spend import make_spend
from chia.util.errors import ValidationError
from chia.util.ints import uint64
from chia.wallet.lineage_proof import LineageProof, LineageProofField
from chia.wallet.util.compute_hints import HintedCoin, compute_spend_hints_and_additions
from chia.wallet.util.merkle_utils import list_to_binary_tree
from chia.wallet.util.tx_config import (
    DEFAULT_COIN_SELECTION_CONFIG,
    DEFAULT_TX_CONFIG,
    CoinSelectionConfigLoader,
    TXConfigLoader,
)


def test_compute_spend_hints_and_additions() -> None:
    coin_generator = CoinGenerator()
    parent_coin = coin_generator.get()
    hinted_coins = [coin_generator.get(parent_coin.coin.name(), include_hint=i % 2 == 0) for i in range(10)]
    create_coin_args = [coin_creation_args(create_coin) for create_coin in hinted_coins]
    coin_spend = make_spend(
        parent_coin.coin,
        Program.to(1),
        Program.to(create_coin_args),
    )
    expected_dict = {hinted_coin.coin.name(): hinted_coin for hinted_coin in hinted_coins}
    assert compute_spend_hints_and_additions(coin_spend)[0] == expected_dict

    not_hinted_coin = HintedCoin(Coin(parent_coin.coin.name(), bytes32([0] * 32), uint64(0)), None)
    assert compute_spend_hints_and_additions(
        make_spend(parent_coin.coin, Program.to(1), Program.to([[51, bytes32([0] * 32), 0, [["not", "a"], "hint"]]]))
    )[0] == {not_hinted_coin.coin.name(): not_hinted_coin}

    with pytest.raises(ValidationError):
        compute_spend_hints_and_additions(
            make_spend(
                parent_coin.coin, Program.to(1), Program.to([[51, bytes32([0] * 32), 0] for _ in range(0, 10000)])
            )
        )
    with pytest.raises(ValidationError):
        compute_spend_hints_and_additions(
            make_spend(
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


def test_list_to_binary_tree() -> None:
    assert list_to_binary_tree([1]) == 1
    assert list_to_binary_tree([1, 2]) == (1, 2)
    assert list_to_binary_tree([1, 2, 3]) == ((1, 2), 3)
    assert list_to_binary_tree([1, 2, 3, 4]) == ((1, 2), (3, 4))
    assert list_to_binary_tree([1, 2, 3, 4, 5]) == (((1, 2), 3), (4, 5))
    with pytest.raises(ValueError):
        list_to_binary_tree([])


@pytest.mark.parametrize(
    "serializations",
    [
        (tuple(), Program.to(None), []),
        ((bytes32([0] * 32),), Program.to([bytes32([0] * 32)]), [LineageProofField.PARENT_NAME]),
        (
            (bytes32([0] * 32), bytes32([0] * 32)),
            Program.to([bytes32([0] * 32), bytes32([0] * 32)]),
            [LineageProofField.PARENT_NAME, LineageProofField.INNER_PUZZLE_HASH],
        ),
        (
            (bytes32([0] * 32), bytes32([0] * 32), uint64(0)),
            Program.to([bytes32([0] * 32), bytes32([0] * 32), uint64(0)]),
            [LineageProofField.PARENT_NAME, LineageProofField.INNER_PUZZLE_HASH, LineageProofField.AMOUNT],
        ),
    ],
)
def test_lineage_proof_varargs(serializations: Tuple[Tuple[Any, ...], Program, List[LineageProofField]]) -> None:
    var_args, expected_program, lp_fields = serializations
    assert LineageProof(*var_args).to_program() == expected_program
    assert LineageProof(*var_args) == LineageProof.from_program(expected_program, lp_fields)


@pytest.mark.parametrize(
    "serializations",
    [
        ({}, Program.to(None), []),
        ({"parent_name": bytes32([0] * 32)}, Program.to([bytes32([0] * 32)]), [LineageProofField.PARENT_NAME]),
        (
            {"parent_name": bytes32([0] * 32), "inner_puzzle_hash": bytes32([0] * 32)},
            Program.to([bytes32([0] * 32), bytes32([0] * 32)]),
            [LineageProofField.PARENT_NAME, LineageProofField.INNER_PUZZLE_HASH],
        ),
        (
            {"parent_name": bytes32([0] * 32), "inner_puzzle_hash": bytes32([0] * 32), "amount": uint64(0)},
            Program.to([bytes32([0] * 32), bytes32([0] * 32), uint64(0)]),
            [LineageProofField.PARENT_NAME, LineageProofField.INNER_PUZZLE_HASH, LineageProofField.AMOUNT],
        ),
        (
            {"parent_name": bytes32([0] * 32), "amount": uint64(0)},
            Program.to([bytes32([0] * 32), uint64(0)]),
            [LineageProofField.PARENT_NAME, LineageProofField.AMOUNT],
        ),
        (
            {"inner_puzzle_hash": bytes32([0] * 32), "amount": uint64(0)},
            Program.to([bytes32([0] * 32), uint64(0)]),
            [LineageProofField.INNER_PUZZLE_HASH, LineageProofField.AMOUNT],
        ),
        ({"amount": uint64(0)}, Program.to([uint64(0)]), [LineageProofField.AMOUNT]),
        (
            {"inner_puzzle_hash": bytes32([0] * 32)},
            Program.to([bytes32([0] * 32)]),
            [LineageProofField.INNER_PUZZLE_HASH],
        ),
    ],
)
def test_lineage_proof_kwargs(serializations: Tuple[Dict[str, Any], Program, List[LineageProofField]]) -> None:
    kwargs, expected_program, lp_fields = serializations
    assert LineageProof(**kwargs).to_program() == expected_program
    assert LineageProof(**kwargs) == LineageProof.from_program(expected_program, lp_fields)


def test_lineage_proof_errors() -> None:
    with pytest.raises(ValueError, match="Mismatch"):
        LineageProof.from_program(Program.to([]), [LineageProofField.PARENT_NAME])
    with pytest.raises(StopIteration):
        LineageProof.from_program(Program.to([bytes32([0] * 32)]), [])
    with pytest.raises(ValueError):
        LineageProof.from_program(Program.to([bytes32([1] * 32)]), [LineageProofField.AMOUNT])
    with pytest.raises(ValueError):
        LineageProof.from_program(Program.to([uint64(0)]), [LineageProofField.PARENT_NAME])
