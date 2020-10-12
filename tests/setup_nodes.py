import asyncio
import signal

from secrets import token_bytes
from typing import Dict, Tuple, List, Optional
from src.consensus.constants import ConsensusConstants
from src.full_node.full_node import FullNode
from src.server.connection import NodeType
from src.server.server import ChiaServer
from src.simulator.full_node_simulator import FullNodeSimulator
from src.timelord_launcher import spawn_process, kill_processes
from src.util.keychain import Keychain, bytes_to_mnemonic
from src.wallet.wallet_node import WalletNode
from src.util.config import load_config
from src.server.connection import PeerInfo
from src.util.ints import uint16, uint32
from src.server.start_farmer import service_kwargs_for_farmer
from src.server.start_harvester import service_kwargs_for_harvester
from src.server.start_introducer import service_kwargs_for_introducer
from src.server.start_timelord import service_kwargs_for_timelord
from src.server.start_service import Service
from src.util.make_test_constants import make_test_constants_with_genesis
from tests.time_out_assert import time_out_assert
from src.util.chech32 import encode_puzzle_hash

test_constants, bt = make_test_constants_with_genesis(
    {
        "DIFFICULTY_STARTING": 1,
        "DISCRIMINANT_SIZE_BITS": 8,
        "BLOCK_TIME_TARGET": 10,
        "DIFFICULTY_EPOCH": 12,  # The number of blocks per epoch
        "DIFFICULTY_DELAY": 3,  # EPOCH / WARP_FACTOR
        "PROPAGATION_THRESHOLD": 10,
        "PROPAGATION_DELAY_THRESHOLD": 20,
        "TX_PER_SEC": 1,
        "MEMPOOL_BLOCK_BUFFER": 10,
        "MIN_ITERS_STARTING": 50 * 1,
        "NUMBER_ZERO_BITS_CHALLENGE_SIG": 1,
        "CLVM_COST_RATIO_CONSTANT": 108,
    }
)

global_config = load_config(bt.root_path, "config.yaml")
self_hostname = global_config["self_hostname"]


def constants_for_dic(dic):
    return test_constants.replace(**dic)


async def _teardown_nodes(node_aiters: List) -> None:
    awaitables = [node_iter.__anext__() for node_iter in node_aiters]
    for sublist_awaitable in asyncio.as_completed(awaitables):
        try:
            await sublist_awaitable
        except StopAsyncIteration:
            pass


async def setup_full_node(
    consensus_constants: ConsensusConstants,
    db_name,
    port,
    introducer_port=None,
    simulator=False,
    send_uncompact_interval=30,
):
    db_path = bt.root_path / f"{db_name}"
    if db_path.exists():
        db_path.unlink()

    config = load_config(bt.root_path, "config.yaml", "full_node")
    config["database_path"] = db_name
    config["send_uncompact_interval"] = send_uncompact_interval
    config["peer_connect_interval"] = 3
    config["introducer_peer"]["host"] = "::1"
    if introducer_port is not None:
        config["introducer_peer"]["port"] = introducer_port

    if not simulator:
        api: FullNode = FullNode(
            config=config,
            root_path=bt.root_path,
            consensus_constants=consensus_constants,
            name=f"full_node_{port}",
        )
    else:
        api = FullNodeSimulator(
            config=config,
            root_path=bt.root_path,
            consensus_constants=consensus_constants,
            name=f"full_node_sim_{port}",
            bt=bt,
        )

    service = Service(
        root_path=bt.root_path,
        api=api,
        node_type=NodeType.FULL_NODE,
        advertised_port=port,
        service_name="full_node",
        server_listen_ports=[port],
        auth_connect_peers=False,
        on_connect_callback=api._on_connect,
        parse_cli_args=False,
    )

    await service.start()

    yield service._api, service._api.server

    service.stop()
    await service.wait_closed()
    if db_path.exists():
        db_path.unlink()


