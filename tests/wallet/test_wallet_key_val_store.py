import asyncio
from pathlib import Path
import aiosqlite
import pytest

from chia.types.full_block import FullBlock
from chia.types.header_block import HeaderBlock
from chia.util.db_wrapper import DBWrapper
from chia.wallet.key_val_store import KeyValStore
from tests.setup_nodes import bt


@pytest.fixture(scope="module")
def event_loop():
    loop = asyncio.get_event_loop()
    yield loop


class TestWalletKeyValStore:
    @pytest.mark.asyncio
    async def test_store(self):
        db_filename = Path("wallet_store_test.db")

        if db_filename.exists():
            db_filename.unlink()

        db_connection = await aiosqlite.connect(db_filename)
        db_wrapper = DBWrapper(db_connection)
        store = await KeyValStore.create(db_wrapper)
        try:
            blocks = bt.get_consecutive_blocks(20)
            block: FullBlock = blocks[0]
            block_2: FullBlock = blocks[1]

            assert (await store.get_object("a", FullBlock)) is None
            await store.set_object("a", block)
            assert await store.get_object("a", FullBlock) == block
            await store.set_object("a", block)
            assert await store.get_object("a", FullBlock) == block
            await store.set_object("a", block_2)
            await store.set_object("a", block_2)
            assert await store.get_object("a", FullBlock) == block_2
            await store.remove_object("a")
            assert (await store.get_object("a", FullBlock)) is None

            for block in blocks:
                assert (await store.get_object(block.header_hash.hex(), FullBlock)) is None
                await store.set_object(block.header_hash.hex(), block)
                assert (await store.get_object(block.header_hash.hex(), FullBlock)) == block

            # Wrong type
            await store.set_object("a", block_2)
            with pytest.raises(Exception):
                await store.get_object("a", HeaderBlock)

        finally:
            await db_connection.close()
            db_filename.unlink()
