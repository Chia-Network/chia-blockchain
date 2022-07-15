import asyncio
from typing import Optional, List, Set

import pytest
from chia_rs import Coin

from chia.full_node.coin_store import CoinStore
from chia.full_node.singleton_store import LAUNCHER_PUZZLE_HASH
from chia.full_node.singleton_tracker import SingletonTracker
from chia.types.coin_record import CoinRecord
from chia.util.hash import std_hash
from chia.util.ints import uint32, uint64
from tests.core.full_node.stores.test_singleton_store import add_coins
from tests.util.db_connection import DBConnection

"""
Cases to test:
1. Launcher created before start, spend before start
2. Launcher created but not spent
3. Created before, spent after
4. Created after, spent after
5. Created after, not spent
6.  Test multiple singletons
7. Test multiple spends of one singleton
"""


@pytest.mark.asyncio
async def test_1_created_and_spent_before_start(db_version):
    async with DBConnection(db_version) as db_wrapper:
        coin_store = await CoinStore.create(db_wrapper)

        tracker = SingletonTracker(coin_store, asyncio.Lock(), start_threshold=1000)

        launcher_coin = Coin(std_hash((123).to_bytes(4, "big")), LAUNCHER_PUZZLE_HASH, uint64(1))
        launcher_spend = Coin(launcher_coin.name(), std_hash(b"2"), uint64(1))
        await add_coins(1, coin_store, [launcher_coin, launcher_spend])

        await tracker.start(uint32(5000))
        cr: Optional[CoinRecord] = await tracker.get_latest_coin_record_by_launcher_id(launcher_coin.name())
        assert cr is not None and cr.coin == launcher_spend and not cr.spent

        await tracker.new_peak(uint32(4900), uint32(5000))
        cr = await tracker.get_latest_coin_record_by_launcher_id(launcher_coin.name())
        assert cr is not None and cr.coin == launcher_spend and not cr.spent


@pytest.mark.asyncio
async def test_2_created_before_but_not_spent(db_version):
    async with DBConnection(db_version) as db_wrapper:
        coin_store = await CoinStore.create(db_wrapper)

        tracker = SingletonTracker(coin_store, asyncio.Lock(), start_threshold=1000)

        launcher_coin = Coin(std_hash((123).to_bytes(4, "big")), LAUNCHER_PUZZLE_HASH, uint64(1))
        await add_coins(1, coin_store, [launcher_coin])

        await tracker.start(uint32(5000))
        cr: Optional[CoinRecord] = await tracker.get_latest_coin_record_by_launcher_id(launcher_coin.name())
        assert cr is None
        await tracker.new_peak(uint32(4900), uint32(5000))
        assert cr is None


@pytest.mark.asyncio
async def test_3_created_before_spent_after(db_version):
    async with DBConnection(db_version) as db_wrapper:
        coin_store = await CoinStore.create(db_wrapper)

        tracker = SingletonTracker(coin_store, asyncio.Lock(), start_threshold=1000)

        launcher_coin = Coin(std_hash((123).to_bytes(4, "big")), LAUNCHER_PUZZLE_HASH, uint64(1))
        launcher_spend = Coin(launcher_coin.name(), std_hash(b"2"), uint64(1))
        await add_coins(1, coin_store, [launcher_coin])
        await add_coins(4500, coin_store, [launcher_spend])

        await tracker.start(uint32(5000))
        cr: Optional[CoinRecord] = await tracker.get_latest_coin_record_by_launcher_id(launcher_coin.name())
        assert cr is None

        await tracker.new_peak(uint32(4999), uint32(5000))
        cr = await tracker.get_latest_coin_record_by_launcher_id(launcher_coin.name())
        assert cr is not None and cr.coin == launcher_spend and not cr.spent


@pytest.mark.asyncio
async def test_4_created_after_spent_after(db_version):
    async with DBConnection(db_version) as db_wrapper:
        coin_store = await CoinStore.create(db_wrapper)

        tracker = SingletonTracker(coin_store, asyncio.Lock(), start_threshold=1000)

        launcher_coin = Coin(std_hash((123).to_bytes(4, "big")), LAUNCHER_PUZZLE_HASH, uint64(1))
        launcher_spend = Coin(launcher_coin.name(), std_hash(b"2"), uint64(1))
        await add_coins(4500, coin_store, [launcher_coin])
        await add_coins(4600, coin_store, [launcher_spend])

        await tracker.start(uint32(5000))
        cr: Optional[CoinRecord] = await tracker.get_latest_coin_record_by_launcher_id(launcher_coin.name())
        assert cr is None

        await tracker.new_peak(uint32(4999), uint32(5000))
        cr = await tracker.get_latest_coin_record_by_launcher_id(launcher_coin.name())
        assert cr is not None and cr.coin == launcher_spend and not cr.spent


