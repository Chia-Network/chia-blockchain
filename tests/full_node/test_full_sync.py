# flake8: noqa: F811, F401
import asyncio

import pytest

from src.types.peer_info import PeerInfo
from src.protocols import full_node_protocol
from src.util.ints import uint16
from tests.setup_nodes import setup_two_nodes, test_constants, bt
from tests.time_out_assert import time_out_assert
from tests.full_node.fixtures import (
    empty_blockchain,
    default_400_blocks,
    default_1000_blocks,
    default_10000_blocks,
)


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
        num_blocks = 60
        blocks = bt.get_consecutive_blocks(num_blocks)
        full_node_1, full_node_2, server_1, server_2 = two_nodes

        for block in blocks:
            await full_node_1.full_node.respond_sub_block(full_node_protocol.RespondSubBlock(block))

        await server_2.start_client(PeerInfo("localhost", uint16(server_1._port)), None)

        # The second node should eventually catch up to the first one, and have the
        # same tip at height num_blocks - 1 (or at least num_blocks - 3, in case we sync to below the tip)
        await time_out_assert(60, node_height_at_least, True, full_node_2, num_blocks - 1)

    @pytest.mark.asyncio
    async def test_sync_with_sub_epochs(self, two_nodes, default_400_blocks):
        # Must be larger than "sync_block_behind_threshold" in the config
        num_blocks = len(default_400_blocks)
        blocks = default_400_blocks
        full_node_1, full_node_2, server_1, server_2 = two_nodes

        for block in blocks:
            await full_node_1.full_node.respond_sub_block(full_node_protocol.RespondSubBlock(block))

        await server_2.start_client(PeerInfo("localhost", uint16(server_1._port)), None)

        # The second node should eventually catch up to the first one, and have the
        # same tip at height num_blocks - 1 (or at least num_blocks - 3, in case we sync to below the tip)
        await time_out_assert(60, node_height_at_least, True, full_node_2, num_blocks - 1)

    @pytest.mark.asyncio
    async def test_sync_from_forkpoint(self, two_nodes, default_1000_blocks):
        # Must be larger than "sync_block_behind_threshold" in the config
        num_blocks = len(default_1000_blocks)
        blocks = default_1000_blocks
        full_node_1, full_node_2, server_1, server_2 = two_nodes

        for block in blocks:
            await full_node_1.full_node.respond_sub_block(full_node_protocol.RespondSubBlock(block))

        for i in range(int(len(default_1000_blocks) / 2)):
            await full_node_2.full_node.respond_sub_block(full_node_protocol.RespondSubBlock(default_1000_blocks[i]))

        await server_2.start_client(PeerInfo("localhost", uint16(server_1._port)), None)

        # The second node should eventually catch up to the first one, and have the
        # same tip at height num_blocks - 1 (or at least num_blocks - 3, in case we sync to below the tip)
        await time_out_assert(60, node_height_at_least, True, full_node_2, num_blocks - 1)

    @pytest.mark.asyncio
    async def test_short_sync(self, two_nodes):
        # Must be below "sync_block_behind_threshold" in the config
        num_blocks = 7
        num_blocks_2 = 3
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
            PeerInfo("localhost", uint16(server_1._port)),
            on_connect=full_node_2.full_node.on_connect,
        )
        await time_out_assert(60, node_height_at_least, True, full_node_2, num_blocks - 1)

    @pytest.mark.asyncio
    async def test_sync_different_chains(self, two_nodes, default_1000_blocks, default_400_blocks):
        # Must be larger than "sync_block_behind_threshold" in the config
        full_node_1, full_node_2, server_1, server_2 = two_nodes

        for block in default_1000_blocks:
            await full_node_1.full_node.respond_sub_block(full_node_protocol.RespondSubBlock(block))

        for block in default_400_blocks:
            await full_node_2.full_node.respond_sub_block(full_node_protocol.RespondSubBlock(block))

        # for h in sorted(full_node_1.full_node.blockchain.sub_epoch_summaries.keys()):
        #     print(f"\n ses 1  {h} {full_node_1.full_node.blockchain.sub_epoch_summaries[h]}")
        #
        # for h in full_node_2.full_node.blockchain.sub_epoch_summaries:
        #     print(f"\n ses 2  {h} {full_node_2.full_node.blockchain.sub_epoch_summaries[h]}")

        await server_2.start_client(PeerInfo("localhost", uint16(server_1._port)), None)

        # The second node should eventually catch up to the first one, and have the
        # same tip at height num_blocks - 1 (or at least num_blocks - 3, in case we sync to below the tip)
        await time_out_assert(180, node_height_at_least, True, full_node_2, len(default_1000_blocks) - 1)
