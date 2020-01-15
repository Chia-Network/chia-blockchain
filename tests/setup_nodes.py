from typing import Any, Dict

from src.blockchain import Blockchain
from src.store import FullNodeStore
from src.full_node import FullNode
from src.server.connection import NodeType
from src.server.server import ChiaServer
from src.types.full_block import FullBlock
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


async def setup_two_nodes():
    """
    Setup and teardown of two full nodes, with blockchains and separate DBs.
    """

    # SETUP
    store_1 = await FullNodeStore.create("fndb_test")
    store_2 = await FullNodeStore.create("fndb_test_2")
    await store_1._clear_database()
    await store_2._clear_database()
    b_1: Blockchain = await Blockchain.create({}, test_constants)
    b_2: Blockchain = await Blockchain.create({}, test_constants)
    await store_1.add_block(FullBlock.from_bytes(test_constants["GENESIS_BLOCK"]))
    await store_2.add_block(FullBlock.from_bytes(test_constants["GENESIS_BLOCK"]))

    full_node_1 = FullNode(store_1, b_1)
    server_1 = ChiaServer(21234, full_node_1, NodeType.FULL_NODE)
    _ = await server_1.start_server("127.0.0.1", full_node_1._on_connect)
    full_node_1._set_server(server_1)

    full_node_2 = FullNode(store_2, b_2)
    server_2 = ChiaServer(21235, full_node_2, NodeType.FULL_NODE)
    full_node_2._set_server(server_2)

    yield (full_node_1, full_node_2, server_1, server_2)

    # TEARDOWN
    full_node_1._shutdown()
    full_node_2._shutdown()
    server_1.close_all()
    server_2.close_all()
    await server_1.await_closed()
    await server_2.await_closed()
    await store_1.close()
    await store_2.close()
