import asyncio
from secrets import token_bytes
from pathlib import Path
from typing import Any, Dict
import sqlite3
import random

import aiosqlite
import pytest
from src.full_node.block_store import BlockStore
from src.full_node.coin_store import CoinStore
from src.full_node.blockchain import Blockchain
from src.types.full_block import FullBlock
from src.types.sized_bytes import bytes32
from src.util.ints import uint32, uint64
from tests.block_tools import BlockTools

bt = BlockTools()

test_constants: Dict[str, Any] = {
    "DIFFICULTY_STARTING": 5,
    "DISCRIMINANT_SIZE_BITS": 16,
    "BLOCK_TIME_TARGET": 10,
    "MIN_BLOCK_TIME": 2,
    "MIN_ITERS_STARTING": 100,
    "DIFFICULTY_EPOCH": 12,  # The number of blocks per epoch
    "DIFFICULTY_DELAY": 3,  # EPOCH / WARP_FACTOR
}
test_constants["GENESIS_BLOCK"] = bytes(
    bt.create_genesis_block(test_constants, bytes([0] * 32), b"0")
)


@pytest.fixture(scope="module")
def event_loop():
    loop = asyncio.get_event_loop()
    yield loop


class TestBlockStore:
    @pytest.mark.asyncio
    async def test_block_store(self):
        assert sqlite3.threadsafety == 1
        blocks = bt.get_consecutive_blocks(test_constants, 9, [], 9, b"0")
        blocks_alt = bt.get_consecutive_blocks(test_constants, 3, [], 9, b"1")
        db_filename = Path("blockchain_test.db")
        db_filename_2 = Path("blockchain_test_2.db")
        db_filename_3 = Path("blockchain_test_3.db")

        if db_filename.exists():
            db_filename.unlink()
        if db_filename_2.exists():
            db_filename_2.unlink()
        if db_filename_3.exists():
            db_filename_3.unlink()

        connection = await aiosqlite.connect(db_filename)
        connection_2 = await aiosqlite.connect(db_filename_2)
        connection_3 = await aiosqlite.connect(db_filename_3)

        db = await BlockStore.create(connection)
        db_2 = await BlockStore.create(connection_2)
        db_3 = await BlockStore.create(connection_3)
        try:
            genesis = FullBlock.from_bytes(test_constants["GENESIS_BLOCK"])

            # Save/get block
            for block in blocks:
                await db.add_block(block)
                assert block == await db.get_block(block.header_hash)

            await db.add_block(blocks_alt[2])
            assert len(await db.get_blocks_at([1, 2])) == 3

            # Get headers (added alt block also, so +1)
            assert len(await db.get_headers()) == len(blocks) + 1

            # Test LCA
            assert (await db.get_lca()) is None
            await db.set_lca(blocks[-3].header_hash)
            assert (await db.get_lca()) == blocks[-3].header
            await db.set_tips([blocks[-2].header_hash, blocks[-1].header_hash])
            assert (await db.get_tips()) == [blocks[-2].header, blocks[-1].header]

            coin_store: CoinStore = await CoinStore.create(connection_3)
            b: Blockchain = await Blockchain.create(coin_store, db_3, test_constants)

            assert b.lca_block == genesis.header
            assert b.tips == [genesis.header]
            assert await db_3.get_lca() == genesis.header
            assert await db_3.get_tips() == [genesis.header]

            for block in blocks:
                await b.receive_block(block)

            assert b.lca_block == blocks[-3].header
            assert set(b.tips) == set(
                [blocks[-3].header, blocks[-2].header, blocks[-1].header]
            )
            left = sorted(b.tips, key=lambda t: t.height)
            right = sorted((await db_3.get_tips()), key=lambda t: t.height)
            assert left == right

        except Exception:
            await connection.close()
            await connection_2.close()
            await connection_3.close()
            db_filename.unlink()
            db_filename_2.unlink()
            db_filename_3.unlink()
            b.shut_down()
            raise

        await connection.close()
        await connection_2.close()
        await connection_3.close()
        db_filename.unlink()
        db_filename_2.unlink()
        db_filename_3.unlink()
        b.shut_down()

    @pytest.mark.asyncio
    async def test_deadlock(self):
        blocks = bt.get_consecutive_blocks(test_constants, 10, [], 9, b"0")
        db_filename = Path("blockchain_test.db")

        if db_filename.exists():
            db_filename.unlink()

        connection = await aiosqlite.connect(db_filename)
        db = await BlockStore.create(connection)
        tasks = []

        for i in range(10000):
            rand_i = random.randint(0, 10)
            if random.random() < 0.5:
                tasks.append(asyncio.create_task(db.add_block(blocks[rand_i])))
            if random.random() < 0.5:
                tasks.append(
                    asyncio.create_task(db.get_block(blocks[rand_i].header_hash))
                )
        await asyncio.gather(*tasks)
        await connection.close()
        db_filename.unlink()
