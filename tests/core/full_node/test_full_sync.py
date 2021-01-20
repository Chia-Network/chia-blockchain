# flake8: noqa: F811, F401
import asyncio
import time

import pytest

from src.types.peer_info import PeerInfo
from src.protocols import full_node_protocol
from src.util.hash import std_hash
from src.util.ints import uint16
from tests.setup_nodes import setup_two_nodes, test_constants, bt, setup_n_nodes, self_hostname
from tests.time_out_assert import time_out_assert
from tests.core.fixtures import (
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

    @pytest.fixture(scope="function")
    async def three_nodes(self):
        async for _ in setup_n_nodes(test_constants, 3):
            yield _

    @pytest.mark.asyncio
    async def test_sync_from_zero(self, two_nodes, default_400_blocks):
        # Must be larger than "sync_block_behind_threshold" in the config
        num_blocks = len(default_400_blocks)
        blocks = default_400_blocks
        full_node_1, full_node_2, server_1, server_2 = two_nodes

        for block in blocks:
            await full_node_1.full_node.respond_sub_block(full_node_protocol.RespondSubBlock(block))

        await server_2.start_client(PeerInfo(self_hostname, uint16(server_1._port)), None)

        # The second node should eventually catch up to the first one, and have the
        # same tip at height num_blocks - 1 (or at least num_blocks - 3, in case we sync to below the tip)
        await time_out_assert(60, node_height_at_least, True, full_node_2, num_blocks - 1)

    @pytest.mark.asyncio
    async def test_sync_from_fork_point_and_weight_proof(self, three_nodes, default_1000_blocks, default_400_blocks):
        start = time.time()
        # Must be larger than "sync_block_behind_threshold" in the config
        num_blocks_initial = len(default_1000_blocks) - 50
        blocks_950 = default_1000_blocks[:num_blocks_initial]
        blocks_rest = default_1000_blocks[num_blocks_initial:]
        blocks_400 = default_400_blocks
        full_node_1, full_node_2, full_node_3 = three_nodes
        server_1 = full_node_1.full_node.server
        server_2 = full_node_2.full_node.server
        server_3 = full_node_3.full_node.server

        for block in blocks_950:
            await full_node_1.full_node.respond_sub_block(full_node_protocol.RespondSubBlock(block))

        # Node 2 syncs from halfway
        for i in range(int(len(default_1000_blocks) / 2)):
            await full_node_2.full_node.respond_sub_block(full_node_protocol.RespondSubBlock(default_1000_blocks[i]))

        # Node 3 syncs from a different blockchain
        for block in blocks_400:
            await full_node_3.full_node.respond_sub_block(full_node_protocol.RespondSubBlock(block))

        await server_2.start_client(PeerInfo(self_hostname, uint16(server_1._port)), None)
        await server_3.start_client(PeerInfo(self_hostname, uint16(server_1._port)), None)

        # Also test request proof of weight
        # Have the request header hash
        res = await full_node_1.request_proof_of_weight(
            full_node_protocol.RequestProofOfWeight(blocks_950[-1].sub_block_height + 1, blocks_950[-1].header_hash)
        )
        assert res is not None
        validated, _ = full_node_1.full_node.weight_proof_handler.validate_weight_proof(res.data.wp)
        assert validated

        # Don't have the request header hash
        res = await full_node_1.request_proof_of_weight(
            full_node_protocol.RequestProofOfWeight(blocks_950[-1].sub_block_height + 1, std_hash(b"12"))
        )
        assert res is None

        print("Here1: ", time.time() - start)
        # The second node should eventually catch up to the first one, and have the
        # same tip at height num_blocks - 1 (or at least num_blocks - 3, in case we sync to below the tip)
        await time_out_assert(180, node_height_at_least, True, full_node_2, num_blocks_initial - 1)
        print("Here2: ", time.time() - start)
        await time_out_assert(180, node_height_at_least, True, full_node_3, num_blocks_initial - 1)

        print("Here3: ", time.time() - start)
        for block in blocks_rest:
            await full_node_3.full_node.respond_sub_block(full_node_protocol.RespondSubBlock(block))

        print("Here4: ", time.time() - start)
        await time_out_assert(120, node_height_at_least, True, full_node_1, 999)
        print("Here5: ", time.time() - start)
        await time_out_assert(120, node_height_at_least, True, full_node_2, 999)
        print("Here6: ", time.time() - start)

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
            PeerInfo(self_hostname, uint16(server_1._port)),
            on_connect=full_node_2.full_node.on_connect,
        )
        await time_out_assert(60, node_height_at_least, True, full_node_2, num_blocks - 1)

    @pytest.mark.asyncio
    async def test_short_sync_2(self, two_nodes):
        blocks = bt.get_consecutive_blocks(1, skip_slots=1)
        blocks = bt.get_consecutive_blocks(1, blocks, skip_slots=0)
        blocks = bt.get_consecutive_blocks(1, blocks, skip_slots=0)
        full_node_1, full_node_2, server_1, server_2 = two_nodes

        # 3 blocks to node_1 in different sub slots
        for block in blocks:
            await full_node_1.full_node.respond_sub_block(full_node_protocol.RespondSubBlock(block))

        await server_2.start_client(
            PeerInfo(self_hostname, uint16(server_1._port)),
            on_connect=full_node_2.full_node.on_connect,
        )
        await time_out_assert(60, node_height_at_least, True, full_node_2, 2)

    @pytest.mark.asyncio
    async def test_short_sync_3(self, two_nodes):
        blocks = bt.get_consecutive_blocks(1, skip_slots=3)
        blocks = bt.get_consecutive_blocks(1, blocks, skip_slots=0)
        full_node_1, full_node_2, server_1, server_2 = two_nodes

        # 3 blocks to node_1 in different sub slots
        for block in blocks:
            await full_node_1.full_node.respond_sub_block(full_node_protocol.RespondSubBlock(block))

        await server_2.start_client(
            PeerInfo(self_hostname, uint16(server_1._port)),
            on_connect=full_node_2.full_node.on_connect,
        )
        await time_out_assert(60, node_height_at_least, True, full_node_2, 1)
