from __future__ import annotations

from secrets import token_bytes

import pytest

from chia.types.blockchain_format.coin import Coin
from chia.util.ints import uint64
from chia.wallet.wallet_interested_store import WalletInterestedStore
from tests.util.db_connection import DBConnection


class TestWalletInterestedStore:
    @pytest.mark.asyncio
    async def test_store(self):
        async with DBConnection(1) as db_wrapper:
            store = await WalletInterestedStore.create(db_wrapper)
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
