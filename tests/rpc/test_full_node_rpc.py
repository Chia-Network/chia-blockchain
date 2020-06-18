import asyncio

import pytest

from src.rpc.full_node_rpc_api import FullNodeRpcApi
from src.rpc.rpc_server import start_rpc_server
from src.protocols import full_node_protocol
from src.rpc.full_node_rpc_client import FullNodeRpcClient
from src.util.ints import uint16
from tests.setup_nodes import setup_two_nodes, test_constants, bt
from tests.time_out_assert import time_out_assert


@pytest.fixture(scope="module")
def event_loop():
    loop = asyncio.get_event_loop()
    yield loop


class TestRpc:
    @pytest.fixture(scope="function")
    async def two_nodes(self):
        async for _ in setup_two_nodes():
            yield _

    @pytest.mark.asyncio
    async def test1(self, two_nodes):
        num_blocks = 5
        test_rpc_port = uint16(21522)
        full_node_1, full_node_2, server_1, server_2 = two_nodes
        blocks = bt.get_consecutive_blocks(test_constants, num_blocks, [], 10)

        for i in range(1, num_blocks):
            async for _ in full_node_1.respond_unfinished_block(
                full_node_protocol.RespondUnfinishedBlock(blocks[i])
            ):
                pass
            async for _ in full_node_1.respond_block(
                full_node_protocol.RespondBlock(blocks[i])
            ):
                pass

        def stop_node_cb():
            full_node_1._close()
            server_1.close_all()

        full_node_rpc_api = FullNodeRpcApi(full_node_1)

        rpc_cleanup = await start_rpc_server(
            full_node_rpc_api, test_rpc_port, stop_node_cb, connect_to_daemon=False
        )

        try:
            client = await FullNodeRpcClient.create(test_rpc_port)
            state = await client.get_blockchain_state()
            assert state["lca"].header_hash is not None
            assert not state["sync"]["sync_mode"]
            assert len(state["tips"]) > 0
            assert state["difficulty"] > 0
            assert state["ips"] > 0
            assert state["min_iters"] > 0

            block = await client.get_block(state["lca"].header_hash)
            assert block == blocks[2]
            assert (await client.get_block(bytes([1] * 32))) is None

            unf_block_headers = await client.get_unfinished_block_headers(4)
            assert len(unf_block_headers) == 1
            assert unf_block_headers[0] == blocks[4].header

            header = await client.get_header(state["lca"].header_hash)
            assert header == blocks[2].header

            assert (await client.get_header_by_height(2)) == blocks[2].header

            assert (await client.get_header_by_height(100)) is None

            coins = await client.get_unspent_coins(
                blocks[-1].header.data.coinbase.puzzle_hash, blocks[-1].header_hash
            )
            assert len(coins) == 6
            coins_lca = await client.get_unspent_coins(
                blocks[-1].header.data.coinbase.puzzle_hash
            )
            assert len(coins_lca) == 6

            assert len(await client.get_connections()) == 0

            await client.open_connection("localhost", server_2._port)

            async def num_connections():
                return len(await client.get_connections())

            await time_out_assert(10, num_connections, 1)
            connections = await client.get_connections()

            await client.close_connection(connections[0]["node_id"])
            await time_out_assert(10, num_connections, 0)
        except AssertionError:
            # Checks that the RPC manages to stop the node
            client.close()
            await client.await_closed()
            await rpc_cleanup()
            raise

        client.close()
        await client.await_closed()
        await rpc_cleanup()
