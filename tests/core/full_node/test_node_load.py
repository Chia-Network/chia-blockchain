from __future__ import annotations

import pytest

from chia.simulator.time_out_assert import time_out_assert
from chia.types.peer_info import PeerInfo
from chia.util.ints import uint16
from tests.connection_utils import connect_and_get_peer
from tests.util.misc import assert_runtime


class TestNodeLoad:
    @pytest.mark.asyncio
    async def test_blocks_load(self, request: pytest.FixtureRequest, two_nodes, self_hostname):
        num_blocks = 50
        full_node_1, full_node_2, server_1, server_2, bt = two_nodes
        blocks = bt.get_consecutive_blocks(num_blocks)
        peer = await connect_and_get_peer(server_1, server_2, self_hostname)
        await full_node_1.full_node.add_block(blocks[0], peer)

        await server_2.start_client(PeerInfo(self_hostname, uint16(server_1._port)), None)

        async def num_connections():
            return len(server_2.get_connections())

        await time_out_assert(10, num_connections, 1)

        with assert_runtime(seconds=100, label=request.node.name) as runtime_results_future:
            for i in range(1, num_blocks):
                await full_node_1.full_node.add_block(blocks[i])
                await full_node_2.full_node.add_block(blocks[i])
        runtime_results = runtime_results_future.result(timeout=0)
        print(f"Time taken to process {num_blocks} is {runtime_results.duration}")
