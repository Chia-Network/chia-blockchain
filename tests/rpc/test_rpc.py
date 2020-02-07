import asyncio
from typing import Any, Dict
from pathlib import Path

import pytest

from src.blockchain import Blockchain, ReceiveBlockResult
from src.mempool import Mempool
from src.store import FullNodeStore
from src.full_node import FullNode
from src.server.connection import NodeType
from src.server.server import ChiaServer
from src.unspent_store import UnspentStore
from tests.block_tools import BlockTools
from src.rpc.rpc_server import start_rpc_server
from src.rpc.rpc_client import RpcClient
from src.util.config import load_config


bt = BlockTools()

test_constants: Dict[str, Any] = {
    "DIFFICULTY_STARTING": 5,
    "DISCRIMINANT_SIZE_BITS": 32,
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


class TestRpc:
    @pytest.mark.asyncio
    async def test1(self):
        test_node_1_port = 21234
        test_node_2_port = 21235
        test_rpc_port = 21236
        db_filename = Path("blockchain_test.db")

        if db_filename.exists():
            db_filename.unlink()
        store = await FullNodeStore.create(db_filename)
        await store._clear_database()
        blocks = bt.get_consecutive_blocks(test_constants, 10, [], 10)
        unspent_store = await UnspentStore.create("blockchain_test.db")
        mempool = Mempool(unspent_store)

        b: Blockchain = await Blockchain.create(unspent_store, store, test_constants)
        await store.add_block(blocks[0])
        for i in range(1, 9):
            assert (await b.receive_block(blocks[i]))[
                0
            ] == ReceiveBlockResult.ADDED_TO_HEAD
            await store.add_block(blocks[i])

        config = load_config("config.yaml", "full_node")
        full_node_1 = FullNode(store, b, config, mempool, unspent_store)
        server_1 = ChiaServer(test_node_1_port, full_node_1, NodeType.FULL_NODE)
        _ = await server_1.start_server("127.0.0.1", None)
        full_node_1._set_server(server_1)

        def stop_node_cb():
            full_node_1._shutdown()
            server_1.close_all()

        rpc_cleanup = await start_rpc_server(full_node_1, stop_node_cb, test_rpc_port)

        try:
            client = await RpcClient.create(test_rpc_port)
            state = await client.get_blockchain_state()
            assert state["lca"].header_hash is not None
            assert not state["sync_mode"]
            assert len(state["tips"]) > 0
            assert state["difficulty"] > 0
            assert state["ips"] > 0

            block = await client.get_block(state["lca"].header_hash)
            assert block == blocks[6]
            assert (await client.get_block(bytes([1] * 32))) is None

            header = await client.get_header(state["lca"].header_hash)
            assert header == blocks[6].header

            # TODO implement get pool balances
            # assert len(await client.get_pool_balances()) > 0
            assert len(await client.get_connections()) == 0

            unspent_store2 = await UnspentStore.create("blockchain_test_2.db")
            full_node_2 = FullNode(store, b, config, mempool, unspent_store2)
            server_2 = ChiaServer(test_node_2_port, full_node_2, NodeType.FULL_NODE)
            full_node_2._set_server(server_2)

            _ = await server_2.start_server("127.0.0.1", None)
            await asyncio.sleep(2)  # Allow server to start
        except AssertionError:
            # Checks that the RPC manages to stop the node
            await client.stop_node()
            client.close()
            await client.await_closed()
            server_2.close_all()
            await server_1.await_closed()
            await server_2.await_closed()
            await rpc_cleanup()
            await store.close()
            Path("blockchain_test.db").unlink()
            Path("blockchain_test_2.db").unlink()
            raise

        await client.stop_node()
        client.close()
        await client.await_closed()
        server_2.close_all()
        await server_1.await_closed()
        await server_2.await_closed()
        await rpc_cleanup()
        await store.close()
        await unspent_store.close()
        await unspent_store2.close()
        Path("blockchain_test.db").unlink()
        Path("blockchain_test_2.db").unlink()
