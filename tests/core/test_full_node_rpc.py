import pytest

from src.consensus.pot_iterations import is_overflow_block
from src.rpc.full_node_rpc_api import FullNodeRpcApi
from src.rpc.rpc_server import start_rpc_server
from src.protocols import full_node_protocol
from src.rpc.full_node_rpc_client import FullNodeRpcClient
from src.types.unfinished_block import UnfinishedBlock
from src.util.ints import uint16
from tests.setup_nodes import setup_two_nodes, test_constants, bt, self_hostname
from tests.time_out_assert import time_out_assert


class TestRpc:
    @pytest.fixture(scope="function")
    async def two_nodes(self):
        async for _ in setup_two_nodes(test_constants):
            yield _

    @pytest.mark.asyncio
    async def test1(self, two_nodes):
        num_blocks = 5
        test_rpc_port = uint16(21522)
        full_node_api_1, full_node_api_2, server_1, server_2 = two_nodes

        def stop_node_cb():
            full_node_api_1._close()
            server_1.close_all()

        full_node_rpc_api = FullNodeRpcApi(full_node_api_1.full_node)

        config = bt.config
        hostname = config["self_hostname"]
        daemon_port = config["daemon_port"]

        rpc_cleanup = await start_rpc_server(
            full_node_rpc_api,
            hostname,
            daemon_port,
            test_rpc_port,
            stop_node_cb,
            bt.root_path,
            config,
            connect_to_daemon=False,
        )

        try:
            client = await FullNodeRpcClient.create(self_hostname, test_rpc_port, bt.root_path, config)
            state = await client.get_blockchain_state()
            assert state["peak"] is None
            assert not state["sync"]["sync_mode"]
            assert state["difficulty"] > 0
            assert state["sub_slot_iters"] > 0

            blocks = bt.get_consecutive_blocks(num_blocks)
            blocks = bt.get_consecutive_blocks(1, block_list_input=blocks, guarantee_transaction_block=True)

            assert len(await client.get_unfinished_block_headers()) == 0
            assert len((await client.get_block_records(0, 100))) == 0
            for block in blocks:
                if is_overflow_block(test_constants, block.reward_chain_block.signage_point_index):
                    finished_ss = block.finished_sub_slots[:-1]
                else:
                    finished_ss = block.finished_sub_slots

                unf = UnfinishedBlock(
                    finished_ss,
                    block.reward_chain_block.get_unfinished(),
                    block.challenge_chain_sp_proof,
                    block.reward_chain_sp_proof,
                    block.foliage,
                    block.foliage_transaction_block,
                    block.transactions_info,
                    block.transactions_generator,
                )
                await full_node_api_1.full_node.respond_unfinished_block(
                    full_node_protocol.RespondUnfinishedBlock(unf), None
                )
                await full_node_api_1.full_node.respond_block(full_node_protocol.RespondBlock(block), None)

            assert len(await client.get_unfinished_block_headers()) > 0
            assert len(await client.get_all_block(0, 2)) == 2
            state = await client.get_blockchain_state()

            block = await client.get_block(state["peak"].header_hash)
            assert block == blocks[-1]
            assert (await client.get_block(bytes([1] * 32))) is None

            assert (await client.get_block_record_by_height(2)).header_hash == blocks[2].header_hash

            assert len((await client.get_block_records(0, 100))) == num_blocks + 1

            assert (await client.get_block_record_by_height(100)) is None

            ph = list(blocks[-1].get_included_reward_coins())[0].puzzle_hash
            coins = await client.get_unspent_coins(ph)
            assert len(coins) >= 1

            additions, removals = await client.get_additions_and_removals(blocks[-1].header_hash)
            assert len(additions) >= 2 and len(removals) == 0

            assert len(await client.get_connections()) == 0

            await client.open_connection(self_hostname, server_2._port)

            async def num_connections():
                return len(await client.get_connections())

            await time_out_assert(10, num_connections, 1)
            connections = await client.get_connections()

            await client.close_connection(connections[0]["node_id"])
            await time_out_assert(10, num_connections, 0)
        finally:
            # Checks that the RPC manages to stop the node
            client.close()
            await client.await_closed()
            await rpc_cleanup()
