from typing import Set

import pytest

from chia.consensus.default_constants import DEFAULT_CONSTANTS
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.hash import std_hash
from chia.util.ints import uint64, uint128
from chia.wallet.coin_selection import check_for_exact_match, knapsack_coin_algorithm


class TestCoinSelection:
    @pytest.fixture(scope="function")
    def a_hash(self) -> bytes32:
        return std_hash(b"a")

    def test_exact_match(self, a_hash: bytes32) -> None:
        coin_list = [
            Coin(a_hash, a_hash, uint64(220000)),
            Coin(a_hash, a_hash, uint64(120000)),
            Coin(a_hash, a_hash, uint64(22)),
        ]
        assert check_for_exact_match(coin_list, uint64(220000)) == coin_list[0]
        assert check_for_exact_match(coin_list, uint64(22)) == coin_list[2]
        # check for no match.
        assert check_for_exact_match(coin_list, uint64(20)) is None

    def test_knapsack_coin_selection(self, a_hash: bytes32) -> None:
        tries = 100
        coins_to_append = 1000
        coin_list = set()
        for i in range(coins_to_append):
            coin_list.add(Coin(a_hash, a_hash, uint64(100000000 * i)))
        for i in range(tries):
            knapsack = knapsack_coin_algorithm(coin_list, uint128(30000000000000), DEFAULT_CONSTANTS.MAX_COIN_AMOUNT)
            assert knapsack is not None
            assert sum([coin.amount for coin in knapsack]) >= 310000000

    def test_knapsack_coin_selection_2(self, a_hash: bytes32) -> None:
        coin_amounts = [6, 20, 40, 80, 150, 160, 203, 202, 201, 320]
        coin_list: Set[Coin] = set([Coin(a_hash, a_hash, uint64(a)) for a in coin_amounts])
        # coin_list = set([coin for a in coin_amounts])
        for i in range(100):
            knapsack = knapsack_coin_algorithm(coin_list, uint128(265), DEFAULT_CONSTANTS.MAX_COIN_AMOUNT)
            assert knapsack is not None
            selected_sum = sum(coin.amount for coin in list(knapsack))
            assert 265 <= selected_sum <= 280  # Selects a set of coins which does exceed by too much
