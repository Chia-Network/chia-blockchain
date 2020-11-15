import asyncio
from typing import Dict

import pytest
from src.full_node.sub_block_record import SubBlockRecord

from src.full_node.make_proof_of_weight import create_sub_epoch_segments, get_sub_epoch_block_num
from src.types.sized_bytes import bytes32
from src.util.ints import uint32
from tests.setup_nodes import test_constants, bt


@pytest.fixture(scope="module")
def event_loop():
    loop = asyncio.get_event_loop()
    yield loop


class TestWeightProof:
    @pytest.mark.asyncio
    async def test_create_sub_epoch_segments(self, empty_blockchain):
        assert empty_blockchain.get_peak() is None
        blocks = bt.get_consecutive_blocks(test_constants, 500)

        for block in range(blocks):
            empty_blockchain.receive_block(blocks)
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
