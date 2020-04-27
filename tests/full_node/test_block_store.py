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
        try:
            await db._clear_database()

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

            unspent_store = await CoinStore.create(connection)
            b: Blockchain = await Blockchain.create(unspent_store, db, test_constants)

            assert (await db.get_lca()) == blocks[-3].header_hash
            assert b.lca_block.header_hash == (await db.get_lca())

            b_2: Blockchain = await Blockchain.create(unspent_store, db, test_constants)
            assert (await db.get_lca()) == blocks[-3].header_hash
            assert b_2.lca_block.header_hash == (await db.get_lca())

        except Exception:
            await connection.close()
            await connection_2.close()
            await connection_3.close()
            db_filename.unlink()
            db_filename_2.unlink()
            raise

        await connection.close()
        await connection_2.close()
        await connection_3.close()
        db_filename.unlink()
        db_filename_2.unlink()
        db_filename_3.unlink()
