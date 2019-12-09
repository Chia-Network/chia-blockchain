import asyncio
from typing import Any, Dict
import pytest
from src.blockchain import Blockchain, ReceiveBlockResult
from src.database import FullNodeStore
from src.full_node import FullNode
from tests.block_tools import BlockTools
from src.server.connection import NodeType
from src.server.server import ChiaServer
from src.types.peer_info import PeerInfo
from src.protocols import peer_protocol
from src.server.outbound_message import OutboundMessage, Message, Delivery

bt = BlockTools()

test_constants: Dict[str, Any] = {
    "DIFFICULTY_STARTING": 5,
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


class TestNodeBandwitdh:
    @pytest.mark.asyncio
    async def test1(self):
        store = FullNodeStore("fndb_test")
        await store._clear_database()
        blocks = bt.get_consecutive_blocks(test_constants, 10, [], 10)
        b: Blockchain = Blockchain(store, test_constants)
        await b.initialize()
        for i in range(1, 9):
            assert (
                await b.receive_block(blocks[i])
            ) == ReceiveBlockResult.ADDED_TO_HEAD

        full_node_1 = FullNode(store, b)
        server_1 = ChiaServer(21234, full_node_1, NodeType.FULL_NODE)
        _ = await server_1.start_server("127.0.0.1", None)
        full_node_1._set_server(server_1)

        full_node_2 = FullNode(store, b)
        server_2 = ChiaServer(21235, full_node_2, NodeType.FULL_NODE)
        full_node_2._set_server(server_2)

        await server_2.start_client(
            PeerInfo("127.0.0.1", 21234), None
        )

        await asyncio.sleep(2)
        for i in range(1):
            print("Pushing", i)
            msg = Message("unfinished_block", peer_protocol.UnfinishedBlock(blocks[9]))
            server_1.push_message(OutboundMessage(NodeType.FULL_NODE, msg, Delivery.BROADCAST))
        # block_msg =
        # sever_1.push_message()
        print("Awaiting closed")
        await server_1.await_closed()
        await server_2.await_closed()
