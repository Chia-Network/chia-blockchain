import asyncio
from pathlib import Path
from secrets import token_bytes
import aiosqlite
import pytest

from chia.types.blockchain_format.coin import Coin
from chia.util.db_wrapper import DBWrapper
from chia.util.ints import uint64

from chia.wallet.wallet_interested_store import WalletInterestedStore


@pytest.fixture(scope="module")
def event_loop():
    loop = asyncio.get_event_loop()
    yield loop


class TestWalletInterestedStore:
    @pytest.mark.asyncio
    async def test_store(self):
        db_filename = Path("wallet_store_test.db")

        if db_filename.exists():
            db_filename.unlink()

        db_connection = await aiosqlite.connect(db_filename)
        db_wrapper = DBWrapper(db_connection)
        store = await WalletInterestedStore.create(db_wrapper)
        try:
            coin_1 = Coin(token_bytes(32), token_bytes(32), uint64(12312))
            coin_2 = Coin(token_bytes(32), token_bytes(32), uint64(12312))
            assert (await store.get_interested_coin_ids()) == []
            await store.add_interested_coin_id(coin_1.name())
            assert (await store.get_interested_coin_ids()) == [coin_1.name()]
            await store.add_interested_coin_id(coin_1.name())
            assert (await store.get_interested_coin_ids()) == [coin_1.name()]
            await store.add_interested_coin_id(coin_2.name())
            assert set(await store.get_interested_coin_ids()) == {coin_1.name(), coin_2.name()}
            puzzle_hash = token_bytes(32)
            assert len(await store.get_interested_puzzle_hashes()) == 0

            await store.add_interested_puzzle_hash(puzzle_hash, 2)
            assert len(await store.get_interested_puzzle_hashes()) == 1
            await store.add_interested_puzzle_hash(puzzle_hash, 2)
            assert len(await store.get_interested_puzzle_hashes()) == 1
            assert (await store.get_interested_puzzle_hash_wallet_id(puzzle_hash)) == 2
            await store.add_interested_puzzle_hash(puzzle_hash, 3)
            assert len(await store.get_interested_puzzle_hashes()) == 1

            assert (await store.get_interested_puzzle_hash_wallet_id(puzzle_hash)) == 3
            await store.remove_interested_puzzle_hash(puzzle_hash)
            assert (await store.get_interested_puzzle_hash_wallet_id(puzzle_hash)) is None
            assert len(await store.get_interested_puzzle_hashes()) == 0

        finally:
            await db_connection.close()
            db_filename.unlink()
