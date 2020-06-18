import asyncio
import time

import pytest

from src.protocols import full_node_protocol
from src.server.connection import NodeType
from src.server.outbound_message import Delivery, Message, OutboundMessage
from src.types.peer_info import PeerInfo
from src.util.ints import uint16
from tests.setup_nodes import setup_two_nodes, test_constants
from tests.block_tools import BlockTools
from tests.time_out_assert import time_out_assert


def node_height_at_least(node, h):
    if (max([h.height for h in node.blockchain.get_current_tips()])) >= h:
        return True
    return False


@pytest.fixture(scope="module")
def event_loop():
    loop = asyncio.get_event_loop()
    yield loop


class TestNodeLoad:
    @pytest.fixture(scope="function")
    async def two_nodes(self):
        async for _ in setup_two_nodes():
            yield _

    @pytest.mark.asyncio
    async def test_unfinished_blocks_load(self, two_nodes):
        num_blocks = 2
        full_node_1, full_node_2, server_1, server_2 = two_nodes
        bt = BlockTools()
        blocks = bt.get_consecutive_blocks(test_constants, num_blocks, [], 10)

        for i in range(1, num_blocks - 1):
            async for _ in full_node_1.respond_block(
                full_node_protocol.RespondBlock(blocks[i])
            ):
                pass

        await server_2.start_client(PeerInfo("localhost", uint16(server_1._port)), None)

        async def num_connections():
            return len(server_2.global_connections.get_connections())

        await time_out_assert(10, num_connections, 1)

        num_unfinished_blocks = 250
        for i in range(num_unfinished_blocks):
            msg = Message(
                "respond_unfinished_block",
                full_node_protocol.RespondUnfinishedBlock(blocks[num_blocks - 1]),
            )
            server_1.push_message(
                OutboundMessage(NodeType.FULL_NODE, msg, Delivery.BROADCAST)
            )

        # Send the whole block ast the end so we can detect when the node is done
        block_msg = Message(
            "respond_block", full_node_protocol.RespondBlock(blocks[num_blocks - 1])
        )
        server_1.push_message(
            OutboundMessage(NodeType.FULL_NODE, block_msg, Delivery.BROADCAST)
        )

        await time_out_assert(
            60, node_height_at_least, True, full_node_2, num_blocks - 1
        )

    @pytest.mark.asyncio
    async def test_blocks_load(self, two_nodes):
        num_blocks = 50
        full_node_1, full_node_2, server_1, server_2 = two_nodes
        bt = BlockTools()
        blocks = bt.get_consecutive_blocks(test_constants, num_blocks, [], 10)

        await server_2.start_client(PeerInfo("localhost", uint16(server_1._port)), None)

        async def num_connections():
            return len(server_2.global_connections.get_connections())

        await time_out_assert(10, num_connections, 1)

        start_unf = time.time()
        for i in range(1, num_blocks):
            await time_out_assert(5, node_height_at_least, True, full_node_2, i - 2)
            msg = Message("respond_block", full_node_protocol.RespondBlock(blocks[i]))
            server_1.push_message(
                OutboundMessage(NodeType.FULL_NODE, msg, Delivery.BROADCAST)
            )
        print(f"Time taken to process {num_blocks} is {time.time() - start_unf}")
        assert time.time() - start_unf < 100
