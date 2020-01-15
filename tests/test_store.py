import asyncio
from secrets import token_bytes
from typing import Any, Dict

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
        blocks = bt.get_consecutive_blocks(test_constants, 9, [], 9, b"0")

        db = await FullNodeStore.create("fndb_test")
        db_2 = await FullNodeStore.create("fndb_test_2")
        try:
            await db._clear_database()

            genesis = FullBlock.from_bytes(constants["GENESIS_BLOCK"])

            # Save/get block
            for block in blocks:
                await db.add_block(block)
                assert block == await db.get_block(block.header_hash)

            # Save/get sync
            for sync_mode in (False, True):
                await db.set_sync_mode(sync_mode)
                assert sync_mode == await db.get_sync_mode()

            # clear sync info
            await db.clear_sync_info()

            # add/get potential tip, get potential tips num
            await db.add_potential_tip(blocks[6])
            assert blocks[6] == await db.get_potential_tip(blocks[6].header_hash)

            # add/get potential trunk
            header = genesis.header_block
            db.add_potential_header(header)
            assert db.get_potential_header(genesis.height) == header

            # Add potential block
            await db.add_potential_block(genesis)
            assert genesis == await db.get_potential_block(uint32(0))

            # Add/get candidate block
            assert await db.get_candidate_block(0) is None
            partial = (
                blocks[5].body,
                blocks[5].header_block.header.data,
                blocks[5].header_block.proof_of_space,
            )
            await db.add_candidate_block(blocks[5].header_hash, *partial)
            assert await db.get_candidate_block(blocks[5].header_hash) == partial
            await db.clear_candidate_blocks_below(uint32(8))
            assert await db.get_candidate_block(blocks[5].header_hash) is None

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

            assert await db.get_disconnected_block(blocks[0].prev_header_hash) is None
            # Disconnected blocks
            for block in blocks:
                await db.add_disconnected_block(block)
                await db.get_disconnected_block(block.prev_header_hash) == block

            await db.clear_disconnected_blocks_below(uint32(5))
            assert await db.get_disconnected_block(blocks[4].prev_header_hash) is None

            h_hash_1 = bytes32(token_bytes(32))
            assert not db.seen_unfinished_block(h_hash_1)
            assert db.seen_unfinished_block(h_hash_1)
            db.clear_seen_unfinished_blocks()
            assert not db.seen_unfinished_block(h_hash_1)

        except Exception:
            await db.close()
            await db_2.close()
            raise

        # Different database should have different data
        db_3 = await FullNodeStore.create("fndb_test_3")
        assert db_3.get_unfinished_block_leader() == (0, (1 << 64) - 1)

        await db.close()
        await db_2.close()
        await db_3.close()
