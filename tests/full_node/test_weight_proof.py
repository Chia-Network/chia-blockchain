import asyncio
from typing import Dict
import pytest

from src.consensus.blockchain import ReceiveBlockResult
from src.full_node.weight_proof import (
    create_sub_epoch_segments,
    get_sub_epoch_block_num,
    full_block_to_header,
    make_weight_proof,
    validate_weight,
)
from src.types.header_block import HeaderBlock
from src.types.sized_bytes import bytes32
from src.util.ints import uint32, uint64
from tests.setup_nodes import test_constants, bt
from tests.full_node.fixtures import empty_blockchain
from tests.full_node.fixtures import default_1000_blocks as blocks


@pytest.fixture(scope="module")
def event_loop():
    loop = asyncio.get_event_loop()
    yield loop


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
    async def test_get_sub_epoch_block_num_basic(self, empty_blockchain, blocks):
        assert empty_blockchain.get_peak() is None
        header_cache: Dict[bytes32, HeaderBlock] = {}
        blockchain = empty_blockchain
        for block in blocks:
            result, err, _ = await blockchain.receive_block(block)
            assert err is None
            assert result == ReceiveBlockResult.NEW_PEAK
            header_cache[block.header_hash] = full_block_to_header(block)

        sub_epoch_start = get_sub_epoch_start(blockchain, blocks[-1].header_hash)
        print("first block of last sub epoch ", sub_epoch_start.height)
        block_rec = blockchain.sub_blocks[blocks[-1].header_hash]
        sub_epoch_blocks_n: uint32 = get_sub_epoch_block_num(block_rec, blockchain.sub_blocks)
        assert sub_epoch_blocks_n > 0
        assert sub_epoch_blocks_n == blocks[-1].height - sub_epoch_start.height
        # todo better assertions
        print("sub epoch block num ", sub_epoch_blocks_n)

    @pytest.mark.asyncio
    async def test_create_sub_epoch_segments(self, empty_blockchain, blocks):
        assert empty_blockchain.get_peak() is None
        header_cache: Dict[bytes32, HeaderBlock] = {}
        blockchain = empty_blockchain
        for block in blocks:
            result, err, _ = await blockchain.receive_block(block)
            assert err is None
            assert result == ReceiveBlockResult.NEW_PEAK
            header_cache[block.header_hash] = full_block_to_header(block)
        curr = get_sub_epoch_start(blockchain, blocks[-1].prev_header_hash)
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

    #   assert number of segments
    #   assert no gaps

    @pytest.mark.asyncio
    async def test_weight_proof(self, empty_blockchain, blocks):
        assert empty_blockchain.get_peak() is None
        header_cache: Dict[bytes32, HeaderBlock] = {}
        blockchain = empty_blockchain
        for block in blocks:
            print(f"\n validate block {block.height}")
            result, err, _ = await blockchain.receive_block(block)
            assert err is None
            assert result == ReceiveBlockResult.NEW_PEAK
            header_cache[block.header_hash] = full_block_to_header(block)

        wp = make_weight_proof(
            test_constants,
            uint32(len(header_cache)),
            blockchain.get_peak().header_hash,
            blockchain.sub_blocks,
            uint64(300),
            header_cache,
            blockchain.height_to_hash,
        )
        assert wp is not None

        #   assert number of segments
        print(f"number of challenge segments {len(wp.sub_epoch_segments)}")
        print(f"number of sub-epochs {len(wp.sub_epochs)}")
        assert len(wp.sub_epochs) > 0
        sub_epoch_n = len(wp.sub_epochs)
        curr = blockchain.sub_blocks[wp.proof_blocks[-1]]
        first_sub_epoch_summary = None
        while not sub_epoch_n == 0:
            if curr.sub_epoch_summary_included is not None:
                sub_epoch_n -= 1
                first_sub_epoch_summary = curr.sub_epoch_summary_included
            # next sub block
            curr = blockchain.sub_blocks[curr.prev_hash]
        assert validate_weight(test_constants, wp, first_sub_epoch_summary.prev_subepoch_summary_hash)

        #   assert no gaps


# @pytest.mark.asyncio
# async def test_make_weight_proof(self):

# @pytest.mark.asyncio
# test_get_sub_epoch_block_num(self):

# @pytest.mark.asyncio
# test_validate_weight_proof
