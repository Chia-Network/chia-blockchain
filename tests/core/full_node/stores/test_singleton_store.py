import asyncio
from secrets import token_bytes
from typing import List

import pytest
from chia_rs import Coin

from chia.full_node.coin_store import CoinStore
from chia.full_node.singleton_store import SingletonStore, LAUNCHER_PUZZLE_HASH, MAX_REORG_SIZE
from chia.util.hash import std_hash
from chia.util.ints import uint64, uint32
from tests.util.db_connection import DBConnection


def test_coin() -> Coin:
    return Coin(token_bytes(32), std_hash(b"456"), uint64(1))


async def add_coins(height: int, coin_store: CoinStore, coins: List[Coin]) -> None:
    reward_coins = {test_coin() for i in range(2)}
    await coin_store.new_block(uint32(height), uint64(1000000), reward_coins, coins, [])


@pytest.mark.asyncio
async def test_basic_singleton_store(db_version):
    async with DBConnection(db_version) as db_wrapper:
        coin_store = await CoinStore.create(db_wrapper)
        store = SingletonStore(asyncio.Lock())

        # Create singletons
        launcher_coins, launcher_spends = [], []
        for i in range(10):
            launcher_coins.append(Coin(std_hash(i.to_bytes(4, "big")), LAUNCHER_PUZZLE_HASH, uint64(1)))
            launcher_spends.append(Coin(launcher_coins[-1].name(), std_hash(b"2"), uint64(1)))

        await add_coins(1, coin_store, launcher_coins)
        await add_coins(2, coin_store, launcher_spends)

        launcher_coins_2, launcher_spends_2 = [], []
        for i in range(10, 20):
            launcher_coins_2.append(Coin(std_hash(i.to_bytes(4, "big")), LAUNCHER_PUZZLE_HASH, uint64(1)))
            launcher_spends_2.append(Coin(launcher_coins_2[-1].name(), std_hash(b"2"), uint64(1)))

        await add_coins(3, coin_store, launcher_coins_2)
        await add_coins(4, coin_store, launcher_spends_2)

        for coin in launcher_spends + launcher_spends_2:
            cr = await coin_store.get_coin_record(coin.name())
            await store.add_singleton(coin.parent_coin_info, cr.confirmed_block_index, cr)
            # Already exists
            with pytest.raises(ValueError):
                await store.add_singleton(coin.parent_coin_info, uint32(2), cr)

        await store.set_peak_height(uint32(4))

        assert (await store.get_peak_height()) == 4

        # Get the latest state
        for lc, ls in zip(launcher_coins + launcher_coins_2, launcher_spends + launcher_spends_2):
            cr = await store.get_latest_coin_record_by_launcher_id(lc.name())
            assert cr.coin == ls

        state_updates = []
        for coin in launcher_spends + launcher_spends_2:
            state_updates.append(Coin(coin.name(), std_hash(b"2"), uint64(1)))

        await add_coins(uint32(6), coin_store, state_updates)

        # State not yet updated
        for n, lc in enumerate(launcher_coins + launcher_coins_2):
            cr = await store.get_latest_coin_record_by_launcher_id(lc.name())
            assert cr.name != state_updates[n].name()

        # Update store state
        await store.set_peak_height(uint32(6))
        for coin in state_updates:
            cr = await coin_store.get_coin_record(coin.name())
            launcher_id = (await coin_store.get_coin_record(cr.coin.parent_coin_info)).coin.parent_coin_info
            await store.add_state(launcher_id, cr)

        # Now it's updated
        for n, lc in enumerate(launcher_coins + launcher_coins_2):
            cr = await store.get_latest_coin_record_by_launcher_id(lc.name())
            assert cr.name == state_updates[n].name()

        # Remove a singleton
        await store.remove_singleton(launcher_coins[0].name())
        assert (await store.get_latest_coin_record_by_launcher_id(launcher_coins[0].name())) is None

        launcher_id = launcher_coins[1].name()
        assert store._singleton_history[launcher_id].last_non_recent_state is None
        assert len(store._singleton_history[launcher_id].recent_history) == 1

        latest_state_coin = state_updates[1]
        for height in range(7, 200):
            cr = await coin_store.get_coin_record(latest_state_coin.name())
            if height == 7:
                with pytest.raises(ValueError):
                    await store.add_state(launcher_id, cr)
            else:
                await store.add_state(launcher_id, cr)
            latest_state_coin = Coin(cr.name, std_hash(b"2"), uint64(1))
            await add_coins(height, coin_store, [latest_state_coin])
            await store.set_peak_height(uint32(height))

        assert (await store.get_latest_coin_record_by_launcher_id(launcher_id)).confirmed_block_index == 198
        assert store.is_recent(uint32(200))
        assert not store.is_recent(uint32(60))

        assert store._singleton_history[launcher_id].last_non_recent_state is not None
        assert 110 >= len(store._singleton_history[launcher_id].recent_history) >= 100

        for height in range(200, 350):
            await store.set_peak_height(uint32(height))

        assert len(store._singleton_history[launcher_id].recent_history) == 0

        await store.rollback(uint32(200), coin_store)
        assert len(store._singleton_history[launcher_id].recent_history) == (198 - MAX_REORG_SIZE - 1)
