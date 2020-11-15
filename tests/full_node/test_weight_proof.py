import asyncio
from pathlib import Path

import aiosqlite
import pytest

from src.full_node.block_store import BlockStore
from src.full_node.blockchain import Blockchain
from src.full_node.coin_store import CoinStore
from src.full_node.make_proof_of_weight import create_sub_epoch_segments, get_sub_epoch_block_num
from src.util.ints import uint32
from tests.setup_nodes import test_constants, bt


@pytest.fixture(scope="module")
def event_loop():
    loop = asyncio.get_event_loop()
    yield loop


# todo this is duplicated code from blockchain.py
@pytest.fixture(scope="function")
async def empty_blockchain():
    """
    Provides a list of 10 valid blocks, as well as a blockchain with 9 blocks added to it.
    """
    db_path = Path("blockchain_test.db")
    if db_path.exists():
        db_path.unlink()
    connection = await aiosqlite.connect(db_path)
    coin_store = await CoinStore.create(connection)
    store = await BlockStore.create(connection)
    bc1 = await Blockchain.create(coin_store, store, test_constants)
    assert bc1.get_peak() is None

    yield bc1

    await connection.close()
    bc1.shut_down()


class TestWeightProof:
    @pytest.mark.asyncio
    async def test_create_sub_epoch_segments(self, empty_blockchain):
        assert empty_blockchain.get_peak() is None
        blocks = bt.get_consecutive_blocks(test_constants, 500)

        for block in blocks:
            empty_blockchain.receive_block(block)
        curr = blocks[-1]
        while True:
            # next sub block
            curr = empty_blockchain.sub_blocks[curr.prev_header_hash]
            # if end of sub-epoch
            if curr.sub_epoch_summary_included is not None:
                break

        sub_epoch_blocks_n: uint32 = get_sub_epoch_block_num(test_constants, curr, empty_blockchain.sub_blocks)

        segments = create_sub_epoch_segments(
            test_constants,
            curr,
            sub_epoch_blocks_n,
            empty_blockchain.sub_blocks,
            uint32(1),
            empty_blockchain.block_store,
        )
        assert segments is not None

    # @pytest.mark.asyncio
    # async def test_make_weight_proof(self):

    # @pytest.mark.asyncio
    # async def test_make_weight_proof(self):

    # @pytest.mark.asyncio
    # test_get_sub_epoch_block_num(self):

    # @pytest.mark.asyncio
    # test_validate_weight_proof