async def setup_wallet_node(
    port,
    consensus_constants: ConsensusConstants,
    full_node_port=None,
    introducer_port=None,
    key_seed=None,
    starting_height=None,
):
    config = load_config(bt.root_path, "config.yaml", "wallet")
    if starting_height is not None:
        config["starting_height"] = starting_height
    config["initial_num_public_keys"] = 5

    entropy = token_bytes(32)
    keychain = Keychain(entropy.hex(), True)
    keychain.add_private_key(bytes_to_mnemonic(entropy), "")
    first_pk = keychain.get_first_public_key()
    assert first_pk is not None
    db_path_key_suffix = str(first_pk.get_fingerprint())
    db_name = f"test-wallet-db-{port}"
    db_path = bt.root_path / f"test-wallet-db-{port}-{db_path_key_suffix}"
    if db_path.exists():
        db_path.unlink()
    config["database_path"] = str(db_name)
    config["testing"] = True

    api = WalletNode(
        config,
        keychain,
        bt.root_path,
        consensus_constants=consensus_constants,
        name="wallet1",
    )
    config["introducer_peer"]["host"] = "::1"
    if introducer_port is not None:
        config["introducer_peer"]["port"] = introducer_port
        config["peer_connect_interval"] = 10

    connect_peers: List[PeerInfo] = []
    if full_node_port is not None:
        connect_peers = [PeerInfo(self_hostname, full_node_port)]

    service = Service(
        root_path=bt.root_path,
        api=api,
        node_type=NodeType.WALLET,
        advertised_port=port,
        service_name="wallet",
        server_listen_ports=[port],
        connect_peers=connect_peers,
        auth_connect_peers=False,
        on_connect_callback=api._on_connect,
        parse_cli_args=False,
    )

    await service.start(new_wallet=True)

    yield service._api, service._api.server

    service.stop()
    await service.wait_closed()
    if db_path.exists():
        db_path.unlink()
    keychain.delete_all_keys()


async def setup_harvester(port, farmer_port, consensus_constants: ConsensusConstants):
    kwargs = service_kwargs_for_harvester(
        bt.root_path, bt.config["harvester"], consensus_constants
    )
    kwargs.update(
        dict(
            server_listen_ports=[port],
            advertised_port=port,
            connect_peers=[PeerInfo(self_hostname, farmer_port)],
            parse_cli_args=False,
        )
    )

    service = Service(**kwargs)

    await service.start()

    yield service._api, service._api.server

    service.stop()
    await service.wait_closed()


async def setup_farmer(
    port,
    consensus_constants: ConsensusConstants,
    full_node_port: Optional[uint16] = None,
):
    config = bt.config["farmer"]
    config_pool = bt.config["pool"]

    config["xch_target_address"] = encode_puzzle_hash(bt.farmer_ph)
    config["pool_public_keys"] = [bytes(pk).hex() for pk in bt.pool_pubkeys]
    config["port"] = port
    config_pool["xch_target_address"] = encode_puzzle_hash(bt.pool_ph)

    if full_node_port:
        config["full_node_peer"]["host"] = self_hostname
        config["full_node_peer"]["port"] = full_node_port
    else:
        del config["full_node_peer"]

    kwargs = service_kwargs_for_farmer(
        bt.root_path, config, config_pool, bt.keychain, consensus_constants
    )
    kwargs.update(
        dict(
            parse_cli_args=False,
        )
    )

    service = Service(**kwargs)

    await service.start()

    yield service._api, service._api.server

    service.stop()
    await service.wait_closed()


async def setup_introducer(port):
    kwargs = service_kwargs_for_introducer(
        bt.root_path,
        bt.config["introducer"],
    )
    kwargs.update(
        dict(
            advertised_port=port,
            parse_cli_args=False,
        )
    )

    service = Service(**kwargs)

    await service.start()

    yield service._api, service._api.server

    service.stop()
    await service.wait_closed()


async def setup_vdf_clients(port):
    vdf_task = asyncio.create_task(spawn_process(self_hostname, port, 1))

    def stop():
        asyncio.create_task(kill_processes())

    asyncio.get_running_loop().add_signal_handler(signal.SIGTERM, stop)
    asyncio.get_running_loop().add_signal_handler(signal.SIGINT, stop)

    yield vdf_task

    await kill_processes()


async def setup_timelord(
    port, full_node_port, sanitizer, consensus_constants: ConsensusConstants
):
    config = bt.config["timelord"]
    config["port"] = port
    config["full_node_peer"]["port"] = full_node_port
    config["sanitizer_mode"] = sanitizer
    if sanitizer:
        config["vdf_server"]["port"] = 7999

    kwargs = service_kwargs_for_timelord(
        bt.root_path, config, consensus_constants.DISCRIMINANT_SIZE_BITS
    )
    kwargs.update(
        dict(
            parse_cli_args=False,
        )
    )

    service = Service(**kwargs)

    await service.start()

    yield service._api, service._api.server

    service.stop()
    await service.wait_closed()


