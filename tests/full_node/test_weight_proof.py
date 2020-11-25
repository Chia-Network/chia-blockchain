import asyncio
from typing import Dict
import pytest

from src.consensus.blockchain import ReceiveBlockResult
from tests.full_node.test_blockchain import empty_blockchain
from src.full_node.weight_proof import (
    create_sub_epoch_segments,
    get_sub_epoch_block_num,
    full_block_to_header,
)
from src.types.header_block import HeaderBlock
from src.types.sized_bytes import bytes32
from src.util.ints import uint32
from tests.setup_nodes import test_constants, bt


@pytest.fixture(scope="module")
def event_loop():
    loop = asyncio.get_event_loop()
    yield loop


@pytest.fixture(scope="function")
async def default_blocks():
    yield bt.get_consecutive_blocks(200)


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


def get_sub_epoch_start(blockchain, last_hash):
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
    async def test_get_sub_epoch_block_num_basic(self, empty_blockchain, default_blocks):
        assert empty_blockchain.get_peak() is None
        header_cache: Dict[bytes32, HeaderBlock] = {}
        blockchain = empty_blockchain
        for block in default_blocks:
            result, err, _ = await blockchain.receive_block(block)
            assert result == ReceiveBlockResult.NEW_PEAK
            header_cache[block.header_hash] = full_block_to_header(block)

        sub_epoch_start = get_sub_epoch_start(blockchain, default_blocks[-1].header_hash)
        print("first block of last sub epoch ", sub_epoch_start.height)
        block_rec = blockchain.sub_blocks[default_blocks[-1].header_hash]
        sub_epoch_blocks_n: uint32 = get_sub_epoch_block_num(block_rec, blockchain.sub_blocks)
        assert sub_epoch_blocks_n > 0
        assert sub_epoch_blocks_n == default_blocks[-1].height - sub_epoch_start.height
        # todo better assertions
        print("sub epoch block num ", sub_epoch_blocks_n)

    @pytest.mark.asyncio
    async def test_create_sub_epoch_segments(self, empty_blockchain, default_blocks):
        assert empty_blockchain.get_peak() is None
        header_cache: Dict[bytes32, HeaderBlock] = {}
        blockchain = empty_blockchain
        for block in default_blocks:
            if block.finished_sub_slots is not None and len(block.finished_sub_slots) > 0:
                print("block ", block.height, "deficit ", block.finished_sub_slots[-1].reward_chain.deficit)
            result, err, _ = await blockchain.receive_block(block)
            assert result == ReceiveBlockResult.NEW_PEAK
            header_cache[block.header_hash] = full_block_to_header(block)
        curr = get_sub_epoch_start(blockchain, default_blocks[-1].prev_header_hash)
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
