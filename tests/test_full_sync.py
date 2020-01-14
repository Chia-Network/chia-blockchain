import asyncio
import time
from typing import Any, Dict

import pytest

from src.blockchain import Blockchain, ReceiveBlockResult
from src.store import FullNodeStore
from src.full_node import FullNode
from src.server.connection import NodeType
from src.server.server import ChiaServer
from src.types.peer_info import PeerInfo
from src.util.ints import uint16
from tests.block_tools import BlockTools


bt = BlockTools()

test_constants: Dict[str, Any] = {
    "DIFFICULTY_STARTING": 1,
    "DISCRIMINANT_SIZE_BITS": 16,
    "BLOCK_TIME_TARGET": 10,
    "MIN_BLOCK_TIME": 2,
    "DIFFICULTY_FACTOR": 3,
    "DIFFICULTY_EPOCH": 12,  # The number of blocks per epoch
    "DIFFICULTY_WARP_FACTOR": 4,  # DELAY divides EPOCH in order to warp efficiently.
    "DIFFICULTY_DELAY": 3,  # EPOCH / WARP_FACTOR
}
test_constants["GENESIS_BLOCK"] = bytes(
    bt.create_genesis_block(test_constants, bytes([0] * 32), b"0")
)


@pytest.fixture(scope="module")
def event_loop():
    loop = asyncio.get_event_loop()
    yield loop


class TestFullSync:
    @pytest.mark.asyncio
    async def test_basic_sync(self):
        num_blocks = 100
        store_1 = await FullNodeStore.create("fndb_test")
        store_2 = await FullNodeStore.create("fndb_test_2")
        await store_1._clear_database()
        await store_2._clear_database()
        blocks = bt.get_consecutive_blocks(test_constants, num_blocks, [], 10)
        b_1: Blockchain = await Blockchain.create({}, test_constants)
        b_2: Blockchain = await Blockchain.create({}, test_constants)
        await store_1.add_block(blocks[0])
        await store_2.add_block(blocks[0])
        for i in range(1, num_blocks):
            assert (
                await b_1.receive_block(blocks[i])
            ) == ReceiveBlockResult.ADDED_TO_HEAD
            await store_1.add_block(blocks[i])

        full_node_1 = FullNode(store_1, b_1)
        server_1 = ChiaServer(21234, full_node_1, NodeType.FULL_NODE)
        _ = await server_1.start_server("127.0.0.1", full_node_1._on_connect)
        full_node_1._set_server(server_1)

        full_node_2 = FullNode(store_1, b_2)
        server_2 = ChiaServer(21235, full_node_2, NodeType.FULL_NODE)
        full_node_2._set_server(server_2)

        await server_2.start_client(PeerInfo("127.0.0.1", uint16(21234)), None)

        await asyncio.sleep(2)  # Allow connections to get made

        start_unf = time.time()

        while time.time() - start_unf < 300:
            # The second node should eventually catch up to the first one, and have the
            # same tip at height num_blocks - 1.
            if max([h.height for h in b_2.get_current_tips()]) == num_blocks - 1:
                print(f"Time taken to sync {num_blocks} is {time.time() - start_unf}")
                full_node_1._shutdown()
                full_node_2._shutdown()
                server_1.close_all()
                server_2.close_all()
                await server_1.await_closed()
                await server_2.await_closed()
                await store_1.close()
                await store_2.close()
                return
            await asyncio.sleep(0.1)

        full_node_1._shutdown()
        full_node_2._shutdown()
        server_1.close_all()
        server_2.close_all()
        await server_1.await_closed()
        await server_2.await_closed()
        await store_1.close()
        await store_2.close()
        raise Exception("Took too long to process blocks")
