import asyncio

import pytest

from src.types.peer_info import PeerInfo
from src.protocols import full_node_protocol
from src.util.ints import uint16
from tests.setup_nodes import setup_two_nodes, test_constants, bt
from tests.time_out_assert import time_out_assert


def node_height_at_least(node, h):
    if (max([h.height for h in node.full_node.blockchain.get_current_tips()])) >= h:
        return True
    return False


@pytest.fixture(scope="module")
def event_loop():
    loop = asyncio.get_event_loop()
    yield loop


class TestFullSync:
    @pytest.fixture(scope="function")
    async def two_nodes(self):
        async for _ in setup_two_nodes(test_constants):
            yield _

    @pytest.mark.asyncio
    async def test_basic_sync(self, two_nodes):
        num_blocks = 40
        blocks = bt.get_consecutive_blocks(test_constants, num_blocks, [], 10)
        full_node_1, full_node_2, server_1, server_2 = two_nodes

        for i in range(1, num_blocks):
            await full_node_1.full_node._respond_sub_block(full_node_protocol.RespondSubBlock(blocks[i]))

        await server_2.start_client(PeerInfo("localhost", uint16(server_1._port)), None)

        # The second node should eventually catch up to the first one, and have the
        # same tip at height num_blocks - 1 (or at least num_blocks - 3, in case we sync to a
        # worse tip)
        await time_out_assert(60, node_height_at_least, True, full_node_2, num_blocks - 3)

    @pytest.mark.asyncio
    async def test_short_sync(self, two_nodes):
        num_blocks = 10
        num_blocks_2 = 4
        blocks = bt.get_consecutive_blocks(test_constants, num_blocks, [], 10)
        blocks_2 = bt.get_consecutive_blocks(test_constants, num_blocks_2, [], 10, seed=b"123")
        full_node_1, full_node_2, server_1, server_2 = two_nodes

        # 10 blocks to node_1
        for i in range(1, num_blocks):
            await full_node_1.full_node._respond_sub_block(full_node_protocol.RespondSubBlock(blocks[i]))

        # 4 different blocks to node_2
        for i in range(1, num_blocks_2):
            await full_node_2.full_node._respond_sub_block(full_node_protocol.RespondSubBlock(blocks_2[i]))

        # 6th block from node_1 to node_2
        await full_node_2.full_node._respond_sub_block(full_node_protocol.RespondSubBlock(blocks[5]))

        await server_2.start_client(PeerInfo("localhost", uint16(server_1._port)), None)
        await time_out_assert(60, node_height_at_least, True, full_node_2, num_blocks - 1)
