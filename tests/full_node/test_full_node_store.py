import asyncio
from secrets import token_bytes
from pathlib import Path
from typing import Any, Dict
import sqlite3
import random

import aiosqlite
import pytest
from src.full_node.full_node_store import FullNodeStore
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


class TestFullNodeStore:
    @pytest.mark.asyncio
    async def test_basic_store(self):
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

        db = await FullNodeStore.create(connection)
        db_2 = await FullNodeStore.create(connection_2)
        try:
            # Add/get candidate block
            assert db.get_candidate_block(0) is None
            partial = (
                blocks[5].transactions_generator,
                blocks[5].transactions_filter,
                blocks[5].header.data,
                blocks[5].proof_of_space,
            )
            db.add_candidate_block(blocks[5].header_hash, *partial)
            assert db.get_candidate_block(blocks[5].header_hash) == partial
            db.clear_candidate_blocks_below(uint32(8))
            assert db.get_candidate_block(blocks[5].header_hash) is None

            # Proof of time heights
            chall_iters = (bytes32(bytes([1] * 32)), uint32(32532535))
            chall_iters_2 = (bytes32(bytes([3] * 32)), uint32(12522535))
            assert db.get_proof_of_time_heights(chall_iters) is None
            db.add_proof_of_time_heights(chall_iters, 5)
            db.add_proof_of_time_heights(chall_iters_2, 7)
            db.clear_proof_of_time_heights_below(6)
            assert db.get_proof_of_time_heights(chall_iters) is None
            assert db.get_proof_of_time_heights(chall_iters_2) is not None

            # Add/get unfinished block
            i = 1
            for block in blocks:
                key = (block.header_hash, uint64(1000))

                # Different database should have different data
                await db_2.add_unfinished_block(key, block)

                assert await db.get_unfinished_block(key) is None
                await db.add_unfinished_block(key, block)
                assert await db.get_unfinished_block(key) == block
                assert len(await db.get_unfinished_blocks()) == i
                i += 1
            await db.clear_unfinished_blocks_below(uint32(5))
            assert len(await db.get_unfinished_blocks()) == 5

            # Set/get unf block leader
            assert db.get_unfinished_block_leader() == (0, (1 << 64) - 1)
            db.set_unfinished_block_leader(key)
            assert db.get_unfinished_block_leader() == key

            assert db.get_disconnected_block(blocks[0].prev_header_hash) is None
            # Disconnected blocks
            for block in blocks:
                db.add_disconnected_block(block)
                db.get_disconnected_block(block.prev_header_hash) == block

            db.clear_disconnected_blocks_below(uint32(5))
            assert db.get_disconnected_block(blocks[4].prev_header_hash) is None

            h_hash_1 = bytes32(token_bytes(32))
            assert not db.seen_unfinished_block(h_hash_1)
            assert db.seen_unfinished_block(h_hash_1)
            await db.clear_seen_unfinished_blocks()
            assert not db.seen_unfinished_block(h_hash_1)

        except Exception:
            await connection.close()
            await connection_2.close()
            await connection_3.close()
            db_filename.unlink()
            db_filename_2.unlink()
            raise

        # Different database should have different data
        db_3 = await FullNodeStore.create(connection_3)
        assert db_3.get_unfinished_block_leader() == (0, (1 << 64) - 1)

        await connection.close()
        await connection_2.close()
        await connection_3.close()
        db_filename.unlink()
        db_filename_2.unlink()
        db_filename_3.unlink()
