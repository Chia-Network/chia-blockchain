import asyncio
from pathlib import Path
from typing import Dict

import aiosqlite
import pytest

from src.full_node.block_store import BlockStore
from src.full_node.blockchain import Blockchain, ReceiveBlockResult
from src.full_node.coin_store import CoinStore
from src.full_node.weight_proof import create_sub_epoch_segments, get_sub_epoch_block_num, full_block_to_header
from src.types.header_block import HeaderBlock
from src.types.sized_bytes import bytes32
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


def count_sub_epochs(blockchain, last_hash) -> int:
    curr = blockchain.sub_blocks[last_hash]
    count = 0
    while True:
        if curr.height == 0:
            break
        # next sub block
        curr = blockchain.sub_blocks[curr.prev_hash]
        # if end of sub-epoch
        if curr.sub_epoch_summary_included is not None:
            count += 1
    return count


def get_last_sub_epoch_end(blockchain, last_hash):
    curr = blockchain.sub_blocks[last_hash]
    while True:
        if curr.height == 0:
            break
        # next sub block
        curr = blockchain.sub_blocks[curr.prev_hash]
        # if end of sub-epoch
        if curr.sub_epoch_summary_included is not None:
            curr = blockchain.sub_blocks[curr.prev_hash]
            break
    return curr


class TestWeightProof:
    @pytest.mark.asyncio
    async def test_get_sub_epoch_block_num_basic(self, empty_blockchain):
        assert empty_blockchain.get_peak() is None
        blocks = bt.get_consecutive_blocks(test_constants, 200)
        header_cache: Dict[bytes32, HeaderBlock] = {}
        blockchain = empty_blockchain
        for block in blocks:
            result, err, _ = await blockchain.receive_block(block)
            assert result == ReceiveBlockResult.NEW_PEAK
            header_cache[block.header_hash] = full_block_to_header(block)
            curr = get_last_sub_epoch_end(blockchain, blockchain.sub_blocks[blocks[-1].header_hash])
        print("first block of last epoch ", curr.height)
        sub_epoch_blocks_n: uint32 = get_sub_epoch_block_num(curr, blockchain.sub_blocks)
        assert sub_epoch_blocks_n > 0
        # todo better assertions
        print("sub epoch block num ", sub_epoch_blocks_n)

    @pytest.mark.asyncio
    async def test_create_sub_epoch_segments(self, empty_blockchain):
        assert empty_blockchain.get_peak() is None
        blocks = bt.get_consecutive_blocks(test_constants, 200)
        header_cache: Dict[bytes32, HeaderBlock] = {}
        blockchain = empty_blockchain
        for block in blocks:
            if block.finished_sub_slots is not None and len(block.finished_sub_slots) > 0:
                print("block ", block.height, "deficit ", block.finished_sub_slots[-1].reward_chain.deficit)
            result, err, _ = await blockchain.receive_block(block)
            assert result == ReceiveBlockResult.NEW_PEAK
            header_cache[block.header_hash] = full_block_to_header(block)
        curr = get_last_sub_epoch_end(blockchain, blocks[-1].prev_header_hash)
        sub_epoch_blocks_n: uint32 = get_sub_epoch_block_num(curr, blockchain.sub_blocks)
        print("sub epoch block num ", sub_epoch_blocks_n)
        segments = create_sub_epoch_segments(
            test_constants,
            curr,
            sub_epoch_blocks_n,
            empty_blockchain.sub_blocks,
            uint32(2),
            header_cache,
            blockchain.height_to_hash,
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
