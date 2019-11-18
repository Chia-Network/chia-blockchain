import asyncio

import pytest
from bson.binary import Binary
from bson.codec_options import CodecOptions, TypeRegistry
from motor import motor_asyncio

from src.consensus.constants import constants
from src.database import FullNodeStore
from src.types.body import Body
from src.types.full_block import FullBlock
from src.types.proof_of_space import ProofOfSpace
from src.types.sized_bytes import bytes32
from src.util.ints import uint32, uint64
from src.util.streamable import Streamable


@pytest.fixture(scope="module")
def event_loop():
    loop = asyncio.get_event_loop()
    yield loop
    loop.close()


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
        assert await db.get_potential_heads_number() == 0

        # add/get potential head, get potential heads num
        await db.add_potential_head(genesis.header_hash)
        assert await db.get_potential_heads_number() == 1
        await db.add_potential_head(genesis.header_hash, genesis)
        assert await db.get_potential_heads_number() == 1
        assert genesis == await db.get_potential_head(genesis.header_hash)

        # add/get potential trunk
        trunk = genesis.trunk_block
        await db.add_potential_trunk(trunk)
        assert await db.get_potential_trunk(genesis.height) == trunk

        # Add potential block
        await db.add_potential_block(genesis)
        assert genesis == await db.get_potential_block(0)

        # Add/get candidate block
        assert await db.get_candidate_block(0) is None
        partial = (
            genesis.body,
            genesis.trunk_block.header.data,
            genesis.trunk_block.proof_of_space,
        )
        await db.add_candidate_block(genesis.header_hash, *partial)
        assert await db.get_candidate_block(genesis.header_hash) == partial

        # Add/get unfinished block
        key = (genesis.header_hash, 1000)
        assert await db.get_unfinished_block(key) is None
        await db.add_unfinished_block(key, genesis)
        assert await db.get_unfinished_block(key) == genesis

        # Set/get unf block leader
        assert db.get_unfinished_block_leader() is None
        db.set_unfinished_block_leader(key)
        assert db.get_unfinished_block_leader() == key
