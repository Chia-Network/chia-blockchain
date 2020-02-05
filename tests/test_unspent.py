import asyncio
from typing import Any, Dict

import pytest

from src.blockchain import Blockchain, ReceiveBlockResult
from src.consensus.constants import constants
from src.store import FullNodeStore
from src.types.full_block import FullBlock
from src.unspent_store import UnspentStore
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


class TestUnspent:
    @pytest.mark.asyncio
    async def test_basic_unspent_store(self):
        blocks = bt.get_consecutive_blocks(test_constants, 9, [], 9, b"0")

        db = await UnspentStore.create("fndb_test")
        await db._clear_database()

        genesis = FullBlock.from_bytes(constants["GENESIS_BLOCK"])

        # Save/get block
        for block in blocks:
            await db.new_lca(block)
            unspent = await db.get_unspent(block.body.coinbase.name())
            unspent_fee = await db.get_unspent(block.body.fees_coin.name())
            assert block.body.coinbase == unspent.coin
            assert block.body.fees_coin == unspent_fee.coin

        await db.close()

    @pytest.mark.asyncio
    async def test_set_spent(self):
        blocks = bt.get_consecutive_blocks(test_constants, 9, [], 9, b"0")

        db = await UnspentStore.create("fndb_test")
        await db._clear_database()

        genesis = FullBlock.from_bytes(constants["GENESIS_BLOCK"])

        # Save/get block
        for block in blocks:
            await db.new_lca(block)
            unspent = await db.get_unspent(block.body.coinbase.name())
            unspent_fee = await db.get_unspent(block.body.fees_coin.name())
            assert block.body.coinbase == unspent.coin
            assert block.body.fees_coin == unspent_fee.coin

            await db.set_spent(unspent.coin.name(), block.height)
            await db.set_spent(unspent_fee.coin.name(), block.height)
            unspent = await db.get_unspent(block.body.coinbase.name())
            unspent_fee = await db.get_unspent(block.body.fees_coin.name())
            assert unspent.spent == 1
            assert unspent_fee.spent == 1

        await db.close()

    @pytest.mark.asyncio
    async def test_rollback(self):
        blocks = bt.get_consecutive_blocks(test_constants, 9, [], 9, b"0")

        db = await UnspentStore.create("fndb_test")
        await db._clear_database()

        genesis = FullBlock.from_bytes(constants["GENESIS_BLOCK"])

        # Save/get block
        for block in blocks:
            await db.new_lca(block)
            unspent = await db.get_unspent(block.body.coinbase.name())
            unspent_fee = await db.get_unspent(block.body.fees_coin.name())
            assert block.body.coinbase == unspent.coin
            assert block.body.fees_coin == unspent_fee.coin

            await db.set_spent(unspent.coin.name(), block.height)
            await db.set_spent(unspent_fee.coin.name(), block.height)
            unspent = await db.get_unspent(block.body.coinbase.name())
            unspent_fee = await db.get_unspent(block.body.fees_coin.name())
            assert unspent.spent == 1
            assert unspent_fee.spent == 1

        reorg_index = 4
        await db.rollback_lca_to_block(reorg_index)

        for c, block in enumerate(blocks):
            unspent = await db.get_unspent(block.body.coinbase.name())
            unspent_fee = await db.get_unspent(block.body.fees_coin.name())
            if c <= reorg_index:
                assert unspent.spent == 1
                assert unspent_fee.spent == 1
            else:
                assert unspent is None
                assert unspent_fee is None

        await db.close()

    @pytest.mark.asyncio
    async def test_basic_reorg(self):
        blocks = bt.get_consecutive_blocks(test_constants, 100, [], 9)
        unspent_store = await UnspentStore.create("blockchain_test")
        store = await FullNodeStore.create("blockchain_test")
        await store._clear_database()
        b: Blockchain = await Blockchain.create(
            {}, unspent_store, store, test_constants
        )

        for block in blocks:
            await b.receive_block(block)
        assert b.get_current_tips()[0].height == 100

        for c, block in enumerate(blocks):
            unspent = await unspent_store.get_unspent(
                block.body.coinbase.name(), block.header_block
            )
            unspent_fee = await unspent_store.get_unspent(
                block.body.fees_coin.name(), block.header_block
            )
            assert unspent.spent == 0
            assert unspent_fee.spent == 0
            assert unspent.confirmed_block_index == block.height
            assert unspent.spent_block_index == 0
            assert unspent.name == block.body.coinbase.name()
            assert unspent_fee.name == block.body.fees_coin.name()

        blocks_reorg_chain = bt.get_consecutive_blocks(
            test_constants, 30, blocks[:90], 9, b"1"
        )

        for reorg_block in blocks_reorg_chain:
            result, removed = await b.receive_block(reorg_block)
            if reorg_block.height < 90:
                assert result == ReceiveBlockResult.ALREADY_HAVE_BLOCK
            elif reorg_block.height < 99:
                assert result == ReceiveBlockResult.ADDED_AS_ORPHAN
            elif reorg_block.height >= 100:
                assert result == ReceiveBlockResult.ADDED_TO_HEAD
                unspent = await unspent_store.get_unspent(
                    reorg_block.body.coinbase.name(), reorg_block.header_block
                )
                assert unspent.name == reorg_block.body.coinbase.name()
                assert unspent.confirmed_block_index == reorg_block.height
                assert unspent.spent == 0
                assert unspent.spent_block_index == 0
        assert b.get_current_tips()[0].height == 119

        await unspent_store.close()
        await store.close()
