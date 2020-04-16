import asyncio

from typing import Any, Dict, Tuple, List
from pathlib import Path

import aiosqlite
import blspy
from secrets import token_bytes

from src.full_node.blockchain import Blockchain
from src.full_node.mempool_manager import MempoolManager
from src.full_node.store import FullNodeStore
from src.full_node.full_node import FullNode
from src.server.connection import NodeType
from src.server.server import ChiaServer
from src.simulator.full_node_simulator import FullNodeSimulator
from src.timelord_launcher import spawn_process, kill_processes
from src.wallet.wallet_node import WalletNode
from src.types.full_block import FullBlock
from src.full_node.coin_store import CoinStore
from tests.block_tools import BlockTools
from src.types.BLSSignature import BLSPublicKey
from src.util.config import load_config
from src.consensus.coinbase import create_puzzlehash_for_pk
from src.harvester import Harvester
from src.farmer import Farmer
from src.introducer import Introducer
from src.timelord import Timelord
from src.server.connection import PeerInfo
from src.util.ints import uint16, uint32


bt = BlockTools()

root_path = bt.root_path

test_constants: Dict[str, Any] = {
    "DIFFICULTY_STARTING": 1,
    "DISCRIMINANT_SIZE_BITS": 16,
    "BLOCK_TIME_TARGET": 10,
    "MIN_BLOCK_TIME": 2,
    "DIFFICULTY_EPOCH": 12,  # The number of blocks per epoch
    "DIFFICULTY_DELAY": 3,  # EPOCH / WARP_FACTOR
    "PROPAGATION_THRESHOLD": 10,
    "PROPAGATION_DELAY_THRESHOLD": 20,
    "TX_PER_SEC": 1,
    "MEMPOOL_BLOCK_BUFFER": 10,
    "MIN_ITERS_STARTING": 50 * 2,
}
test_constants["GENESIS_BLOCK"] = bytes(
    bt.create_genesis_block(test_constants, bytes([0] * 32), b"0")
)


async def setup_full_node_simulator(db_name, port, introducer_port=None, dic={}):
    # SETUP
    test_constants_copy = test_constants.copy()
    for k in dic.keys():
        test_constants_copy[k] = dic[k]

    db_path = Path(db_name)
    db_path = root_path / f"{db_name}"
    if db_path.exists():
        db_path.unlink()

    connection = await aiosqlite.connect(db_path)
    store_1 = await FullNodeStore.create(connection)
    await store_1._clear_database()
    unspent_store_1 = await CoinStore.create(connection)
    await unspent_store_1._clear_database()
    mempool_1 = MempoolManager(unspent_store_1, test_constants_copy)

    b_1: Blockchain = await Blockchain.create(
        unspent_store_1, store_1, test_constants_copy
    )
    await mempool_1.new_tips(await b_1.get_full_tips())

    await store_1.add_block(FullBlock.from_bytes(test_constants_copy["GENESIS_BLOCK"]))

    net_config = load_config(root_path, "config.yaml")
    ping_interval = net_config.get("ping_interval")
    network_id = net_config.get("network_id")

    config = load_config(root_path, "config.yaml", "full_node")
    config["database_path"] = str(db_path)

    if introducer_port is not None:
        config["introducer_peer"]["host"] = "127.0.0.1"
        config["introducer_peer"]["port"] = introducer_port
    full_node_1 = FullNodeSimulator(
        store_1,
        b_1,
        config,
        mempool_1,
        unspent_store_1,
        f"full_node_{port}",
        test_constants_copy,
    )
    assert ping_interval is not None
    assert network_id is not None
    server_1 = ChiaServer(
        port,
        full_node_1,
        NodeType.FULL_NODE,
        ping_interval,
        network_id,
        bt.root_path,
        config,
        "full-node-simulator-server",
    )
    _ = await server_1.start_server(full_node_1._on_connect)
    full_node_1._set_server(server_1)

    yield (full_node_1, server_1)

    # TEARDOWN
    full_node_1._shutdown()
    server_1.close_all()
    await server_1.await_closed()
    await connection.close()
    Path(db_name).unlink()


