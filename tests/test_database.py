import asyncio

import pytest
from src.util.ints import uint32, uint64
from src.consensus.constants import constants
from src.database import FullNodeStore
from src.types.full_block import FullBlock


@pytest.fixture(scope="module")
def event_loop():
    loop = asyncio.get_event_loop()
    yield loop


class TestDatabase:
    @pytest.mark.asyncio
    async def test_basic_database(self):
        db = FullNodeStore("fndb_test")
        await db._clear_database()
        genesis = FullBlock.from_bytes(constants["GENESIS_BLOCK"])

        # Save/get block
        await db.save_block(genesis)
        assert genesis == await db.get_block(genesis.header_hash)

        # Save/get sync
        for sync_mode in (False, True):
            await db.set_sync_mode(sync_mode)
            assert sync_mode == await db.get_sync_mode()

        # clear sync info
        await db.clear_sync_info()

        # add/get potential tip, get potential tips num
        await db.add_potential_tip(genesis)
        assert genesis == await db.get_potential_tip(genesis.header_hash)

        # add/get potential trunk
        header = genesis.header_block
        await db.add_potential_header(header)
        assert await db.get_potential_header(genesis.height) == header

        # Add potential block
        await db.add_potential_block(genesis)
        assert genesis == await db.get_potential_block(uint32(0))

        # Add/get candidate block
        assert await db.get_candidate_block(0) is None
        partial = (
            genesis.body,
            genesis.header_block.header.data,
            genesis.header_block.proof_of_space,
        )
        await db.add_candidate_block(genesis.header_hash, *partial)
        assert await db.get_candidate_block(genesis.header_hash) == partial

        # Add/get unfinished block
        key = (genesis.header_hash, uint64(1000))
        assert await db.get_unfinished_block(key) is None
        await db.add_unfinished_block(key, genesis)
        assert await db.get_unfinished_block(key) == genesis
        assert len(await db.get_unfinished_blocks()) == 1

        # Set/get unf block leader
        assert db.get_unfinished_block_leader() == (0, 9999999999)
        db.set_unfinished_block_leader(key)
        assert db.get_unfinished_block_leader() == key
