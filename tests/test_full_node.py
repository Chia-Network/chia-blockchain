import asyncio

import pytest

from src.protocols import full_node_protocol
from src.types.peer_info import PeerInfo
from src.util.ints import uint16
from tests.setup_nodes import setup_two_nodes, test_constants, bt


@pytest.fixture(scope="module")
def event_loop():
    loop = asyncio.get_event_loop()
    yield loop


@pytest.fixture
async def two_nodes():
    async for _ in setup_two_nodes():
        yield _


@pytest.mark.usefixtures("two_nodes")
class TestFullNode:
    @pytest.mark.asyncio
    async def test_new_tip(self, two_nodes):
        num_blocks = 3
        full_node_1, full_node_2, server_1, server_2 = two_nodes
        blocks = bt.get_consecutive_blocks(test_constants, num_blocks, [], 10)

        for i in range(1, num_blocks - 1):
            async for _ in full_node_1.respond_block(
                full_node_protocol.RespondBlock(blocks[i])
            ):
                pass

        await server_2.start_client(
            PeerInfo(server_1._host, uint16(server_1._port)), None
        )
        await asyncio.sleep(2)  # Allow connections to get made

        # msgs = []
        msgs = [
            x
            async for x in full_node_1.new_tip(
                full_node_protocol.NewTip(
                    blocks[-1].height, blocks[-1].weight, blocks[-1].header_hash
                )
            )
        ]
        print("Msgs", msgs)

    @pytest.mark.asyncio
    async def test_new_tip_2(self, two_nodes):
        print("Running second test.")
