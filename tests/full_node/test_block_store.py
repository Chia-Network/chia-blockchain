import asyncio
from pathlib import Path
import sqlite3
import random

import aiosqlite
import pytest
from src.full_node.block_store import BlockStore
from src.full_node.coin_store import CoinStore
from src.full_node.blockchain import Blockchain
from src.types.full_block import FullBlock
from tests.setup_nodes import test_constants, bt


@pytest.fixture(scope="module")
def event_loop():
    loop = asyncio.get_event_loop()
    yield loop


class TestBlockStore:
    @pytest.mark.asyncio
    async def test_block_store(self):
        assert sqlite3.threadsafety == 1
        block_1 = bt.create_genesis_block(test_constants, seed=b"1")
        block_2 = bt.create_genesis_block(test_constants, seed=b"2")
        block_3 = bt.create_genesis_block(test_constants, seed=b"3")
        blocks = [block_1, block_2, block_3]

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
        # db_2 = await BlockStore.create(connection_2)
        await BlockStore.create(connection_2)
        db_3 = await BlockStore.create(connection_3)
        try:
            genesis = FullBlock.from_bytes(test_constants.GENESIS_BLOCK)

            # Save/get block
            for block in blocks:
                await db.add_block(block)
                assert block == await db.get_block(block.header_hash)

            assert len(await db.get_blocks_at([1])) == 0
            assert len(await db.get_blocks_at([0])) == 3

            # Get sub blocks
            assert len(await db.get_sub_blocks()) == len(blocks)

            # for block in blocks:
            #     await b.receive_block(block)
            #
            # assert b.lca_block == blocks[-3].header
            # assert set(b.tips) == set([blocks[-3].header, blocks[-2].header, blocks[-1].header])
            # left = sorted(b.tips, key=lambda t: t.height)
            # right = sorted((await db_3.get_tips()), key=lambda t: t.height)
            # assert left == right

        except Exception:
            await connection.close()
            await connection_2.close()
            await connection_3.close()
            db_filename.unlink()
            db_filename_2.unlink()
            db_filename_3.unlink()
            # b.shut_down()
            raise

        await connection.close()
        await connection_2.close()
        await connection_3.close()
        db_filename.unlink()
        db_filename_2.unlink()
        db_filename_3.unlink()
        # b.shut_down()

    # @pytest.mark.asyncio
    # async def test_deadlock(self):
    #     blocks = bt.get_consecutive_blocks(test_constants, 10, [], 9, b"0")
    #     db_filename = Path("blockchain_test.db")
    #
    #     if db_filename.exists():
    #         db_filename.unlink()
    #
    #     connection = await aiosqlite.connect(db_filename)
    #     db = await BlockStore.create(connection)
    #     tasks = []
    #
    #     for i in range(10000):
    #         rand_i = random.randint(0, 10)
    #         if random.random() < 0.5:
    #             tasks.append(asyncio.create_task(db.add_block(blocks[rand_i])))
    #         if random.random() < 0.5:
    #             tasks.append(asyncio.create_task(db.get_block(blocks[rand_i].header_hash)))
    #     await asyncio.gather(*tasks)
    #     await connection.close()
    #     db_filename.unlink()
