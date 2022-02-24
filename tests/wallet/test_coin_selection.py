from typing import Set

import pytest

from chia.consensus.default_constants import DEFAULT_CONSTANTS
from chia.types.blockchain_format.coin import Coin
from chia.util.hash import std_hash
from chia.util.ints import uint64, uint128
from chia.wallet.coin_selection import check_for_exact_match, find_smallest_coin, knapsack_coin_algorithm


class TestCoinSelection:
    @pytest.fixture(scope="function")
    def a_hash(self):
        return std_hash(b"a")

    def test_exact_match(self, a_hash):
        coin_list = [
            Coin(a_hash, a_hash, uint64(220000)),
            Coin(a_hash, a_hash, uint64(120000)),
            Coin(a_hash, a_hash, uint64(22)),
        ]
        assert check_for_exact_match(coin_list, uint128(220000)) == coin_list[0]
        assert check_for_exact_match(coin_list, uint128(22)) == coin_list[2]
        # check for no match.
        assert check_for_exact_match(coin_list, uint128(20)) is None

    def test_smallest_individual_coin_selection(self, a_hash):
        coin_list = [
            Coin(a_hash, a_hash, uint64(340000)),
            Coin(a_hash, a_hash, uint64(300000)),
            Coin(a_hash, a_hash, uint64(200000)),
            Coin(a_hash, a_hash, uint64(123331)),
            Coin(a_hash, a_hash, uint64(120000)),
            Coin(a_hash, a_hash, uint64(110000)),
            Coin(a_hash, a_hash, uint64(300)),
        ]
        assert find_smallest_coin(coin_list, uint128(100000), DEFAULT_CONSTANTS.MAX_COIN_AMOUNT) == coin_list[5]
        assert find_smallest_coin(coin_list, uint128(320000), DEFAULT_CONSTANTS.MAX_COIN_AMOUNT) == coin_list[0]
        # test for failure where target is greater than any available coin.
        assert find_smallest_coin(coin_list, uint128(360000), DEFAULT_CONSTANTS.MAX_COIN_AMOUNT) is None

    def test_knapsack_coin_selection(self, a_hash):
        tries = 100
        coins_to_append = 1000
        coin_list = set()
        for i in range(coins_to_append):
            coin_list.add(Coin(a_hash, a_hash, uint64(100000000 * i)))
        for i in range(tries):
            knapsack = knapsack_coin_algorithm(coin_list, uint128(30000000000000), DEFAULT_CONSTANTS.MAX_COIN_AMOUNT)
            assert knapsack is not None
            assert sum([coin.amount for coin in knapsack]) >= 310000000

    def test_knapsack_coin_selection_2(self, a_hash):
        coin_amounts = [6, 20, 40, 80, 150, 160, 203, 202, 201, 320]
        coin_list: Set[Coin] = set([Coin(a_hash, a_hash, uint64(a)) for a in coin_amounts])
        # coin_list = set([coin for a in coin_amounts])
        for i in range(100):
            knapsack = knapsack_coin_algorithm(coin_list, uint128(265), DEFAULT_CONSTANTS.MAX_COIN_AMOUNT)
            assert knapsack is not None
            selected_sum = sum(coin.amount for coin in list(knapsack))
            assert 265 <= selected_sum <= 280  # Selects a set of coins which does exceed by too much
