from __future__ import annotations

import logging
import time
from random import randrange
from typing import List, Set

import pytest

from chia.consensus.default_constants import DEFAULT_CONSTANTS
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.hash import std_hash
from chia.util.ints import uint32, uint64, uint128
from chia.wallet.coin_selection import (
    check_for_exact_match,
    knapsack_coin_algorithm,
    select_coins,
    select_smallest_coin_over_target,
    sum_largest_coins,
)
from chia.wallet.util.tx_config import DEFAULT_COIN_SELECTION_CONFIG
from chia.wallet.util.wallet_types import WalletType
from chia.wallet.wallet_coin_record import WalletCoinRecord

log = logging.getLogger(__name__)


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
            knapsack = knapsack_coin_algorithm(
                coin_list, uint128(30000000000000), DEFAULT_CONSTANTS.MAX_COIN_AMOUNT, 999999, seed=bytes([i])
            )
            assert knapsack is not None
            assert sum([coin.amount for coin in knapsack]) >= 310000000

    def test_knapsack_coin_selection_2(self, a_hash: bytes32) -> None:
        coin_amounts = [6, 20, 40, 80, 150, 160, 203, 202, 201, 320]
        coin_amounts.sort(reverse=True)
        coin_list: List[Coin] = [Coin(a_hash, a_hash, uint64(a)) for a in coin_amounts]
        # coin_list = set([coin for a in coin_amounts])
        for i in range(100):
            knapsack = knapsack_coin_algorithm(
                coin_list, uint128(265), DEFAULT_CONSTANTS.MAX_COIN_AMOUNT, 99999, seed=bytes([i])
            )
            assert knapsack is not None
            selected_sum = sum(coin.amount for coin in list(knapsack))
            assert 265 <= selected_sum <= 281  # Selects a set of coins which does exceed by too much

    @pytest.mark.anyio
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
                DEFAULT_COIN_SELECTION_CONFIG,
                coin_list,
                {},
                logging.getLogger("test"),
                uint128(target_amount),
            )
            assert result is not None
            assert sum([coin.amount for coin in result]) >= target_amount
            assert len(result) <= 500

    @pytest.mark.anyio
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
                    Coin(a_hash, std_hash(i.to_bytes(length=32, byteorder="big")), uint64(1)),
                    uint32(1),
                    uint32(1),
                    False,
                    True,
                    WalletType(0),
                    1,
                )
            )
        # make sure coins are not identical.
        for target_amount in [10000, 9999]:
            print("Target amount: ", target_amount)
            result: Set[Coin] = await select_coins(
                spendable_amount,
                DEFAULT_COIN_SELECTION_CONFIG,
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
                    Coin(a_hash, std_hash(i.to_bytes(length=32, byteorder="big")), uint64(2000)),
                    uint32(1),
                    uint32(1),
                    False,
                    True,
                    WalletType(0),
                    1,
                )
            )
        spendable_amount = uint128(spendable_amount + 2000 * 100)
        for target_amount in [50000, 25000, 15000, 10000, 9000, 3000]:  # select the first 100 values
            dusty_result: Set[Coin] = await select_coins(
                spendable_amount,
                DEFAULT_COIN_SELECTION_CONFIG,
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

        # test when we have multiple coins under target, and a lot of dust coins.
        spendable_amount = uint128(25000 + 10000)
        new_coin_list: List[WalletCoinRecord] = []
        for i in range(5):
            new_coin_list.append(
                WalletCoinRecord(
                    Coin(a_hash, std_hash(i.to_bytes(length=32, byteorder="big")), uint64(5000)),
                    uint32(1),
                    uint32(1),
                    False,
                    True,
                    WalletType(0),
                    1,
                )
            )

        for i in range(10000):
            new_coin_list.append(
                WalletCoinRecord(
                    Coin(a_hash, std_hash(i.to_bytes(length=32, byteorder="big")), uint64(1)),
                    uint32(1),
                    uint32(1),
                    False,
                    True,
                    WalletType(0),
                    1,
                )
            )
        for target_amount in [20000, 15000, 10000, 5000]:  # select the first 100 values
            dusty_below_target: Set[Coin] = await select_coins(
                spendable_amount,
                DEFAULT_COIN_SELECTION_CONFIG,
                new_coin_list,
                {},
                logging.getLogger("test"),
                uint128(target_amount),
            )
            assert dusty_below_target is not None
            assert sum([coin.amount for coin in dusty_below_target]) >= target_amount
            for coin in dusty_below_target:
                assert coin.amount == 5000
            assert len(dusty_below_target) <= 500

    @pytest.mark.anyio
    async def test_dust_and_one_large_coin(self, a_hash: bytes32) -> None:
        # test when we have a lot of dust and 1 large coin
        spendable_amount = uint128(50000 + 10000)
        new_coin_list: List[WalletCoinRecord] = [
            WalletCoinRecord(
                Coin(a_hash, std_hash(b"123"), uint64(50000)), uint32(1), uint32(1), False, True, WalletType(0), 1
            )
        ]

        for i in range(10000):
            new_coin_list.append(
                WalletCoinRecord(
                    Coin(a_hash, std_hash(i.to_bytes(length=32, byteorder="big")), uint64(1)),
                    uint32(1),
                    uint32(1),
                    False,
                    True,
                    WalletType(0),
                    1,
                )
            )
        for target_amount in [50000, 10001, 10000, 9999]:
            dusty_below_target: Set[Coin] = await select_coins(
                spendable_amount,
                DEFAULT_COIN_SELECTION_CONFIG,
                new_coin_list,
                {},
                logging.getLogger("test"),
                uint128(target_amount),
            )
            assert dusty_below_target is not None
            assert sum([coin.amount for coin in dusty_below_target]) >= target_amount
            assert len(dusty_below_target) <= 500

    @pytest.mark.anyio
    async def test_coin_selection_failure(self, a_hash: bytes32) -> None:
        spendable_amount = uint128(10000)
        coin_list: List[WalletCoinRecord] = []
        for i in range(10000):
            coin_list.append(
                WalletCoinRecord(
                    Coin(a_hash, std_hash(i.to_bytes(length=32, byteorder="big")), uint64(1)),
                    uint32(1),
                    uint32(1),
                    False,
                    True,
                    WalletType(0),
                    1,
                )
            )
        # make sure coins are not identical.
        # test for failure
        with pytest.raises(ValueError):
            for target_amount in [10000, 9999]:
                await select_coins(
                    spendable_amount,
                    DEFAULT_COIN_SELECTION_CONFIG,
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
                    DEFAULT_COIN_SELECTION_CONFIG,
                    coin_list,
                    {},
                    logging.getLogger("test"),
                    uint128(target_amount),
                )

    @pytest.mark.anyio
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
            DEFAULT_COIN_SELECTION_CONFIG,
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
            DEFAULT_COIN_SELECTION_CONFIG,
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
            DEFAULT_COIN_SELECTION_CONFIG,
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
            DEFAULT_COIN_SELECTION_CONFIG,
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
            DEFAULT_COIN_SELECTION_CONFIG,
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
            DEFAULT_COIN_SELECTION_CONFIG,
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
            DEFAULT_COIN_SELECTION_CONFIG,
            multiple_greater_coin_list,
            {},
            logging.getLogger("test"),
            target_amount,
        )
        assert multiple_greater_result is not None
        assert sum([coin.amount for coin in multiple_greater_result]) > target_amount
        assert sum([coin.amount for coin in multiple_greater_result]) == 90000
        assert len(multiple_greater_result) == 1

    @pytest.mark.anyio
    async def test_coin_selection_difficult(self, a_hash: bytes32) -> None:
        num_coins = 40
        spendable_amount = uint128(num_coins * 1000)
        coin_list: List[WalletCoinRecord] = [
            WalletCoinRecord(
                Coin(a_hash, std_hash(i.to_bytes(4, "big")), uint64(1000)),
                uint32(1),
                uint32(1),
                False,
                True,
                WalletType(0),
                1,
            )
            for i in range(num_coins)
        ]
        target_amount = spendable_amount - 1
        result: Set[Coin] = await select_coins(
            spendable_amount,
            DEFAULT_COIN_SELECTION_CONFIG,
            coin_list,
            {},
            logging.getLogger("test"),
            uint128(target_amount),
        )
        assert result is not None
        print(result)
        print(sum([c.amount for c in result]))
        assert sum([coin.amount for coin in result]) >= target_amount

    @pytest.mark.anyio
    async def test_smallest_coin_over_amount(self, a_hash: bytes32) -> None:
        coin_list: List[Coin] = [
            Coin(a_hash, std_hash(i.to_bytes(4, "big")), uint64((39 - i) * 1000)) for i in range(40)
        ]
        assert select_smallest_coin_over_target(uint128(100), coin_list) == coin_list[39 - 1]
        assert select_smallest_coin_over_target(uint128(1000), coin_list) == coin_list[39 - 1]
        assert select_smallest_coin_over_target(uint128(1001), coin_list) == coin_list[39 - 2]
        assert select_smallest_coin_over_target(uint128(37000), coin_list) == coin_list[39 - 37]
        assert select_smallest_coin_over_target(uint128(39000), coin_list) == coin_list[39 - 39]
        assert select_smallest_coin_over_target(uint128(39001), coin_list) is None

    @pytest.mark.anyio
    async def test_sum_largest_coins(self, a_hash: bytes32) -> None:
        coin_list: List[Coin] = list(
            reversed([Coin(a_hash, std_hash(i.to_bytes(4, "big")), uint64(i)) for i in range(41)])
        )
        assert sum_largest_coins(uint128(40), coin_list) == {coin_list[0]}
        assert sum_largest_coins(uint128(79), coin_list) == {coin_list[0], coin_list[1]}
        assert sum_largest_coins(uint128(40000), coin_list) is None

    @pytest.mark.anyio
    async def test_knapsack_perf(self, a_hash: bytes32) -> None:
        start = time.time()
        coin_list: List[Coin] = [
            Coin(a_hash, std_hash(i.to_bytes(4, "big")), uint64((200000 - i) * 1000)) for i in range(200000)
        ]
        knapsack_coin_algorithm(coin_list, uint128(2000000), 9999999999999999, 500)

        # Just a sanity check, it's actually much faster than this time
        assert time.time() - start < 10000

    @pytest.mark.anyio
    async def test_coin_selection_min_coin(self, a_hash: bytes32) -> None:
        spendable_amount = uint128(5000000 + 500 + 40050)
        coin_list: List[WalletCoinRecord] = [
            WalletCoinRecord(Coin(a_hash, a_hash, uint64(5000000)), uint32(1), uint32(1), False, True, WalletType(0), 1)
        ]
        for i in range(500):
            coin_list.append(
                WalletCoinRecord(
                    Coin(a_hash, std_hash(i.to_bytes(length=32, byteorder="big")), uint64(1)),
                    uint32(1),
                    uint32(1),
                    False,
                    True,
                    WalletType(0),
                    1,
                )
            )
        for i in range(1, 90):
            coin_list.append(
                WalletCoinRecord(
                    Coin(a_hash, std_hash(i.to_bytes(length=32, byteorder="big")), uint64(i * 10)),
                    uint32(1),
                    uint32(1),
                    False,
                    True,
                    WalletType(0),
                    1,
                )
            )
        # make sure coins are not identical.
        for target_amount in [500, 1000, 50000, 500000]:
            for min_coin_amount in [10, 100, 200, 300, 1000]:
                result: Set[Coin] = await select_coins(
                    spendable_amount,
                    DEFAULT_COIN_SELECTION_CONFIG.override(min_coin_amount=uint64(min_coin_amount)),
                    coin_list,
                    {},
                    logging.getLogger("test"),
                    uint128(target_amount),
                )
                assert result is not None  # this should never happen
                assert sum(coin.amount for coin in result) >= target_amount
                for coin in result:
                    assert not coin.amount < min_coin_amount
                assert len(result) <= 500

    @pytest.mark.anyio
    async def test_coin_selection_with_excluded_coins(self) -> None:
        a_hash = std_hash(b"a")
        b_hash = std_hash(b"b")
        c_hash = std_hash(b"c")
        target_amount = uint128(2)
        spendable_coins = [
            Coin(a_hash, a_hash, uint64(3)),
            Coin(b_hash, b_hash, uint64(6)),
            Coin(c_hash, c_hash, uint64(9)),
        ]
        spendable_amount = uint128(sum(coin.amount for coin in spendable_coins))
        spendable_wallet_coin_records = [
            WalletCoinRecord(spendable_coin, uint32(1), uint32(1), False, True, WalletType(0), 1)
            for spendable_coin in spendable_coins
        ]
        excluded_coins = [Coin(a_hash, a_hash, uint64(3)), Coin(c_hash, c_hash, uint64(9))]
        # test that excluded coins are not included in the result
        selected_coins: Set[Coin] = await select_coins(
            spendable_amount,
            DEFAULT_COIN_SELECTION_CONFIG.override(excluded_coin_ids=[c.name() for c in excluded_coins]),
            spendable_wallet_coin_records,
            {},
            logging.getLogger("test"),
            amount=target_amount,
        )

        assert selected_coins is not None
        assert sum([coin.amount for coin in selected_coins]) >= target_amount
        assert len(selected_coins) == 1
        assert list(selected_coins)[0] == Coin(b_hash, b_hash, uint64(6))

        excluded_all_coins = spendable_coins
        # make sure that a failure is raised if all coins are excluded.
        with pytest.raises(ValueError):
            await select_coins(
                spendable_amount,
                DEFAULT_COIN_SELECTION_CONFIG.override(excluded_coin_ids=[c.name() for c in excluded_all_coins]),
                spendable_wallet_coin_records,
                {},
                logging.getLogger("test"),
                amount=target_amount,
            )

    @pytest.mark.anyio
    async def test_coin_selection_with_zero_amount(self, a_hash: bytes32) -> None:
        coin_amounts = [3, 6, 20, 40, 80, 150, 160, 203, 202, 201, 320]
        coin_list: List[WalletCoinRecord] = [
            WalletCoinRecord(Coin(a_hash, a_hash, uint64(a)), uint32(1), uint32(1), False, True, WalletType(0), 1)
            for a in coin_amounts
        ]
        spendable_amount = uint128(sum(coin_amounts))

        # validate that a zero amount is handled correctly
        target_amount = uint128(0)
        zero_amount_result: Set[Coin] = await select_coins(
            spendable_amount,
            DEFAULT_COIN_SELECTION_CONFIG,
            coin_list,
            {},
            logging.getLogger("test"),
            target_amount,
        )
        assert zero_amount_result is not None
        assert sum([coin.amount for coin in zero_amount_result]) >= target_amount
        assert len(zero_amount_result) == 1
        # make sure that a failure is properly raised if we don't have any coins.
        with pytest.raises(ValueError):
            await select_coins(
                uint128(0),
                DEFAULT_COIN_SELECTION_CONFIG,
                [],
                {},
                logging.getLogger("test"),
                target_amount,
            )
