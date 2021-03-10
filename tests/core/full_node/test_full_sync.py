# flake8: noqa: F811, F401
import asyncio
import logging
import time
from typing import List

import pytest

from src.protocols import full_node_protocol
from src.types.full_block import FullBlock
from src.types.peer_info import PeerInfo
from src.util.hash import std_hash
from src.util.ints import uint16
from tests.core.fixtures import default_400_blocks, default_1000_blocks, default_10000_blocks, empty_blockchain
from tests.setup_nodes import bt, self_hostname, setup_n_nodes, setup_two_nodes, test_constants
from tests.time_out_assert import time_out_assert


def node_height_at_least(node, h):
    if node.full_node.blockchain.get_peak() is not None:
        return node.full_node.blockchain.get_peak().height >= h
    return False


def node_height_exactly(node, h):
    if node.full_node.blockchain.get_peak() is not None:
        return node.full_node.blockchain.get_peak().height == h
    return False


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.get_event_loop()
    yield loop


log = logging.getLogger(__name__)


class TestFullSync:
    @pytest.fixture(scope="function")
    async def two_nodes(self):
        async for _ in setup_two_nodes(test_constants):
            yield _

    @pytest.fixture(scope="function")
    async def three_nodes(self):
        async for _ in setup_n_nodes(test_constants, 3):
            yield _

    @pytest.fixture(scope="function")
    async def four_nodes(self):
        async for _ in setup_n_nodes(test_constants, 4):
            yield _

    @pytest.fixture(scope="function")
    async def five_nodes(self):
        async for _ in setup_n_nodes(test_constants, 5):
            yield _

    @pytest.mark.asyncio
    async def test_long_sync_from_zero(self, five_nodes, default_400_blocks):
        # Must be larger than "sync_block_behind_threshold" in the config
        num_blocks = len(default_400_blocks)
        blocks: List[FullBlock] = default_400_blocks
        full_node_1, full_node_2, full_node_3, full_node_4, full_node_5 = five_nodes
        server_1 = full_node_1.full_node.server
        server_2 = full_node_2.full_node.server
        server_3 = full_node_3.full_node.server
        server_4 = full_node_4.full_node.server
        server_5 = full_node_5.full_node.server

        # If this constant is changed, update the tests to use more blocks
        assert test_constants.WEIGHT_PROOF_RECENT_BLOCKS < 400

        # Syncs up less than recent blocks
        for block in blocks[: test_constants.WEIGHT_PROOF_RECENT_BLOCKS - 5]:
            await full_node_1.full_node.respond_block(full_node_protocol.RespondBlock(block))

        await server_2.start_client(
            PeerInfo(self_hostname, uint16(server_1._port)), on_connect=full_node_2.full_node.on_connect
        )

        # The second node should eventually catch up to the first one
        await time_out_assert(
            150, node_height_exactly, True, full_node_2, test_constants.WEIGHT_PROOF_RECENT_BLOCKS - 5 - 1
        )

        for block in blocks[
            test_constants.WEIGHT_PROOF_RECENT_BLOCKS - 5 : test_constants.WEIGHT_PROOF_RECENT_BLOCKS + 5
        ]:
            await full_node_1.full_node.respond_block(full_node_protocol.RespondBlock(block))

        await server_3.start_client(
            PeerInfo(self_hostname, uint16(server_1._port)), on_connect=full_node_3.full_node.on_connect
        )

        timeout_seconds = 150

        # Node 3 and Node 2 sync up to node 1
        await time_out_assert(
            timeout_seconds, node_height_exactly, True, full_node_2, test_constants.WEIGHT_PROOF_RECENT_BLOCKS + 5 - 1
        )
        await time_out_assert(
            timeout_seconds, node_height_exactly, True, full_node_3, test_constants.WEIGHT_PROOF_RECENT_BLOCKS + 5 - 1
        )

        cons = list(server_1.all_connections.values())[:]
        for con in cons:
            await con.close()
        for block in blocks[test_constants.WEIGHT_PROOF_RECENT_BLOCKS + 5 :]:
            await full_node_1.full_node.respond_block(full_node_protocol.RespondBlock(block))

        await server_2.start_client(
            PeerInfo(self_hostname, uint16(server_1._port)), on_connect=full_node_2.full_node.on_connect
        )
        await server_3.start_client(
            PeerInfo(self_hostname, uint16(server_1._port)), on_connect=full_node_3.full_node.on_connect
        )
        await server_4.start_client(
            PeerInfo(self_hostname, uint16(server_1._port)), on_connect=full_node_4.full_node.on_connect
        )
        await server_3.start_client(
            PeerInfo(self_hostname, uint16(server_2._port)), on_connect=full_node_3.full_node.on_connect
        )
        await server_4.start_client(
            PeerInfo(self_hostname, uint16(server_3._port)), on_connect=full_node_4.full_node.on_connect
        )
        await server_4.start_client(
            PeerInfo(self_hostname, uint16(server_2._port)), on_connect=full_node_4.full_node.on_connect
        )

        # All four nodes are synced
        await time_out_assert(timeout_seconds, node_height_exactly, True, full_node_1, num_blocks - 1)
        await time_out_assert(timeout_seconds, node_height_exactly, True, full_node_2, num_blocks - 1)
        await time_out_assert(timeout_seconds, node_height_exactly, True, full_node_3, num_blocks - 1)
        await time_out_assert(timeout_seconds, node_height_exactly, True, full_node_4, num_blocks - 1)

        # Deep reorg, fall back from batch sync to long sync
        blocks_node_5 = bt.get_consecutive_blocks(60, block_list_input=blocks[:350], seed=b"node5")
        for block in blocks_node_5:
            await full_node_5.full_node.respond_block(full_node_protocol.RespondBlock(block))
        await server_5.start_client(
            PeerInfo(self_hostname, uint16(server_1._port)), on_connect=full_node_5.full_node.on_connect
        )
        await time_out_assert(timeout_seconds, node_height_exactly, True, full_node_5, 409)
        await time_out_assert(timeout_seconds, node_height_exactly, True, full_node_1, 409)

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
            await full_node_1.full_node.respond_block(full_node_protocol.RespondBlock(block))

        # Node 2 syncs from halfway
        for i in range(int(len(default_1000_blocks) / 2)):
            await full_node_2.full_node.respond_block(full_node_protocol.RespondBlock(default_1000_blocks[i]))

        # Node 3 syncs from a different blockchain
        for block in blocks_400:
            await full_node_3.full_node.respond_block(full_node_protocol.RespondBlock(block))

        await server_2.start_client(PeerInfo(self_hostname, uint16(server_1._port)), full_node_2.full_node.on_connect)
        await server_3.start_client(PeerInfo(self_hostname, uint16(server_1._port)), full_node_3.full_node.on_connect)

        # Also test request proof of weight
        # Have the request header hash
        res = await full_node_1.request_proof_of_weight(
            full_node_protocol.RequestProofOfWeight(blocks_950[-1].height + 1, blocks_950[-1].header_hash)
        )
        assert res is not None
        validated, _ = await full_node_1.full_node.weight_proof_handler.validate_weight_proof(
            full_node_protocol.RespondProofOfWeight.from_bytes(res.data).wp
        )
        assert validated

        # Don't have the request header hash
        res = await full_node_1.request_proof_of_weight(
            full_node_protocol.RequestProofOfWeight(blocks_950[-1].height + 1, std_hash(b"12"))
        )
        assert res is None

        # The second node should eventually catch up to the first one, and have the
        # same tip at height num_blocks - 1
        await time_out_assert(180, node_height_exactly, True, full_node_2, num_blocks_initial - 1)
        await time_out_assert(180, node_height_exactly, True, full_node_3, num_blocks_initial - 1)

        def fn3_is_not_syncing():
            return not full_node_3.full_node.sync_store.get_sync_mode()

        await time_out_assert(180, fn3_is_not_syncing)
        cons = list(server_1.all_connections.values())[:]
        for con in cons:
            await con.close()
        for block in blocks_rest:
            await full_node_3.full_node.respond_block(full_node_protocol.RespondBlock(block))
            assert full_node_3.full_node.blockchain.get_peak().height >= block.height

        log.warning(f"FN3 height {full_node_3.full_node.blockchain.get_peak().height}")

        # TODO: fix this flaky test
        await time_out_assert(120, node_height_exactly, True, full_node_3, 999)

        await server_2.start_client(PeerInfo(self_hostname, uint16(server_1._port)), full_node_2.full_node.on_connect)
        await server_3.start_client(PeerInfo(self_hostname, uint16(server_1._port)), full_node_3.full_node.on_connect)
        await server_3.start_client(PeerInfo(self_hostname, uint16(server_2._port)), full_node_3.full_node.on_connect)
        await time_out_assert(180, node_height_exactly, True, full_node_1, 999)
        await time_out_assert(180, node_height_exactly, True, full_node_2, 999)

    @pytest.mark.asyncio
    async def test_batch_sync(self, two_nodes):
        # Must be below "sync_block_behind_threshold" in the config
        num_blocks = 20
        num_blocks_2 = 9
        blocks = bt.get_consecutive_blocks(num_blocks)
        blocks_2 = bt.get_consecutive_blocks(num_blocks_2, seed=b"123")
        full_node_1, full_node_2, server_1, server_2 = two_nodes

        # 12 blocks to node_1
        for block in blocks:
            await full_node_1.full_node.respond_block(full_node_protocol.RespondBlock(block))

        # 9 different blocks to node_2
        for block in blocks_2:
            await full_node_2.full_node.respond_block(full_node_protocol.RespondBlock(block))

        await server_2.start_client(
            PeerInfo(self_hostname, uint16(server_1._port)),
            on_connect=full_node_2.full_node.on_connect,
        )
        await time_out_assert(60, node_height_exactly, True, full_node_2, num_blocks - 1)

    @pytest.mark.asyncio
    async def test_backtrack_sync_1(self, two_nodes):
        blocks = bt.get_consecutive_blocks(1, skip_slots=1)
        blocks = bt.get_consecutive_blocks(1, blocks, skip_slots=0)
        blocks = bt.get_consecutive_blocks(1, blocks, skip_slots=0)
        full_node_1, full_node_2, server_1, server_2 = two_nodes

        # 3 blocks to node_1 in different sub slots
        for block in blocks:
            await full_node_1.full_node.respond_block(full_node_protocol.RespondBlock(block))

        await server_2.start_client(
            PeerInfo(self_hostname, uint16(server_1._port)),
            on_connect=full_node_2.full_node.on_connect,
        )
        await time_out_assert(60, node_height_exactly, True, full_node_2, 2)

    @pytest.mark.asyncio
    async def test_backtrack_sync_2(self, two_nodes):
        blocks = bt.get_consecutive_blocks(1, skip_slots=3)
        blocks = bt.get_consecutive_blocks(8, blocks, skip_slots=0)
        full_node_1, full_node_2, server_1, server_2 = two_nodes

        # 3 blocks to node_1 in different sub slots
        for block in blocks:
            await full_node_1.full_node.respond_block(full_node_protocol.RespondBlock(block))

        await server_2.start_client(
            PeerInfo(self_hostname, uint16(server_1._port)),
            on_connect=full_node_2.full_node.on_connect,
        )
        await time_out_assert(60, node_height_exactly, True, full_node_2, 8)

    @pytest.mark.asyncio
    async def test_close_height_but_big_reorg(self, three_nodes):
        blocks_a = bt.get_consecutive_blocks(50)
        blocks_b = bt.get_consecutive_blocks(51, seed=b"B")
        blocks_c = bt.get_consecutive_blocks(90, seed=b"C")
        full_node_1, full_node_2, full_node_3 = three_nodes
        server_1 = full_node_1.full_node.server
        server_2 = full_node_2.full_node.server
        server_3 = full_node_3.full_node.server

        for block in blocks_a:
            await full_node_1.full_node.respond_block(full_node_protocol.RespondBlock(block))
        for block in blocks_b:
            await full_node_2.full_node.respond_block(full_node_protocol.RespondBlock(block))
        for block in blocks_c:
            await full_node_3.full_node.respond_block(full_node_protocol.RespondBlock(block))

        await server_2.start_client(
            PeerInfo(self_hostname, uint16(server_1._port)),
            on_connect=full_node_2.full_node.on_connect,
        )
        await time_out_assert(60, node_height_exactly, True, full_node_1, 50)
        await time_out_assert(60, node_height_exactly, True, full_node_2, 50)
        await time_out_assert(60, node_height_exactly, True, full_node_3, 89)

        await server_3.start_client(
            PeerInfo(self_hostname, uint16(server_1._port)),
            on_connect=full_node_3.full_node.on_connect,
        )

        await server_3.start_client(
            PeerInfo(self_hostname, uint16(server_2._port)),
            on_connect=full_node_3.full_node.on_connect,
        )
        await time_out_assert(60, node_height_exactly, True, full_node_1, 89)
        await time_out_assert(60, node_height_exactly, True, full_node_2, 89)
        await time_out_assert(60, node_height_exactly, True, full_node_3, 89)
