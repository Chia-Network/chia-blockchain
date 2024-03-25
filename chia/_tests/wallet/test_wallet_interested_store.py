from __future__ import annotations

import random

import pytest

from chia._tests.util.db_connection import DBConnection
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.ints import uint64
from chia.wallet.wallet_interested_store import WalletInterestedStore


class TestWalletInterestedStore:
    @pytest.mark.anyio
    async def test_store(self, seeded_random: random.Random):
        async with DBConnection(1) as db_wrapper:
            store = await WalletInterestedStore.create(db_wrapper)
            coin_1 = Coin(bytes32.random(seeded_random), bytes32.random(seeded_random), uint64(12312))
            coin_2 = Coin(bytes32.random(seeded_random), bytes32.random(seeded_random), uint64(12312))
            assert (await store.get_interested_coin_ids()) == []
            await store.add_interested_coin_id(coin_1.name())
            assert (await store.get_interested_coin_ids()) == [coin_1.name()]
            await store.add_interested_coin_id(coin_1.name())
            assert (await store.get_interested_coin_ids()) == [coin_1.name()]
            await store.add_interested_coin_id(coin_2.name())
            assert set(await store.get_interested_coin_ids()) == {coin_1.name(), coin_2.name()}
            await store.remove_interested_coin_id(coin_1.name())
            assert set(await store.get_interested_coin_ids()) == {coin_2.name()}
            puzzle_hash = bytes32.random(seeded_random)
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
