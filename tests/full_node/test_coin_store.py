import asyncio
from typing import Any, Dict
from pathlib import Path

import aiosqlite
import pytest

from src.full_node.blockchain import Blockchain, ReceiveBlockResult
from src.full_node.coin_store import CoinStore
from src.full_node.block_store import BlockStore
from tests.block_tools import BlockTools
from src.consensus.constants import constants as consensus_constants

bt = BlockTools()

test_constants: Dict[str, Any] = consensus_constants.copy()
test_constants.update(
    {
        "DIFFICULTY_STARTING": 5,
        "DISCRIMINANT_SIZE_BITS": 16,
        "BLOCK_TIME_TARGET": 10,
        "MIN_BLOCK_TIME": 2,
        "DIFFICULTY_EPOCH": 12,  # The number of blocks per epoch
        "DIFFICULTY_DELAY": 3,  # EPOCH / WARP_FACTOR
        "MIN_ITERS_STARTING": 50 * 2,
    }
)
test_constants["GENESIS_BLOCK"] = bytes(
    bt.create_genesis_block(test_constants, bytes([0] * 32), b"0")
)


@pytest.fixture(scope="module")
def event_loop():
    loop = asyncio.get_event_loop()
    yield loop


class TestCoinStore:
    @pytest.mark.asyncio
    async def test_basic_coin_store(self):
        blocks = bt.get_consecutive_blocks(test_constants, 9, [], 9, b"0")

        db_path = Path("fndb_test.db")
        if db_path.exists():
            db_path.unlink()
        connection = await aiosqlite.connect(db_path)
        db = await CoinStore.create(connection)

        # Save/get block
        for block in blocks:
            await db.new_lca(block)
            unspent = await db.get_coin_record(block.header.data.coinbase.name())
            unspent_fee = await db.get_coin_record(block.header.data.fees_coin.name())
            assert block.header.data.coinbase == unspent.coin
            assert block.header.data.fees_coin == unspent_fee.coin

        await connection.close()
        Path("fndb_test.db").unlink()

    @pytest.mark.asyncio
    async def test_set_spent(self):
        blocks = bt.get_consecutive_blocks(test_constants, 9, [], 9, b"0")

        db_path = Path("fndb_test.db")
        if db_path.exists():
            db_path.unlink()
        connection = await aiosqlite.connect(db_path)
        db = await CoinStore.create(connection)

        # Save/get block
        for block in blocks:
            await db.new_lca(block)
            unspent = await db.get_coin_record(block.header.data.coinbase.name())
            unspent_fee = await db.get_coin_record(block.header.data.fees_coin.name())
            assert block.header.data.coinbase == unspent.coin
            assert block.header.data.fees_coin == unspent_fee.coin

            await db.set_spent(unspent.coin.name(), block.height)
            await db.set_spent(unspent_fee.coin.name(), block.height)
            unspent = await db.get_coin_record(block.header.data.coinbase.name())
            unspent_fee = await db.get_coin_record(block.header.data.fees_coin.name())
            assert unspent.spent == 1
            assert unspent_fee.spent == 1

        await connection.close()
        Path("fndb_test.db").unlink()

    @pytest.mark.asyncio
    async def test_rollback(self):
        blocks = bt.get_consecutive_blocks(test_constants, 9, [], 9, b"0")

        db_path = Path("fndb_test.db")
        if db_path.exists():
            db_path.unlink()
        connection = await aiosqlite.connect(db_path)
        db = await CoinStore.create(connection)

        # Save/get block
        for block in blocks:
            await db.new_lca(block)
            unspent = await db.get_coin_record(block.header.data.coinbase.name())
            unspent_fee = await db.get_coin_record(block.header.data.fees_coin.name())
            assert block.header.data.coinbase == unspent.coin
            assert block.header.data.fees_coin == unspent_fee.coin

            await db.set_spent(unspent.coin.name(), block.height)
            await db.set_spent(unspent_fee.coin.name(), block.height)
            unspent = await db.get_coin_record(block.header.data.coinbase.name())
            unspent_fee = await db.get_coin_record(block.header.data.fees_coin.name())
            assert unspent.spent == 1
            assert unspent_fee.spent == 1

        reorg_index = 4
        await db.rollback_lca_to_block(reorg_index)

        for c, block in enumerate(blocks):
            unspent = await db.get_coin_record(block.header.data.coinbase.name())
            unspent_fee = await db.get_coin_record(block.header.data.fees_coin.name())
            if c <= reorg_index:
                assert unspent.spent == 1
                assert unspent_fee.spent == 1
            else:
                assert unspent is None
                assert unspent_fee is None

        await connection.close()
        Path("fndb_test.db").unlink()

    @pytest.mark.asyncio
    async def test_basic_reorg(self):
        blocks = bt.get_consecutive_blocks(test_constants, 100, [], 9)
        db_path = Path("blockchain_test.db")
        if db_path.exists():
            db_path.unlink()
        connection = await aiosqlite.connect(db_path)
        coin_store = await CoinStore.create(connection)
        store = await BlockStore.create(connection)
        b: Blockchain = await Blockchain.create(coin_store, store, test_constants)
        try:

            for i in range(1, len(blocks)):
                await b.receive_block(blocks[i])
            assert b.get_current_tips()[0].height == 100

            for c, block in enumerate(blocks):
                unspent = await coin_store.get_coin_record(
                    block.header.data.coinbase.name(), block.header
                )
                unspent_fee = await coin_store.get_coin_record(
                    block.header.data.fees_coin.name(), block.header
                )
                assert unspent.spent == 0
                assert unspent_fee.spent == 0
                assert unspent.confirmed_block_index == block.height
                assert unspent.spent_block_index == 0
                assert unspent.name == block.header.data.coinbase.name()
                assert unspent_fee.name == block.header.data.fees_coin.name()

            blocks_reorg_chain = bt.get_consecutive_blocks(
                test_constants, 30, blocks[:90], 9, b"1"
            )

            for i in range(1, len(blocks_reorg_chain)):
                reorg_block = blocks_reorg_chain[i]
                result, removed, error_code = await b.receive_block(reorg_block)
                if reorg_block.height < 90:
                    assert result == ReceiveBlockResult.ALREADY_HAVE_BLOCK
                elif reorg_block.height < 99:
                    assert result == ReceiveBlockResult.ADDED_AS_ORPHAN
                elif reorg_block.height >= 100:
                    assert result == ReceiveBlockResult.ADDED_TO_HEAD
                    unspent = await coin_store.get_coin_record(
                        reorg_block.header.data.coinbase.name(), reorg_block.header
                    )
                    assert unspent.name == reorg_block.header.data.coinbase.name()
                    assert unspent.confirmed_block_index == reorg_block.height
                    assert unspent.spent == 0
                    assert unspent.spent_block_index == 0
                assert error_code is None
            assert b.get_current_tips()[0].height == 119
        except Exception as e:
            await connection.close()
            Path("blockchain_test.db").unlink()
            b.shut_down()
            raise e

        await connection.close()
        Path("blockchain_test.db").unlink()
        b.shut_down()

    @pytest.mark.asyncio
    async def test_get_puzzle_hash(self):
        num_blocks = 20
        blocks = bt.get_consecutive_blocks(test_constants, num_blocks, [], 9)
        db_path = Path("blockchain_test.db")
        if db_path.exists():
            db_path.unlink()
        connection = await aiosqlite.connect(db_path)
        coin_store = await CoinStore.create(connection)
        store = await BlockStore.create(connection)
        b: Blockchain = await Blockchain.create(coin_store, store, test_constants)
        try:
            for i in range(1, len(blocks)):
                await b.receive_block(blocks[i])
            assert b.get_current_tips()[0].height == num_blocks
            unspent = await coin_store.get_coin_record(
                blocks[1].header.data.coinbase.name(), blocks[-1].header
            )
            unspent_puzzle_hash = unspent.coin.puzzle_hash

            coins = await coin_store.get_coin_records_by_puzzle_hash(
                unspent_puzzle_hash, blocks[-1].header
            )
            assert len(coins) == (num_blocks + 1) * 2
        except Exception as e:
            await connection.close()
            Path("blockchain_test.db").unlink()
            b.shut_down()
            raise e

        await connection.close()
        Path("blockchain_test.db").unlink()
        b.shut_down()
