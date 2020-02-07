import asyncio
from secrets import token_bytes
from pathlib import Path
from typing import Any, Dict
import sqlite3
import random

import pytest
from src.consensus.constants import constants
from src.store import FullNodeStore
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
    "DIFFICULTY_FACTOR": 3,
    "DIFFICULTY_EPOCH": 12,  # The number of blocks per epoch
    "DIFFICULTY_WARP_FACTOR": 4,  # DELAY divides EPOCH in order to warp efficiently.
    "DIFFICULTY_DELAY": 3,  # EPOCH / WARP_FACTOR
}
test_constants["GENESIS_BLOCK"] = bytes(
    bt.create_genesis_block(test_constants, bytes([0] * 32), b"0")
)


@pytest.fixture(scope="module")
def event_loop():
    loop = asyncio.get_event_loop()
    yield loop


class TestStore:
    @pytest.mark.asyncio
    async def test_basic_store(self):
        assert sqlite3.threadsafety == 1
        blocks = bt.get_consecutive_blocks(test_constants, 9, [], 9, b"0")
        db_filename = Path("blockchain_test.db")
        db_filename_2 = Path("blockchain_test_2.db")
        db_filename_3 = Path("blockchain_test_3.db")

        if db_filename.exists():
            db_filename.unlink()
        if db_filename_2.exists():
            db_filename_2.unlink()
        if db_filename_3.exists():
            db_filename_3.unlink()

        db = await FullNodeStore.create(db_filename)
        db_2 = await FullNodeStore.create(db_filename_2)
        try:
            await db._clear_database()

            genesis = FullBlock.from_bytes(constants["GENESIS_BLOCK"])

            # Save/get block
            for block in blocks:
                await db.add_block(block)
                assert block == await db.get_block(block.header_hash)

            # Get headers
            assert len(await db.get_headers()) == len(blocks)

            # Save/get sync
            for sync_mode in (False, True):
                db.set_sync_mode(sync_mode)
                assert sync_mode == db.get_sync_mode()

            # clear sync info
            await db.clear_sync_info()

            # add/get potential tip, get potential tips num
            db.add_potential_tip(blocks[6])
            assert blocks[6] == db.get_potential_tip(blocks[6].header_hash)

            # Add potential block
            await db.add_potential_block(genesis)
            assert genesis == await db.get_potential_block(uint32(0))

            # Add/get candidate block
            assert db.get_candidate_block(0) is None
            partial = (
                blocks[5].body,
                blocks[5].header.data,
                blocks[5].proof_of_space,
            )
            db.add_candidate_block(blocks[5].header_hash, *partial)
            assert db.get_candidate_block(blocks[5].header_hash) == partial
            db.clear_candidate_blocks_below(uint32(8))
            assert db.get_candidate_block(blocks[5].header_hash) is None

            # Add/get unfinished block
            i = 1
            for block in blocks:
                key = (block.header_hash, uint64(1000))

                # Different database should have different data
                db_2.add_unfinished_block(key, block)

                assert db.get_unfinished_block(key) is None
                db.add_unfinished_block(key, block)
                assert db.get_unfinished_block(key) == block
                assert len(db.get_unfinished_blocks()) == i
                i += 1
            db.clear_unfinished_blocks_below(uint32(5))
            assert len(db.get_unfinished_blocks()) == 5

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
            db.clear_seen_unfinished_blocks()
            assert not db.seen_unfinished_block(h_hash_1)

        except Exception:
            await db.close()
            await db_2.close()
            db_filename.unlink()
            db_filename_2.unlink()
            raise

        # Different database should have different data
        db_3 = await FullNodeStore.create(db_filename_3)
        assert db_3.get_unfinished_block_leader() == (0, (1 << 64) - 1)

        await db.close()
        await db_2.close()
        await db_3.close()
        db_filename.unlink()
        db_filename_2.unlink()
        db_filename_3.unlink()

    @pytest.mark.asyncio
    async def test_deadlock(self):
        blocks = bt.get_consecutive_blocks(test_constants, 10, [], 9, b"0")
        db_filename = Path("blockchain_test.db")

        if db_filename.exists():
            db_filename.unlink()

        db = await FullNodeStore.create(db_filename)
        tasks = []

        for i in range(10000):
            rand_i = random.randint(0, 10)
            if random.random() < 0.5:
                tasks.append(asyncio.create_task(db.add_block(blocks[rand_i])))
            if random.random() < 0.5:
                tasks.append(
                    asyncio.create_task(db.add_potential_block(blocks[rand_i]))
                )
            if random.random() < 0.5:
                tasks.append(
                    asyncio.create_task(db.get_block(blocks[rand_i].header_hash))
                )
            if random.random() < 0.5:
                tasks.append(
                    asyncio.create_task(
                        db.get_potential_block(blocks[rand_i].header_hash)
                    )
                )
        await asyncio.gather(*tasks)
        await db.close()
        db_filename.unlink()