@pytest.mark.asyncio
async def test_5_created_after_not_spent(db_version):
    async with DBConnection(db_version) as db_wrapper:
        coin_store = await CoinStore.create(db_wrapper)

        tracker = SingletonTracker(coin_store, asyncio.Lock(), start_threshold=1000)

        launcher_coin = Coin(std_hash((123).to_bytes(4, "big")), LAUNCHER_PUZZLE_HASH, uint64(1))
        await add_coins(4500, coin_store, [launcher_coin])

        await tracker.start(uint32(5000))
        cr: Optional[CoinRecord] = await tracker.get_latest_coin_record_by_launcher_id(launcher_coin.name())
        assert cr is None

        await tracker.new_peak(uint32(4999), uint32(5000))
        cr = await tracker.get_latest_coin_record_by_launcher_id(launcher_coin.name())
        assert cr is None


@pytest.mark.asyncio
async def test_6_multiple_singletons(db_version):
    async with DBConnection(db_version) as db_wrapper:
        coin_store = await CoinStore.create(db_wrapper)

        tracker = SingletonTracker(coin_store, asyncio.Lock(), start_threshold=1000)

        launcher_coins = []
        launcher_spends = []

        for i in range(2000):
            launcher_coins.append(Coin(std_hash(i.to_bytes(4, "big")), LAUNCHER_PUZZLE_HASH, uint64(1)))
            launcher_spends.append(Coin(launcher_coins[-1].name(), std_hash(b"2"), uint64(1)))
            await add_coins(i + 1, coin_store, [launcher_coins[-1]])
            await add_coins(i + 500, coin_store, [launcher_spends[-1]])

        await tracker.start(uint32(2700))

        async def assert_num_singletons(l_spends: List[Coin], num_singletons: int) -> None:
            found_singletons = 0
            for launcher_spend in l_spends:
                cr: Optional[CoinRecord] = await tracker.get_latest_coin_record_by_launcher_id(
                    launcher_spend.parent_coin_info
                )
                if cr is not None:
                    found_singletons += 1
            assert num_singletons == found_singletons

        await assert_num_singletons(launcher_spends, 1200)
        await tracker.new_peak(uint32(2699), uint32(2700))
        await assert_num_singletons(launcher_spends, 2000)


@pytest.mark.asyncio
async def test_7_multiple_spends(db_version):
    async with DBConnection(db_version) as db_wrapper:
        coin_store = await CoinStore.create(db_wrapper)

        tracker = SingletonTracker(coin_store, asyncio.Lock(), start_threshold=10)

        launcher_coins = []
        launcher_spends = []
        latest_state: Set[Coin] = set()
        for i in range(1, 21):
            launcher_coins.append(Coin(std_hash(i.to_bytes(4, "big")), LAUNCHER_PUZZLE_HASH, uint64(1)))
            launcher_spends.append(Coin(launcher_coins[-1].name(), std_hash(b"2"), uint64(1)))
            await add_coins(i + 1, coin_store, [launcher_coins[-1], launcher_spends[-1]])
            curr = launcher_spends[-1]
            for singleton_spend_index in range(40):
                curr = Coin(curr.name(), std_hash(b"2"), uint64(1))
                await add_coins(i + singleton_spend_index, coin_store, [curr])
            latest_state.add(curr)

        await tracker.start(uint32(65))

        async def num_updated_to_latest(l_spends: List[Coin]) -> int:
            fully_updated = 0
            for launcher_spend in l_spends:
                cr: Optional[CoinRecord] = await tracker.get_latest_coin_record_by_launcher_id(
                    launcher_spend.parent_coin_info
                )
                if cr is not None and cr.coin in latest_state:
                    fully_updated += 1
            return fully_updated

        assert (await num_updated_to_latest(launcher_spends)) == 15
        await tracker.new_peak(uint32(64), uint32(65))
        assert (await num_updated_to_latest(launcher_spends)) == 20
