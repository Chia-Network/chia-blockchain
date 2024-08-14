from __future__ import annotations

import pytest

from chia._tests.util.db_connection import DBConnection
from chia.types.full_block import FullBlock
from chia.types.header_block import HeaderBlock
from chia.wallet.key_val_store import KeyValStore


@pytest.mark.anyio
@pytest.mark.standard_block_tools
async def test_store(bt):
    async with DBConnection(1) as db_wrapper:
        store = await KeyValStore.create(db_wrapper)
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
