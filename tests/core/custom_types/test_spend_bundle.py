from __future__ import annotations

import random
import unittest
from typing import List, Tuple

import pytest
from chia_rs import G2Element

from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_spend import CoinSpend, make_spend
from chia.types.condition_opcodes import ConditionOpcode
from chia.types.spend_bundle import SpendBundle
from chia.util.errors import ValidationError

BLANK_SPEND_BUNDLE = SpendBundle(coin_spends=[], aggregated_signature=G2Element())
NULL_SIGNATURE = "0xc" + "0" * 191


class TestStructStream(unittest.TestCase):
    def test_round_trip(self):
        spend_bundle = BLANK_SPEND_BUNDLE
        json_dict = spend_bundle.to_json_dict()

        sb = SpendBundle.from_json_dict(json_dict)

        assert sb == spend_bundle

    def test_round_trip_with_legacy_key_parsing(self):
        spend_bundle = BLANK_SPEND_BUNDLE
        json_dict = spend_bundle.to_json_dict()
        json_dict["coin_solutions"] = None
        SpendBundle.from_json_dict(json_dict)  # testing no error because parser just looks at "coin_spends"
        json_dict["coin_solutions"] = json_dict["coin_spends"]
        del json_dict["coin_spends"]

        sb = SpendBundle.from_json_dict(json_dict)

        assert sb == spend_bundle


def rand_hash(rng: random.Random) -> bytes32:
    ret = bytearray(32)
    for i in range(32):
        ret[i] = rng.getrandbits(8)
    return bytes32(ret)


def create_spends(num: int) -> Tuple[List[CoinSpend], List[Coin]]:
    spends: List[CoinSpend] = []
    create_coin: List[Coin] = []
    rng = random.Random()

    puzzle = Program.to(1)
    puzzle_hash = puzzle.get_tree_hash()

    for i in range(num):
        target_ph = rand_hash(rng)
        conditions = [[ConditionOpcode.CREATE_COIN, target_ph, 1]]
        coin = Coin(rand_hash(rng), puzzle_hash, 1000)
        new_coin = Coin(coin.name(), target_ph, 1)
        create_coin.append(new_coin)
        spends.append(make_spend(coin, puzzle, Program.to(conditions)))

    return spends, create_coin


def test_compute_additions_create_coin() -> None:
    # make a large number of CoinSpends
    spends, create_coin = create_spends(2000)
    sb = SpendBundle(spends, G2Element())
    coins = sb.additions()
    assert coins == create_coin


def test_compute_additions_create_coin_max_cost() -> None:
    # make a large number of CoinSpends
    spends, _ = create_spends(6111)
    sb = SpendBundle(spends, G2Element())
    with pytest.raises(ValidationError, match="BLOCK_COST_EXCEEDS_MAX"):
        sb.additions()