async def setup_full_node(db_name, port, introducer_port=None, dic={}):
    # SETUP
    test_constants_copy = test_constants.copy()
    for k in dic.keys():
        test_constants_copy[k] = dic[k]

    db_path = Path(db_name)
    connection = await aiosqlite.connect(db_path)
    store_1 = await FullNodeStore.create(connection)
    await store_1._clear_database()
    unspent_store_1 = await CoinStore.create(connection)
    await unspent_store_1._clear_database()
    mempool_1 = MempoolManager(unspent_store_1, test_constants_copy)

    b_1: Blockchain = await Blockchain.create(
        unspent_store_1, store_1, test_constants_copy
    )
    await mempool_1.new_tips(await b_1.get_full_tips())

    await store_1.add_block(FullBlock.from_bytes(test_constants_copy["GENESIS_BLOCK"]))

    net_config = load_config(root_path, "config.yaml")
    ping_interval = net_config.get("ping_interval")
    network_id = net_config.get("network_id")

    config = load_config(root_path, "config.yaml", "full_node")
    if introducer_port is not None:
        config["introducer_peer"]["host"] = "127.0.0.1"
        config["introducer_peer"]["port"] = introducer_port
    full_node_1 = FullNode(
        store_1,
        b_1,
        config,
        mempool_1,
        unspent_store_1,
        f"full_node_{port}",
        test_constants_copy,
    )
    assert ping_interval is not None
    assert network_id is not None
    server_1 = ChiaServer(
        port,
        full_node_1,
        NodeType.FULL_NODE,
        ping_interval,
        network_id,
        root_path,
        config,
    )
    _ = await server_1.start_server(full_node_1._on_connect)
    full_node_1._set_server(server_1)

    yield (full_node_1, server_1)

    # TEARDOWN
    full_node_1._shutdown()
    server_1.close_all()
    await connection.close()
    Path(db_name).unlink()


async def setup_wallet_node(port, introducer_port=None, key_seed=b"", dic={}):
    config = load_config(root_path, "config.yaml", "wallet")
    if "starting_height" in dic:
        config["starting_height"] = dic["starting_height"]
    key_config = {
        "wallet_sk": bytes(blspy.ExtendedPrivateKey.from_seed(key_seed)).hex(),
    }
    test_constants_copy = test_constants.copy()
    for k in dic.keys():
        test_constants_copy[k] = dic[k]
    db_path = root_path / f"test-wallet-db-{port}.db"
    if db_path.exists():
        db_path.unlink()
    config["database_path"] = str(db_path)

    net_config = load_config(root_path, "config.yaml")
    ping_interval = net_config.get("ping_interval")
    network_id = net_config.get("network_id")

    wallet = await WalletNode.create(
        config, key_config, override_constants=test_constants_copy, name="wallet1",
    )
    assert ping_interval is not None
    assert network_id is not None
    server = ChiaServer(
        port,
        wallet,
        NodeType.WALLET,
        ping_interval,
        network_id,
        root_path,
        config,
        "wallet-server",
    )
    wallet.set_server(server)

    yield (wallet, server)

    server.close_all()
    await wallet.wallet_state_manager.clear_all_stores()
    await wallet.wallet_state_manager.close_all_stores()
    wallet.wallet_state_manager.unlink_db()
    await server.await_closed()


async def setup_harvester(port, dic={}):
    config = load_config(root_path, "config.yaml", "harvester")

    harvester = Harvester(config, bt.plot_config)

    net_config = load_config(root_path, "config.yaml")
    ping_interval = net_config.get("ping_interval")
    network_id = net_config.get("network_id")
    assert ping_interval is not None
    assert network_id is not None
    server = ChiaServer(
        port,
        harvester,
        NodeType.HARVESTER,
        ping_interval,
        network_id,
        root_path,
        config,
        f"harvester_server_{port}",
    )

    yield (harvester, server)

    harvester._shutdown()
    server.close_all()
    await harvester._await_shutdown()
    await server.await_closed()


async def setup_farmer(port, dic={}):
    config = load_config(root_path, "config.yaml", "farmer")
    pool_sk = blspy.PrivateKey.from_bytes(
        bytes.fromhex(list(bt.plot_config["plots"].values())[0]["pool_sk"])
    )
    pool_target = create_puzzlehash_for_pk(
        BLSPublicKey(bytes(pool_sk.get_public_key()))
    )
    wallet_sk = bt.wallet_sk
    wallet_target = create_puzzlehash_for_pk(
        BLSPublicKey(bytes(wallet_sk.get_public_key()))
    )

    key_config = {
        "wallet_sk": bytes(wallet_sk).hex(),
        "wallet_target": wallet_target.hex(),
        "pool_sks": [bytes(pool_sk).hex()],
        "pool_target": pool_target.hex(),
    }
    test_constants_copy = test_constants.copy()
    for k in dic.keys():
        test_constants_copy[k] = dic[k]

    net_config = load_config(root_path, "config.yaml")
    ping_interval = net_config.get("ping_interval")
    network_id = net_config.get("network_id")

    farmer = Farmer(config, key_config, test_constants_copy)
    assert ping_interval is not None
    assert network_id is not None
    server = ChiaServer(
        port,
        farmer,
        NodeType.FARMER,
        ping_interval,
        network_id,
        root_path,
        config,
        f"farmer_server_{port}",
    )
    _ = await server.start_server(farmer._on_connect)

    yield (farmer, server)

    server.close_all()
    await server.await_closed()


async def setup_introducer(port, dic={}):
    net_config = load_config(root_path, "config.yaml")
    ping_interval = net_config.get("ping_interval")
    network_id = net_config.get("network_id")

    config = load_config(root_path, "config.yaml", "introducer")

    introducer = Introducer(config)
    assert ping_interval is not None
    assert network_id is not None
    server = ChiaServer(
        port,
        introducer,
        NodeType.INTRODUCER,
        ping_interval,
        network_id,
        bt.root_path,
        config,
    )
    _ = await server.start_server(None)

    yield (introducer, server)

    server.close_all()
    await server.await_closed()


