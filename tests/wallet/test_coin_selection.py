import pytest
from chia.types.blockchain_format.coin import Coin
from chia.util.hash import std_hash
from chia.util.ints import uint64
from chia.wallet.coin_selection import check_for_exact_match, find_smallest_coin, knapsack_coin_algorithm
from chia.consensus.default_constants import DEFAULT_CONSTANTS


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
        assert check_for_exact_match(coin_list, uint64(220000)) == coin_list[0]
        assert check_for_exact_match(coin_list, uint64(22)) == coin_list[2]
        # check for no match.
        assert check_for_exact_match(coin_list, uint64(20)) is None

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
        assert find_smallest_coin(coin_list, uint64(100000), DEFAULT_CONSTANTS.MAX_COIN_AMOUNT) == coin_list[5]
        assert find_smallest_coin(coin_list, uint64(320000), DEFAULT_CONSTANTS.MAX_COIN_AMOUNT) == coin_list[0]
        # test for failure where target is greater than any available coin.
        assert find_smallest_coin(coin_list, uint64(360000), DEFAULT_CONSTANTS.MAX_COIN_AMOUNT) is None

    def test_knapsack_coin_selection(self, a_hash):
        tries = 100
        coins_to_append = 1000
        coin_list = set()
        for i in range(coins_to_append):
            coin_list.add(Coin(a_hash, a_hash, uint64(200000 * i)))
        for i in range(tries):
            knapsack = knapsack_coin_algorithm(coin_list, uint64(310000000), DEFAULT_CONSTANTS.MAX_COIN_AMOUNT)
            assert knapsack is not None
            assert sum([coin.amount for coin in knapsack]) >= 310000000
