import asyncio

from typing import Any, Dict, Tuple, List
from src.full_node.full_node import FullNode
from src.server.connection import NodeType
from src.server.server import ChiaServer
from src.simulator.full_node_simulator import FullNodeSimulator
from src.timelord_launcher import spawn_process, kill_processes
from src.util.keychain import Keychain
from src.wallet.wallet_node import WalletNode
from tests.block_tools import BlockTools
from src.util.config import load_config
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


async def _teardown_nodes(node_aiters: List) -> None:
    awaitables = [node_iter.__anext__() for node_iter in node_aiters]
    for sublist_awaitable in asyncio.as_completed(awaitables):
        try:
            await sublist_awaitable
        except StopAsyncIteration:
            pass


async def setup_full_node_simulator(db_name, port, introducer_port=None, dic={}):
    # SETUP
    test_constants_copy = test_constants.copy()
    for k in dic.keys():
        test_constants_copy[k] = dic[k]

    db_path = root_path / f"{db_name}"
    if db_path.exists():
        db_path.unlink()

    net_config = load_config(root_path, "config.yaml")
    ping_interval = net_config.get("ping_interval")
    network_id = net_config.get("network_id")

    config = load_config(root_path, "config.yaml", "full_node")
    config["database_path"] = str(db_path)

    if introducer_port is not None:
        config["introducer_peer"]["host"] = "127.0.0.1"
        config["introducer_peer"]["port"] = introducer_port
    full_node_1 = await FullNodeSimulator.create(
        config=config,
        name=f"full_node_{port}",
        root_path=root_path,
        override_constants=test_constants_copy,
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
    server_1.close_all()
    full_node_1._close()
    await server_1.await_closed()
    await full_node_1._await_closed()
    db_path.unlink()


async def setup_full_node(db_name, port, introducer_port=None, dic={}):
    # SETUP
    test_constants_copy = test_constants.copy()
    for k in dic.keys():
        test_constants_copy[k] = dic[k]

    db_path = root_path / f"{db_name}"
    if db_path.exists():
        db_path.unlink()

    net_config = load_config(root_path, "config.yaml")
    ping_interval = net_config.get("ping_interval")
    network_id = net_config.get("network_id")

    config = load_config(root_path, "config.yaml", "full_node")
    config["database_path"] = db_name
    if introducer_port is not None:
        config["introducer_peer"]["host"] = "127.0.0.1"
        config["introducer_peer"]["port"] = introducer_port

    full_node_1 = await FullNode.create(
        config=config,
        root_path=root_path,
        name=f"full_node_{port}",
        override_constants=test_constants_copy,
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
        f"full_node_server_{port}",
    )
    _ = await server_1.start_server(full_node_1._on_connect)
    full_node_1._set_server(server_1)

    yield (full_node_1, server_1)

    # TEARDOWN
    server_1.close_all()
    full_node_1._close()
    await server_1.await_closed()
    await full_node_1._await_closed()
    db_path = root_path / f"{db_name}"
    if db_path.exists():
        db_path.unlink()


async def setup_wallet_node(
    port, introducer_port=None, key_seed=b"setup_wallet_node", dic={}
):
    config = load_config(root_path, "config.yaml", "wallet")
    if "starting_height" in dic:
        config["starting_height"] = dic["starting_height"]

    keychain = Keychain(key_seed.hex(), True)
    keychain.add_private_key_seed(key_seed)
    private_key = keychain.get_all_private_keys()[0][0]
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
        config,
        private_key,
        root_path,
        override_constants=test_constants_copy,
        name="wallet1",
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
    config = load_config(bt.root_path, "config.yaml", "harvester")
    # print(bt.plot_config)
    harvester = await Harvester.create(config, bt.plot_config, bt.root_path)

    net_config = load_config(bt.root_path, "config.yaml")
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
        bt.root_path,
        config,
        f"harvester_server_{port}",
    )

    harvester.set_server(server)
    yield (harvester, server)

    server.close_all()
    harvester._shutdown()
    await server.await_closed()
    await harvester._await_shutdown()


async def setup_farmer(port, dic={}):
    print("root path", root_path)
    config = load_config(root_path, "config.yaml", "farmer")
    config_pool = load_config(root_path, "config.yaml", "pool")
    test_constants_copy = test_constants.copy()
    for k in dic.keys():
        test_constants_copy[k] = dic[k]

    net_config = load_config(root_path, "config.yaml")
    ping_interval = net_config.get("ping_interval")
    network_id = net_config.get("network_id")

    config["xch_target_puzzle_hash"] = bt.fee_target.hex()
    config["pool_public_keys"] = [
        bytes(epk.get_public_key()).hex() for epk in bt.keychain.get_all_public_keys()
    ]
    config_pool["xch_target_puzzle_hash"] = bt.fee_target.hex()

    farmer = Farmer(config, config_pool, bt.keychain, test_constants_copy)
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
    farmer.set_server(server)
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
        f"introducer_server_{port}",
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
        f"timelord_server_{port}",
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

    await _teardown_nodes(node_iters)


async def setup_node_and_wallet(dic={}):
    node_iters = [
        setup_full_node_simulator("blockchain_test.db", 21234, dic=dic),
        setup_wallet_node(21235, dic=dic),
    ]

    full_node, s1 = await node_iters[0].__anext__()
    wallet, s2 = await node_iters[1].__anext__()

    yield (full_node, wallet, s1, s2)

    await _teardown_nodes(node_iters)


async def setup_node_and_two_wallets(dic={}):
    node_iters = [
        setup_full_node("blockchain_test.db", 21234, dic=dic),
        setup_wallet_node(21235, key_seed=b"a", dic=dic),
        setup_wallet_node(21236, key_seed=b"b", dic=dic),
    ]

    full_node, s1 = await node_iters[0].__anext__()
    wallet, s2 = await node_iters[1].__anext__()
    wallet_2, s3 = await node_iters[2].__anext__()

    yield (full_node, wallet, wallet_2, s1, s2, s3)

    await _teardown_nodes(node_iters)


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

    await _teardown_nodes(node_iters)


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

    yield (node1, node2, harvester, farmer, introducer, timelord, vdf)

    await _teardown_nodes(node_iters)
