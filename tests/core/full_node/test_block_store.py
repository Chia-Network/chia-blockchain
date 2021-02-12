import asyncio
import random
from pathlib import Path
import sqlite3

import aiosqlite
import pytest
from src.full_node.block_store import BlockStore
from src.consensus.blockchain import Blockchain
from src.full_node.coin_store import CoinStore
from tests.setup_nodes import test_constants, bt


@pytest.fixture(scope="module")
def event_loop():
    loop = asyncio.get_event_loop()
    yield loop


class TestBlockStore:
    @pytest.mark.asyncio
    async def test_block_store(self):
        assert sqlite3.threadsafety == 1
        blocks = bt.get_consecutive_blocks(10)

        db_filename = Path("blockchain_test.db")
        db_filename_2 = Path("blockchain_test2.db")

        if db_filename.exists():
            db_filename.unlink()
        if db_filename_2.exists():
            db_filename_2.unlink()

        connection = await aiosqlite.connect(db_filename)
        connection_2 = await aiosqlite.connect(db_filename_2)

        # Use a different file for the blockchain
        coin_store_2 = await CoinStore.create(connection_2)
        store_2 = await BlockStore.create(connection_2)
        bc = await Blockchain.create(coin_store_2, store_2, test_constants)

        store = await BlockStore.create(connection)
        await BlockStore.create(connection_2)
        try:
            # Save/get block
            for block in blocks:
                await bc.receive_block(block)
                block_record = bc.block_record(block.header_hash)
                block_record_hh = block_record.header_hash
                await store.add_full_block(block, block_record)
                await store.add_full_block(block, block_record)
                assert block == await store.get_full_block(block.header_hash)
                assert block == await store.get_full_block(block.header_hash)
                assert block_record == (await store.get_block_record(block_record_hh))
                await store.set_peak(block_record.header_hash)
                await store.set_peak(block_record.header_hash)

            assert len(await store.get_full_blocks_at([1])) == 1
            assert len(await store.get_full_blocks_at([0])) == 1
            assert len(await store.get_full_blocks_at([100])) == 0

            # Get blocks
            block_record_records = await store.get_block_records()
            assert len(block_record_records[0]) == len(blocks)

            # Peak is correct
            assert block_record_records[1] == blocks[-1].header_hash

        except Exception:
            await connection.close()
            await connection_2.close()
            db_filename.unlink()
            db_filename_2.unlink()
            raise

        await connection.close()
        await connection_2.close()
        db_filename.unlink()
        db_filename_2.unlink()

    @pytest.mark.asyncio
    async def test_deadlock(self):
        """
        This test was added because the store was deadlocking in certain situations, when fetching and
        adding blocks repeatedly. The issue was patched.
        """
        blocks = bt.get_consecutive_blocks(10)
        db_filename = Path("blockchain_test.db")
        db_filename_2 = Path("blockchain_test2.db")

        if db_filename.exists():
            db_filename.unlink()
        if db_filename_2.exists():
            db_filename_2.unlink()

        connection = await aiosqlite.connect(db_filename)
        connection_2 = await aiosqlite.connect(db_filename_2)
        store = await BlockStore.create(connection)

        coin_store_2 = await CoinStore.create(connection_2)
        store_2 = await BlockStore.create(connection_2)
        bc = await Blockchain.create(coin_store_2, store_2, test_constants)
        block_records = []
        for block in blocks:
            await bc.receive_block(block)
            block_records.append(bc.block_record(block.header_hash))
        tasks = []

        for i in range(10000):
            rand_i = random.randint(0, 9)
            if random.random() < 0.5:
                tasks.append(asyncio.create_task(store.add_full_block(blocks[rand_i], block_records[rand_i])))
            if random.random() < 0.5:
                tasks.append(asyncio.create_task(store.get_full_block(blocks[rand_i].header_hash)))
        await asyncio.gather(*tasks)
        await connection.close()
        await connection_2.close()
        db_filename.unlink()
        db_filename_2.unlink()
