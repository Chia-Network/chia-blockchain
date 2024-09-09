from __future__ import annotations

import pytest

from chia._tests.core.node_height import node_height_at_least
from chia._tests.util.misc import BenchmarkRunner
from chia._tests.util.time_out_assert import time_out_assert
from chia.types.peer_info import PeerInfo


class TestNodeLoad:
    @pytest.mark.anyio
    async def test_blocks_load(self, two_nodes, self_hostname, benchmark_runner: BenchmarkRunner):
        num_blocks = 50
        full_node_1, full_node_2, server_1, server_2, bt = two_nodes
        blocks = bt.get_consecutive_blocks(num_blocks)
        await full_node_1.full_node.add_block(blocks[0])
        await time_out_assert(10, node_height_at_least, True, full_node_1, 0)
        await server_2.start_client(
            PeerInfo(self_hostname, server_1.get_port()), on_connect=full_node_2.full_node.on_connect
        )

        async def num_connections():
            return len(server_2.get_connections())

        await time_out_assert(10, num_connections, 1)
        await time_out_assert(10, node_height_at_least, True, full_node_2, 0)

        with benchmark_runner.assert_runtime(seconds=100) as runtime_results_future:
            for i in range(1, num_blocks):
                await full_node_1.full_node.add_block(blocks[i])
                await full_node_2.full_node.add_block(blocks[i])
        runtime_results = runtime_results_future.result(timeout=0)
        print(f"Time taken to process {num_blocks} is {runtime_results.duration}")
