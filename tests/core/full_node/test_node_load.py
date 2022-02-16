import asyncio
import time

import pytest

from chia.protocols import full_node_protocol
from chia.types.peer_info import PeerInfo
from chia.util.ints import uint16
from tests.connection_utils import connect_and_get_peer
from tests.setup_nodes import bt, self_hostname, setup_two_nodes, test_constants
from tests.time_out_assert import time_out_assert


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.get_event_loop()
    yield loop


class TestNodeLoad:
    @pytest.fixture(scope="function")
    async def two_nodes(self, db_version):
        async for _ in setup_two_nodes(test_constants, db_version=db_version):
            yield _

    @pytest.mark.asyncio
    async def test_blocks_load(self, two_nodes):
        num_blocks = 50
        full_node_1, full_node_2, server_1, server_2 = two_nodes
        blocks = bt.get_consecutive_blocks(num_blocks)
        peer = await connect_and_get_peer(server_1, server_2)
        await full_node_1.full_node.respond_block(full_node_protocol.RespondBlock(blocks[0]), peer)

        await server_2.start_client(PeerInfo(self_hostname, uint16(server_1._port)), None)

        async def num_connections():
            return len(server_2.get_connections())

        await time_out_assert(10, num_connections, 1)

        start_unf = time.time()
        for i in range(1, num_blocks):
            await full_node_1.full_node.respond_block(full_node_protocol.RespondBlock(blocks[i]))
            await full_node_2.full_node.respond_block(full_node_protocol.RespondBlock(blocks[i]))
        print(f"Time taken to process {num_blocks} is {time.time() - start_unf}")
        assert time.time() - start_unf < 100