async def setup_two_nodes(consensus_constants: ConsensusConstants):

    """
    Setup and teardown of two full nodes, with blockchains and separate DBs.
    """
    node_iters = [
        setup_full_node(
            consensus_constants, "blockchain_test.db", 21234, simulator=False
        ),
        setup_full_node(
            consensus_constants, "blockchain_test_2.db", 21235, simulator=False
        ),
    ]

    fn1, s1 = await node_iters[0].__anext__()
    fn2, s2 = await node_iters[1].__anext__()

    yield (fn1, fn2, s1, s2)

    await _teardown_nodes(node_iters)


async def setup_node_and_wallet(
    consensus_constants: ConsensusConstants, starting_height=None
):
    node_iters = [
        setup_full_node(
            consensus_constants, "blockchain_test.db", 21234, simulator=False
        ),
        setup_wallet_node(
            21235, consensus_constants, None, starting_height=starting_height
        ),
    ]

    full_node, s1 = await node_iters[0].__anext__()
    wallet, s2 = await node_iters[1].__anext__()

    yield (full_node, wallet, s1, s2)

    await _teardown_nodes(node_iters)


async def setup_simulators_and_wallets(
    simulator_count: int,
    wallet_count: int,
    dic: Dict,
    starting_height=None,
):
    simulators: List[Tuple[FullNode, ChiaServer]] = []
    wallets = []
    node_iters = []

    consensus_constants = constants_for_dic(dic)
    for index in range(0, simulator_count):
        port = 50000 + index
        db_name = f"blockchain_test_{port}.db"
        sim = setup_full_node(consensus_constants, db_name, port, simulator=True)
        simulators.append(await sim.__anext__())
        node_iters.append(sim)

    for index in range(0, wallet_count):
        seed = bytes(uint32(index))
        port = 55000 + index
        wlt = setup_wallet_node(
            port,
            consensus_constants,
            None,
            key_seed=seed,
            starting_height=starting_height,
        )
        wallets.append(await wlt.__anext__())
        node_iters.append(wlt)

    yield (simulators, wallets)

    await _teardown_nodes(node_iters)


async def setup_farmer_harvester(consensus_constants: ConsensusConstants):
    node_iters = [
        setup_harvester(21234, 21235, consensus_constants),
        setup_farmer(21235, consensus_constants),
    ]

    harvester, harvester_server = await node_iters[0].__anext__()
    farmer, farmer_server = await node_iters[1].__anext__()

    yield (harvester, farmer)

    await _teardown_nodes(node_iters)


async def setup_full_system(consensus_constants: ConsensusConstants):
    node_iters = [
        setup_introducer(21233),
        setup_harvester(21234, 21235, consensus_constants),
        setup_farmer(21235, consensus_constants, uint16(21237)),
        setup_vdf_clients(8000),
        setup_timelord(21236, 21237, False, consensus_constants),
        setup_full_node(
            consensus_constants, "blockchain_test.db", 21237, 21232, False, 10
        ),
        setup_full_node(
            consensus_constants, "blockchain_test_2.db", 21238, 21232, False, 10
        ),
        setup_vdf_clients(7999),
        setup_timelord(21239, 21238, True, consensus_constants),
    ]

    introducer, introducer_server = await node_iters[0].__anext__()
    harvester, harvester_server = await node_iters[1].__anext__()
    farmer, farmer_server = await node_iters[2].__anext__()

    async def num_connections():
        return len(harvester.global_connections.get_connections())

    await time_out_assert(10, num_connections, 1)

    vdf = await node_iters[3].__anext__()
    timelord, timelord_server = await node_iters[4].__anext__()
    node1, node1_server = await node_iters[5].__anext__()
    node2, node2_server = await node_iters[6].__anext__()
    vdf_sanitizer = await node_iters[7].__anext__()
    sanitizer, sanitizer_server = await node_iters[8].__anext__()

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
        node1_server,
    )

    await _teardown_nodes(node_iters)
