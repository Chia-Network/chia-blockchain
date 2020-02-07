from typing import Any, Dict
from pathlib import Path
import asyncio

from src.blockchain import Blockchain
from src.mempool_manager import MempoolManager
from src.store import FullNodeStore
from src.full_node import FullNode
from src.server.connection import NodeType
from src.server.server import ChiaServer
from src.types.full_block import FullBlock
from src.unspent_store import UnspentStore
from tests.block_tools import BlockTools
from src.types.hashable.BLSSignature import BLSPublicKey
from src.util.config import load_config
from src.pool import create_puzzlehash_for_pk
from src.harvester import Harvester
from src.farmer import Farmer
from src.introducer import Introducer
from src.timelord import Timelord
from src.server.connection import PeerInfo
from src.util.ints import uint16


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
    "PROPAGATION_THRESHOLD": 10,
    "PROPAGATION_DELAY_THRESHOLD": 20,
}
test_constants["GENESIS_BLOCK"] = bytes(
    bt.create_genesis_block(test_constants, bytes([0] * 32), b"0")
)


async def setup_full_node(db_name, port, introducer_port=None, dic={}):
    # SETUP
    test_constants_copy = test_constants.copy()
    for k in dic.keys():
        test_constants_copy[k] = dic[k]

    store_1 = await FullNodeStore.create(Path(db_name))
    await store_1._clear_database()
    unspent_store_1 = await UnspentStore.create(Path(db_name))
    await unspent_store_1._clear_database()
    mempool_1 = MempoolManager(unspent_store_1, dic)

    b_1: Blockchain = await Blockchain.create(
        unspent_store_1, store_1, test_constants_copy
    )
    await store_1.add_block(FullBlock.from_bytes(test_constants_copy["GENESIS_BLOCK"]))

    config = load_config("config.yaml", "full_node")
    if introducer_port is not None:
        config["introducer_peer"]["host"] = "127.0.0.1"
        config["introducer_peer"]["port"] = introducer_port
    full_node_1 = FullNode(
        store_1, b_1, config, mempool_1, unspent_store_1, f"full_node_{port}"
    )
    server_1 = ChiaServer(port, full_node_1, NodeType.FULL_NODE)
    _ = await server_1.start_server(config["host"], full_node_1._on_connect)
    full_node_1._set_server(server_1)

    yield (full_node_1, server_1)

    # TEARDOWN
    full_node_1._shutdown()
    server_1.close_all()
    await server_1.await_closed()
    await store_1.close()
    await unspent_store_1.close()
    Path(db_name).unlink()


async def setup_harvester(port, dic={}):
    config = load_config("config.yaml", "harvester")

    harvester = Harvester(config, bt.plot_config)
    server = ChiaServer(port, harvester, NodeType.HARVESTER)
    _ = await server.start_server(config["host"], None)

    yield (harvester, server)

    harvester._shutdown()
    server.close_all()
    await harvester._await_shutdown()
    await server.await_closed()


async def setup_farmer(port, dic={}):
    config = load_config("config.yaml", "farmer")
    pool_sk = bt.pool_sk
    pool_target = create_puzzlehash_for_pk(
        BLSPublicKey(bytes(pool_sk.get_public_key()))
    )
    farmer_sk = bt.farmer_sk
    farmer_target = create_puzzlehash_for_pk(
        BLSPublicKey(bytes(farmer_sk.get_public_key()))
    )

    key_config = {
        "farmer_sk": bytes(farmer_sk).hex(),
        "farmer_target": farmer_target.hex(),
        "pool_sks": [bytes(pool_sk).hex()],
        "pool_target": pool_target.hex(),
    }

    farmer = Farmer(config, key_config)
    server = ChiaServer(port, farmer, NodeType.FARMER)
    _ = await server.start_server(config["host"], farmer._on_connect)

    yield (farmer, server)

    server.close_all()
    await server.await_closed()


async def setup_introducer(port, dic={}):
    config = load_config("config.yaml", "introducer")

    introducer = Introducer(config)
    server = ChiaServer(port, introducer, NodeType.INTRODUCER)
    _ = await server.start_server(port, None)

    yield (introducer, server)

    server.close_all()
    await server.await_closed()


async def setup_timelord(port, dic={}):
    config = load_config("config.yaml", "timelord")

    timelord = Timelord(config)
    server = ChiaServer(port, timelord, NodeType.TIMELORD)
    _ = await server.start_server(port, None)

    async def run_timelord():
        async for msg in timelord._manage_discriminant_queue():
            server.push_message(msg)

    timelord_task = asyncio.create_task(run_timelord())

    yield (timelord, server)

    server.close_all()
    await timelord._shutdown()
    await timelord_task
    await server.await_closed()


async def setup_two_nodes(dic={}):
    """
    Setup and teardown of two full nodes, with blockchains and separate DBs.
    """
    node_iters = [
        setup_full_node("blockchain_test.db", 21234, dic=dic),
        setup_full_node("blockchain_test_2.db", 21235, dic=dic),
    ]

    fn1, s1 = await node_iters[0].__anext__()
    fn2, s2 = await node_iters[1].__anext__()

    yield (fn1, fn2, s1, s2)

    for node_iter in node_iters:
        try:
            await node_iter.__anext__()
        except StopAsyncIteration:
            pass


async def setup_full_system(dic={}):
    node_iters = [
        setup_introducer(21233),
        setup_harvester(21234),
        setup_farmer(21235),
        setup_timelord(21236),
        setup_full_node("blockchain_test.db", 21237, 21233, dic),
        setup_full_node("blockchain_test_2.db", 21238, 21233, dic),
    ]

    introducer, introducer_server = await node_iters[0].__anext__()
    harvester, harvester_server = await node_iters[1].__anext__()
    farmer, farmer_server = await node_iters[2].__anext__()
    timelord, timelord_server = await node_iters[3].__anext__()
    node1, node1_server = await node_iters[4].__anext__()
    node2, node2_server = await node_iters[5].__anext__()

    await harvester_server.start_client(
        PeerInfo(farmer_server._host, uint16(farmer_server._port)), None
    )
    await farmer_server.start_client(
        PeerInfo(node1_server._host, uint16(node1_server._port)), None
    )
    await timelord_server.start_client(
        PeerInfo(node1_server._host, uint16(node1_server._port)), None
    )

    yield (node1, node2)

    for node_iter in node_iters:

        try:
            await node_iter.__anext__()
        except StopAsyncIteration:
            pass
