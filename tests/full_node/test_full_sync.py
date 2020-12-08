import asyncio

import pytest

from src.types.peer_info import PeerInfo
from src.protocols import full_node_protocol
from src.util.ints import uint16
from tests.setup_nodes import setup_two_nodes, test_constants, bt
from tests.time_out_assert import time_out_assert


def node_height_at_least(node, h):
    if node.full_node.blockchain.get_peak() is not None:
        return node.full_node.blockchain.get_peak().sub_block_height >= h
    return False


@pytest.fixture(scope="function")
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
        # Must be larger than "sync_block_behind_threshold" in the config
        num_blocks = 40
        blocks = bt.get_consecutive_blocks(num_blocks)
        full_node_1, full_node_2, server_1, server_2 = two_nodes

        for block in blocks:
            await full_node_1.full_node.respond_sub_block(full_node_protocol.RespondSubBlock(block))

        await server_2.start_client(PeerInfo("localhost", uint16(server_1._port)), None)

        # The second node should eventually catch up to the first one, and have the
        # same tip at height num_blocks - 1 (or at least num_blocks - 3, in case we sync to below the tip)
        await time_out_assert(60, node_height_at_least, True, full_node_2, num_blocks - 3)

    @pytest.mark.asyncio
    async def test_short_sync(self, two_nodes):
        # Must be below "sync_block_behind_threshold" in the config
        num_blocks = 12
        num_blocks_2 = 9
        blocks = bt.get_consecutive_blocks(num_blocks)
        blocks_2 = bt.get_consecutive_blocks(num_blocks_2, seed=b"123")
        full_node_1, full_node_2, server_1, server_2 = two_nodes

        # 12 blocks to node_1
        for block in blocks:
            await full_node_1.full_node.respond_sub_block(full_node_protocol.RespondSubBlock(block))

        # 9 different blocks to node_2
        for block in blocks_2:
            await full_node_2.full_node.respond_sub_block(full_node_protocol.RespondSubBlock(block))

        await server_2.start_client(
            PeerInfo("localhost", uint16(server_1._port)), on_connect=full_node_2.full_node.on_connect
        )
        for i in range(10):
            await asyncio.sleep(1)
            print(full_node_2.full_node.blockchain.get_peak())
        await time_out_assert(60, node_height_at_least, True, full_node_2, num_blocks - 1)
