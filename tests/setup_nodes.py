import asyncio
import signal

from typing import Any, Dict, Tuple, List, Optional
from src.full_node.full_node import FullNode
from src.server.connection import NodeType
from src.server.server import ChiaServer, start_server
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
from src.server.start_service import create_periodic_introducer_poll_task
from src.util.ints import uint16, uint32
from src.server.start_service import Service
from src.rpc.harvester_rpc_api import HarvesterRpcApi
from tests.time_out_assert import time_out_assert


bt = BlockTools()

root_path = bt.root_path

test_constants: Dict[str, Any] = {
    "DIFFICULTY_STARTING": 1,
    "DISCRIMINANT_SIZE_BITS": 8,
    "BLOCK_TIME_TARGET": 10,
    "MIN_BLOCK_TIME": 2,
    "DIFFICULTY_EPOCH": 12,  # The number of blocks per epoch
    "DIFFICULTY_DELAY": 3,  # EPOCH / WARP_FACTOR
    "PROPAGATION_THRESHOLD": 10,
    "PROPAGATION_DELAY_THRESHOLD": 20,
    "TX_PER_SEC": 1,
    "MEMPOOL_BLOCK_BUFFER": 10,
    "MIN_ITERS_STARTING": 50 * 1,
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


async def setup_full_node(
    db_name,
    port,
    introducer_port=None,
    simulator=False,
    send_uncompact_interval=30,
    dic={},
):
    test_constants_copy = test_constants.copy()
    for k in dic.keys():
        test_constants_copy[k] = dic[k]

    db_path = root_path / f"{db_name}"
    if db_path.exists():
        db_path.unlink()

    config = load_config(bt.root_path, "config.yaml", "full_node")
    config["database_path"] = db_name
    config["send_uncompact_interval"] = send_uncompact_interval
    periodic_introducer_poll = None
    if introducer_port is not None:
        periodic_introducer_poll = (
            PeerInfo("127.0.0.1", introducer_port),
            30,
            config["target_peer_count"],
        )
    FullNodeApi = FullNodeSimulator if simulator else FullNode
    api = FullNodeApi(
        config=config,
        root_path=root_path,
        name=f"full_node_{port}",
        override_constants=test_constants_copy,
    )

    started = asyncio.Event()

    async def start_callback():
        await api._start()
        nonlocal started
        started.set()

    def stop_callback():
        api._close()

    async def await_closed_callback():
        await api._await_closed()

    service = Service(
        root_path=root_path,
        api=api,
        node_type=NodeType.FULL_NODE,
        advertised_port=port,
        service_name="full_node",
        server_listen_ports=[port],
        auth_connect_peers=False,
        on_connect_callback=api._on_connect,
        start_callback=start_callback,
        stop_callback=stop_callback,
        await_closed_callback=await_closed_callback,
        periodic_introducer_poll=periodic_introducer_poll,
    )

    run_task = asyncio.create_task(service.run())
    await started.wait()

    yield api, api.server

    service.stop()
    await run_task
    if db_path.exists():
        db_path.unlink()


async def setup_wallet_node(
    port,
    full_node_port=None,
    introducer_port=None,
    key_seed=b"setup_wallet_node",
    dic={},
):
    config = load_config(root_path, "config.yaml", "wallet")
    if "starting_height" in dic:
        config["starting_height"] = dic["starting_height"]
    config["initial_num_public_keys"] = 5

    keychain = Keychain(key_seed.hex(), True)
    keychain.add_private_key_seed(key_seed)
    test_constants_copy = test_constants.copy()
    for k in dic.keys():
        test_constants_copy[k] = dic[k]
    db_path_key_suffix = str(
        keychain.get_all_public_keys()[0].get_public_key().get_fingerprint()
    )
    db_name = f"test-wallet-db-{port}"
    db_path = root_path / f"test-wallet-db-{port}-{db_path_key_suffix}"
    if db_path.exists():
        db_path.unlink()
    config["database_path"] = str(db_name)

    api = WalletNode(
        config,
        keychain,
        root_path,
        override_constants=test_constants_copy,
        name="wallet1",
    )
    periodic_introducer_poll = None
    if introducer_port is not None:
        periodic_introducer_poll = (
            PeerInfo("127.0.0.1", introducer_port),
            30,
            config["target_peer_count"],
        )
    connect_peers: List[PeerInfo] = []
    if full_node_port is not None:
        connect_peers = [PeerInfo("127.0.0.1", full_node_port)]

    started = asyncio.Event()

    async def start_callback():
        await api._start()
        nonlocal started
        started.set()

    def stop_callback():
        api._close()

    async def await_closed_callback():
        await api._await_closed()

    service = Service(
        root_path=root_path,
        api=api,
        node_type=NodeType.WALLET,
        advertised_port=port,
        service_name="wallet",
        server_listen_ports=[port],
        connect_peers=connect_peers,
        auth_connect_peers=False,
        on_connect_callback=api._on_connect,
        start_callback=start_callback,
        stop_callback=stop_callback,
        await_closed_callback=await_closed_callback,
        periodic_introducer_poll=periodic_introducer_poll,
    )

    run_task = asyncio.create_task(service.run())
    await started.wait()

    yield api, api.server

    service.stop()
    await run_task
    if db_path.exists():
        db_path.unlink()
    keychain.delete_all_keys()


async def setup_harvester(port, farmer_port, dic={}):
    config = load_config(bt.root_path, "config.yaml", "harvester")

    api = Harvester(config, bt.plot_config, bt.root_path)

    started = asyncio.Event()

    async def start_callback():
        await api._start()
        nonlocal started
        started.set()

    def stop_callback():
        api._close()

    async def await_closed_callback():
        await api._await_closed()

    service = Service(
        root_path=root_path,
        api=api,
        node_type=NodeType.HARVESTER,
        advertised_port=port,
        service_name="harvester",
        server_listen_ports=[port],
        connect_peers=[PeerInfo("127.0.0.1", farmer_port)],
        auth_connect_peers=True,
        start_callback=start_callback,
        stop_callback=stop_callback,
        await_closed_callback=await_closed_callback,
    )

    run_task = asyncio.create_task(service.run())
    await started.wait()

    yield api, api.server

    service.stop()
    await run_task


async def setup_farmer(port, full_node_port: Optional[uint16] = None, dic={}):
    config = load_config(bt.root_path, "config.yaml", "farmer")
    config_pool = load_config(root_path, "config.yaml", "pool")
    test_constants_copy = test_constants.copy()
    for k in dic.keys():
        test_constants_copy[k] = dic[k]
    config["xch_target_puzzle_hash"] = bt.fee_target.hex()
    config["pool_public_keys"] = [
        bytes(epk.get_public_key()).hex() for epk in bt.keychain.get_all_public_keys()
    ]
    config_pool["xch_target_puzzle_hash"] = bt.fee_target.hex()
    if full_node_port:
        connect_peers = [PeerInfo("127.0.0.1", full_node_port)]
    else:
        connect_peers = []

    api = Farmer(config, config_pool, bt.keychain, test_constants_copy)

    started = asyncio.Event()

    async def start_callback():
        nonlocal started
        started.set()

    service = Service(
        root_path=root_path,
        api=api,
        node_type=NodeType.FARMER,
        advertised_port=port,
        service_name="farmer",
        server_listen_ports=[port],
        on_connect_callback=api._on_connect,
        connect_peers=connect_peers,
        auth_connect_peers=False,
        start_callback=start_callback,
    )

    run_task = asyncio.create_task(service.run())
    await started.wait()

    yield api, api.server

    service.stop()
    await run_task


async def setup_introducer(port, dic={}):
    config = load_config(bt.root_path, "config.yaml", "introducer")
    api = Introducer(config["max_peers_to_send"], config["recent_peer_threshold"])

    started = asyncio.Event()

    async def start_callback():
        await api._start()
        nonlocal started
        started.set()

    def stop_callback():
        api._close()

    async def await_closed_callback():
        await api._await_closed()

    service = Service(
        root_path=root_path,
        api=api,
        node_type=NodeType.INTRODUCER,
        advertised_port=port,
        service_name="introducer",
        server_listen_ports=[port],
        auth_connect_peers=False,
        start_callback=start_callback,
        stop_callback=stop_callback,
        await_closed_callback=await_closed_callback,
    )

    run_task = asyncio.create_task(service.run())
    await started.wait()

    yield api, api.server

    service.stop()
    await run_task


async def setup_vdf_clients(port):
    vdf_task = asyncio.create_task(spawn_process("127.0.0.1", port, 1))

    def stop():
        asyncio.create_task(kill_processes())

    asyncio.get_running_loop().add_signal_handler(signal.SIGTERM, stop)
    asyncio.get_running_loop().add_signal_handler(signal.SIGINT, stop)

    yield vdf_task

    await kill_processes()


async def setup_timelord(port, full_node_port, sanitizer, dic={}):
    config = load_config(bt.root_path, "config.yaml", "timelord")
    test_constants_copy = test_constants.copy()
    for k in dic.keys():
        test_constants_copy[k] = dic[k]
    config["sanitizer_mode"] = sanitizer
    if sanitizer:
        config["vdf_server"]["port"] = 7999

    api = Timelord(config, test_constants_copy)

    started = asyncio.Event()

    async def start_callback():
        await api._start()
        nonlocal started
        started.set()

    def stop_callback():
        api._close()

    async def await_closed_callback():
        await api._await_closed()

    service = Service(
        root_path=root_path,
        api=api,
        node_type=NodeType.TIMELORD,
        advertised_port=port,
        service_name="timelord",
        server_listen_ports=[port],
        connect_peers=[PeerInfo("127.0.0.1", full_node_port)],
        auth_connect_peers=False,
        start_callback=start_callback,
        stop_callback=stop_callback,
        await_closed_callback=await_closed_callback,
    )

    run_task = asyncio.create_task(service.run())
    await started.wait()

    yield api, api.server

    service.stop()
    await run_task


async def setup_two_nodes(dic={}):

    """
    Setup and teardown of two full nodes, with blockchains and separate DBs.
    """
    node_iters = [
        setup_full_node("blockchain_test.db", 21234, simulator=False, dic=dic),
        setup_full_node("blockchain_test_2.db", 21235, simulator=False, dic=dic),
    ]

    fn1, s1 = await node_iters[0].__anext__()
    fn2, s2 = await node_iters[1].__anext__()

    yield (fn1, fn2, s1, s2)

    await _teardown_nodes(node_iters)


async def setup_node_and_wallet(dic={}):
    node_iters = [
        setup_full_node("blockchain_test.db", 21234, simulator=False, dic=dic),
        setup_wallet_node(21235, None, dic=dic),
    ]

    full_node, s1 = await node_iters[0].__anext__()
    wallet, s2 = await node_iters[1].__anext__()

    yield (full_node, wallet, s1, s2)

    await _teardown_nodes(node_iters)


async def setup_simulators_and_wallets(
    simulator_count: int, wallet_count: int, dic: Dict
):
    simulators: List[Tuple[FullNode, ChiaServer]] = []
    wallets = []
    node_iters = []

    for index in range(0, simulator_count):
        port = 50000 + index
        db_name = f"blockchain_test_{port}.db"
        sim = setup_full_node(db_name, port, simulator=True, dic=dic)
        simulators.append(await sim.__anext__())
        node_iters.append(sim)

    for index in range(0, wallet_count):
        seed = bytes(uint32(index))
        port = 55000 + index
        wlt = setup_wallet_node(port, None, key_seed=seed, dic=dic)
        wallets.append(await wlt.__anext__())
        node_iters.append(wlt)

    yield (simulators, wallets)

    await _teardown_nodes(node_iters)


async def setup_farmer_harvester(dic={}):
    node_iters = [
        setup_harvester(21234, 21235, dic),
        setup_farmer(21235, None, dic),
    ]

    harvester, harvester_server = await node_iters[0].__anext__()
    farmer, farmer_server = await node_iters[1].__anext__()

    yield (harvester, farmer)

    await _teardown_nodes(node_iters)


async def setup_full_system(dic={}):
    node_iters = [
        setup_introducer(21233),
        setup_harvester(21234, 21235, dic),
        setup_farmer(21235, uint16(21237), dic),
        setup_timelord(21236, 21237, False, dic),
        setup_vdf_clients(8000),
        setup_full_node("blockchain_test.db", 21237, 21233, False, 10, dic),
        setup_full_node("blockchain_test_2.db", 21238, 21233, False, 10, dic),
        setup_timelord(21239, 21238, True, dic),
        setup_vdf_clients(7999),
    ]

    introducer, introducer_server = await node_iters[0].__anext__()
    harvester, harvester_server = await node_iters[1].__anext__()
    farmer, farmer_server = await node_iters[2].__anext__()

    async def num_connections():
        return len(harvester.global_connections.get_connections())

    await time_out_assert(10, num_connections, 1)

    timelord, timelord_server = await node_iters[3].__anext__()
    vdf = await node_iters[4].__anext__()
    node1, node1_server = await node_iters[5].__anext__()
    node2, node2_server = await node_iters[6].__anext__()
    sanitizer, sanitizer_server = await node_iters[7].__anext__()
    vdf_sanitizer = await node_iters[8].__anext__()

    yield (
        node1,
        node2,
        harvester,
        farmer,
        introducer,
        timelord,
        vdf,
        sanitizer,
        vdf_sanitizer,
    )

    await _teardown_nodes(node_iters)
