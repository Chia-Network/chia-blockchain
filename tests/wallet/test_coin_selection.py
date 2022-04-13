import logging
from random import randrange
from typing import List, Set

import pytest

from chia.consensus.default_constants import DEFAULT_CONSTANTS
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.hash import std_hash
from chia.util.ints import uint32, uint64, uint128
from chia.wallet.coin_selection import check_for_exact_match, knapsack_coin_algorithm, select_coins
from chia.wallet.util.wallet_types import WalletType
from chia.wallet.wallet_coin_record import WalletCoinRecord


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
        amounts = list(range(1, coins_to_append))
        amounts.sort(reverse=True)
        coin_list: List[Coin] = [Coin(a_hash, a_hash, uint64(100000000 * a)) for a in amounts]
        for i in range(tries):
            knapsack = knapsack_coin_algorithm(coin_list, uint128(30000000000000), DEFAULT_CONSTANTS.MAX_COIN_AMOUNT)
            assert knapsack is not None
            assert sum([coin.amount for coin in knapsack]) >= 310000000

    def test_knapsack_coin_selection_2(self, a_hash: bytes32) -> None:
        coin_amounts = [6, 20, 40, 80, 150, 160, 203, 202, 201, 320]
        coin_amounts.sort(reverse=True)
        coin_list: List[Coin] = [Coin(a_hash, a_hash, uint64(a)) for a in coin_amounts]
        # coin_list = set([coin for a in coin_amounts])
        for i in range(100):
            knapsack = knapsack_coin_algorithm(coin_list, uint128(265), DEFAULT_CONSTANTS.MAX_COIN_AMOUNT)
            assert knapsack is not None
            selected_sum = sum(coin.amount for coin in list(knapsack))
            assert 265 <= selected_sum <= 280  # Selects a set of coins which does exceed by too much

    @pytest.mark.asyncio
    async def test_coin_selection_randomly(self, a_hash: bytes32) -> None:
        coin_base_amounts = [3, 6, 20, 40, 80, 150, 160, 203, 202, 201, 320]
        coin_amounts = []
        spendable_amount = 0
        # this is possibly overkill, but it's a good test.
        for i in range(3000):
            for amount in coin_base_amounts:
                c_amount = randrange(1, 10000000) * amount
                coin_amounts.append(c_amount)
                spendable_amount += c_amount
        spendable_amount = uint128(spendable_amount)

        coin_list: List[WalletCoinRecord] = [
            WalletCoinRecord(Coin(a_hash, a_hash, uint64(a)), uint32(1), uint32(1), False, True, WalletType(0), 1)
            for a in coin_amounts
        ]
        for target_amount in coin_amounts[:100]:  # select the first 100 values
            result: Set[Coin] = await select_coins(
                spendable_amount,
                DEFAULT_CONSTANTS.MAX_COIN_AMOUNT,
                coin_list,
                {},
                logging.getLogger("test"),
                uint128(target_amount),
            )
            assert result is not None
            assert sum([coin.amount for coin in result]) >= target_amount
            assert len(result) <= 500

    @pytest.mark.asyncio
    async def test_coin_selection_with_dust(self, a_hash: bytes32) -> None:
        spendable_amount = uint128(5000000000000 + 10000)
        coin_list: List[WalletCoinRecord] = [
            WalletCoinRecord(
                Coin(a_hash, a_hash, uint64(5000000000000)), uint32(1), uint32(1), False, True, WalletType(0), 1
            )
        ]
        for i in range(10000):
            coin_list.append(
                WalletCoinRecord(
                    Coin(a_hash, std_hash(i), uint64(1)), uint32(1), uint32(1), False, True, WalletType(0), 1
                )
            )
        # make sure coins are not identical.
        for target_amount in [10000, 9999]:
            result: Set[Coin] = await select_coins(
                spendable_amount,
                DEFAULT_CONSTANTS.MAX_COIN_AMOUNT,
                coin_list,
                {},
                logging.getLogger("test"),
                uint128(target_amount),
            )
            assert result is not None
            assert sum([coin.amount for coin in result]) >= target_amount
            assert len(result) == 1  # only one coin should be selected

        for i in range(100):
            coin_list.append(
                WalletCoinRecord(
                    Coin(a_hash, std_hash(i), uint64(2000)), uint32(1), uint32(1), False, True, WalletType(0), 1
                )
            )
        spendable_amount = uint128(spendable_amount + 2000 * 100)
        for target_amount in [50000, 25000, 15000, 10000, 9000, 3000]:  # select the first 100 values
            dusty_result: Set[Coin] = await select_coins(
                spendable_amount,
                DEFAULT_CONSTANTS.MAX_COIN_AMOUNT,
                coin_list,
                {},
                logging.getLogger("test"),
                uint128(target_amount),
            )
            assert dusty_result is not None
            assert sum([coin.amount for coin in dusty_result]) >= target_amount
            for coin in dusty_result:
                assert coin.amount > 1
            assert len(dusty_result) <= 500

    @pytest.mark.asyncio
    async def test_coin_selection_failure(self, a_hash: bytes32) -> None:
        spendable_amount = uint128(10000)
        coin_list: List[WalletCoinRecord] = []
        for i in range(10000):
            coin_list.append(
                WalletCoinRecord(
                    Coin(a_hash, std_hash(i), uint64(1)), uint32(1), uint32(1), False, True, WalletType(0), 1
                )
            )
        # make sure coins are not identical.
        # test for failure
        with pytest.raises(ValueError):
            for target_amount in [10000, 9999]:
                await select_coins(
                    spendable_amount,
                    DEFAULT_CONSTANTS.MAX_COIN_AMOUNT,
                    coin_list,
                    {},
                    logging.getLogger("test"),
                    uint128(target_amount),
                )
        # test not enough coin failure.
        with pytest.raises(ValueError):
            for target_amount in [10001, 20000]:
                await select_coins(
                    spendable_amount,
                    DEFAULT_CONSTANTS.MAX_COIN_AMOUNT,
                    coin_list,
                    {},
                    logging.getLogger("test"),
                    uint128(target_amount),
                )

    @pytest.mark.asyncio
    async def test_coin_selection(self, a_hash: bytes32) -> None:
        coin_amounts = [3, 6, 20, 40, 80, 150, 160, 203, 202, 201, 320]
        coin_list: List[WalletCoinRecord] = [
            WalletCoinRecord(Coin(a_hash, a_hash, uint64(a)), uint32(1), uint32(1), False, True, WalletType(0), 1)
            for a in coin_amounts
        ]
        spendable_amount = uint128(sum(coin_amounts))

        # check for exact match
        target_amount = uint128(40)
        exact_match_result: Set[Coin] = await select_coins(
            spendable_amount,
            DEFAULT_CONSTANTS.MAX_COIN_AMOUNT,
            coin_list,
            {},
            logging.getLogger("test"),
            target_amount,
        )
        assert exact_match_result is not None
        assert sum([coin.amount for coin in exact_match_result]) >= target_amount
        assert len(exact_match_result) == 1

        # check for match of 2
        target_amount = uint128(153)
        match_2: Set[Coin] = await select_coins(
            spendable_amount,
            DEFAULT_CONSTANTS.MAX_COIN_AMOUNT,
            coin_list,
            {},
            logging.getLogger("test"),
            target_amount,
        )
        assert match_2 is not None
        assert sum([coin.amount for coin in match_2]) == target_amount
        assert len(match_2) == 2
        # check for match of at least 3. it is random after all.
        target_amount = uint128(541)
        match_3: Set[Coin] = await select_coins(
            spendable_amount,
            DEFAULT_CONSTANTS.MAX_COIN_AMOUNT,
            coin_list,
            {},
            logging.getLogger("test"),
            target_amount,
        )
        assert match_3 is not None
        assert sum([coin.amount for coin in match_3]) >= target_amount
        assert len(match_3) >= 3

        # check for match of all
        target_amount = spendable_amount
        match_all: Set[Coin] = await select_coins(
            spendable_amount,
            DEFAULT_CONSTANTS.MAX_COIN_AMOUNT,
            coin_list,
            {},
            logging.getLogger("test"),
            target_amount,
        )
        assert match_all is not None
        assert sum([coin.amount for coin in match_all]) == target_amount
        assert len(match_all) == len(coin_list)

        # test smallest greater than target
        greater_coin_amounts = [1, 2, 5, 20, 400, 700]
        greater_coin_list: List[WalletCoinRecord] = [
            WalletCoinRecord(Coin(a_hash, a_hash, uint64(a)), uint32(1), uint32(1), False, True, WalletType(0), 1)
            for a in greater_coin_amounts
        ]
        greater_spendable_amount = uint128(sum(greater_coin_amounts))
        target_amount = uint128(625)
        smallest_result: Set[Coin] = await select_coins(
            greater_spendable_amount,
            DEFAULT_CONSTANTS.MAX_COIN_AMOUNT,
            greater_coin_list,
            {},
            logging.getLogger("test"),
            target_amount,
        )
        assert smallest_result is not None
        assert sum([coin.amount for coin in smallest_result]) > target_amount
        assert len(smallest_result) == 1

        # test smallest greater than target with only 1 large coin.
        single_greater_coin_list: List[WalletCoinRecord] = [
            WalletCoinRecord(Coin(a_hash, a_hash, uint64(70000)), uint32(1), uint32(1), False, True, WalletType(0), 1)
        ]
        single_greater_spendable_amount = uint128(70000)
        target_amount = uint128(50000)
        single_greater_result: Set[Coin] = await select_coins(
            single_greater_spendable_amount,
            DEFAULT_CONSTANTS.MAX_COIN_AMOUNT,
            single_greater_coin_list,
            {},
            logging.getLogger("test"),
            target_amount,
        )
        assert single_greater_result is not None
        assert sum([coin.amount for coin in single_greater_result]) > target_amount
        assert len(single_greater_result) == 1

        # test smallest greater than target with only multiple larger then target coins.
        multiple_greater_coin_amounts = [90000, 100000, 120000, 200000, 100000]
        multiple_greater_coin_list: List[WalletCoinRecord] = [
            WalletCoinRecord(Coin(a_hash, a_hash, uint64(a)), uint32(1), uint32(1), False, True, WalletType(0), 1)
            for a in multiple_greater_coin_amounts
        ]
        multiple_greater_spendable_amount = uint128(sum(multiple_greater_coin_amounts))
        target_amount = uint128(70000)
        multiple_greater_result: Set[Coin] = await select_coins(
            multiple_greater_spendable_amount,
            DEFAULT_CONSTANTS.MAX_COIN_AMOUNT,
            multiple_greater_coin_list,
            {},
            logging.getLogger("test"),
            target_amount,
        )
        assert multiple_greater_result is not None
        assert sum([coin.amount for coin in multiple_greater_result]) > target_amount
        assert sum([coin.amount for coin in multiple_greater_result]) == 90000
        assert len(multiple_greater_result) == 1