async def setup_vdf_clients(port):
    vdf_task = asyncio.create_task(spawn_process("127.0.0.1", port, 1))

    yield vdf_task

    await kill_processes()


async def setup_timelord(port, dic={}):
    config = load_config(root_path, "config.yaml", "timelord")

    test_constants_copy = test_constants.copy()
    for k in dic.keys():
        test_constants_copy[k] = dic[k]
    timelord = Timelord(config, test_constants_copy)

    net_config = load_config(root_path, "config.yaml")
    ping_interval = net_config.get("ping_interval")
    network_id = net_config.get("network_id")
    assert ping_interval is not None
    assert network_id is not None
    server = ChiaServer(
        port,
        timelord,
        NodeType.TIMELORD,
        ping_interval,
        network_id,
        bt.root_path,
        config,
    )

    coro = asyncio.start_server(
        timelord._handle_client,
        config["vdf_server"]["host"],
        config["vdf_server"]["port"],
        loop=asyncio.get_running_loop(),
    )

    vdf_server = asyncio.ensure_future(coro)

    timelord.set_server(server)
    timelord._start_bg_tasks()

    async def run_timelord():
        async for msg in timelord._manage_discriminant_queue():
            server.push_message(msg)

    timelord_task = asyncio.create_task(run_timelord())

    yield (timelord, server)

    vdf_server.cancel()
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


async def setup_node_and_wallet(dic={}):
    node_iters = [
        setup_full_node_simulator("blockchain_test.db", 21234, dic=dic),
        setup_wallet_node(21235, dic=dic),
    ]

    full_node, s1 = await node_iters[0].__anext__()
    wallet, s2 = await node_iters[1].__anext__()

    yield (full_node, wallet, s1, s2)

    for node_iter in node_iters:
        try:
            await node_iter.__anext__()
        except StopAsyncIteration:
            pass


async def setup_node_and_two_wallets(dic={}):
    node_iters = [
        setup_full_node("blockchain_test.db", 21234, dic=dic),
        setup_wallet_node(21235, key_seed=b'a', dic=dic),
        setup_wallet_node(21236, key_seed=b'b', dic=dic),
    ]

    full_node, s1 = await node_iters[0].__anext__()
    wallet, s2 = await node_iters[1].__anext__()
    wallet_2, s3 = await node_iters[2].__anext__()

    yield (full_node, wallet, wallet_2, s1, s2, s3)

    for node_iter in node_iters:
        try:
            await node_iter.__anext__()
        except StopAsyncIteration:
            pass


async def setup_simulators_and_wallets(
    simulator_count: int, wallet_count: int, dic: Dict
):
    simulators: List[Tuple[FullNode, ChiaServer]] = []
    wallets = []
    node_iters = []

    for index in range(0, simulator_count):
        db_name = f"blockchain_test{index}.db"
        port = 50000 + index
        sim = setup_full_node_simulator(db_name, port, dic=dic)
        simulators.append(await sim.__anext__())
        node_iters.append(sim)

    for index in range(0, wallet_count):
        seed = bytes(uint32(index))
        port = 55000 + index
        wlt = setup_wallet_node(port, key_seed=seed, dic=dic)
        wallets.append(await wlt.__anext__())
        node_iters.append(wlt)

    yield (simulators, wallets)

    for node_iter in node_iters:
        try:
            await node_iter.__anext__()
        except StopAsyncIteration:
            pass


async def setup_full_system(dic={}):
    node_iters = [
        setup_introducer(21233),
        setup_harvester(21234, dic),
        setup_farmer(21235, dic),
        setup_timelord(21236, dic),
        setup_vdf_clients(8000),
        setup_full_node("blockchain_test.db", 21237, 21233, dic),
        setup_full_node("blockchain_test_2.db", 21238, 21233, dic),
    ]

    introducer, introducer_server = await node_iters[0].__anext__()
    harvester, harvester_server = await node_iters[1].__anext__()
    farmer, farmer_server = await node_iters[2].__anext__()
    timelord, timelord_server = await node_iters[3].__anext__()
    vdf = await node_iters[4].__anext__()
    node1, node1_server = await node_iters[5].__anext__()
    node2, node2_server = await node_iters[6].__anext__()

    await harvester_server.start_client(
        PeerInfo("127.0.0.1", uint16(farmer_server._port)), auth=True
    )
    await farmer_server.start_client(PeerInfo("127.0.0.1", uint16(node1_server._port)))

    await timelord_server.start_client(
        PeerInfo("127.0.0.1", uint16(node1_server._port))
    )

    yield (node1, node2)

    for node_iter in node_iters:

        try:
            await node_iter.__anext__()
        except StopAsyncIteration:
            pass
