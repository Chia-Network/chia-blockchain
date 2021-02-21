import asyncio
import signal

from secrets import token_bytes
from typing import Dict, List, Optional
from src.consensus.constants import ConsensusConstants
from src.full_node.full_node_api import FullNodeAPI
from src.timelord.timelord_launcher import spawn_process, kill_processes
from src.util.block_tools import BlockTools, test_constants
from src.types.peer_info import PeerInfo
from src.util.hash import std_hash
from src.util.keychain import Keychain, bytes_to_mnemonic
from src.simulator.start_simulator import service_kwargs_for_full_node_simulator
from src.server.start_farmer import service_kwargs_for_farmer
from src.server.start_full_node import service_kwargs_for_full_node
from src.server.start_harvester import service_kwargs_for_harvester
from src.server.start_introducer import service_kwargs_for_introducer
from src.server.start_timelord import service_kwargs_for_timelord
from src.server.start_wallet import service_kwargs_for_wallet
from src.server.start_service import Service
from src.util.ints import uint16, uint32
from src.util.bech32m import encode_puzzle_hash

from tests.time_out_assert import time_out_assert_custom_interval


bt = BlockTools(constants=test_constants)

self_hostname = bt.config["self_hostname"]


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
    local_bt,
    introducer_port=None,
    simulator=False,
    send_uncompact_interval=30,
):
    db_path = bt.root_path / f"{db_name}"
    if db_path.exists():
        db_path.unlink()

    config = bt.config["full_node"]
    config["database_path"] = db_name
    config["send_uncompact_interval"] = send_uncompact_interval
    config["peer_connect_interval"] = 3
    if introducer_port is not None:
        config["introducer_peer"]["host"] = self_hostname
        config["introducer_peer"]["port"] = introducer_port
    else:
        config["introducer_peer"] = None
    config["port"] = port
    config["rpc_port"] = port + 1000

    if simulator:
        kwargs = service_kwargs_for_full_node_simulator(local_bt.root_path, config, local_bt)
    else:
        kwargs = service_kwargs_for_full_node(local_bt.root_path, config, consensus_constants)

    kwargs.update(
        parse_cli_args=False,
        connect_to_daemon=False,
    )

    service = Service(**kwargs)

    await service.start()

    yield service._api

    service.stop()
    await service.wait_closed()
    if db_path.exists():
        db_path.unlink()


async def setup_wallet_node(
    port,
    consensus_constants: ConsensusConstants,
    local_bt,
    full_node_port=None,
    introducer_port=None,
    key_seed=None,
    starting_height=None,
):
    config = bt.config["wallet"]
    config["port"] = port
    config["rpc_port"] = port + 1000
    if starting_height is not None:
        config["starting_height"] = starting_height
    config["initial_num_public_keys"] = 5

    entropy = token_bytes(32)
    keychain = Keychain(entropy.hex(), True)
    if key_seed is None:
        key_seed = entropy
    keychain.add_private_key(bytes_to_mnemonic(key_seed), "")
    first_pk = keychain.get_first_public_key()
    assert first_pk is not None
    db_path_key_suffix = str(first_pk.get_fingerprint())
    db_name = f"test-wallet-db-{port}-KEY.sqlite"
    db_path_replaced: str = db_name.replace("KEY", db_path_key_suffix)
    db_path = bt.root_path / db_path_replaced

    if db_path.exists():
        db_path.unlink()
    config["database_path"] = str(db_name)
    config["testing"] = True

    config["introducer_peer"]["host"] = self_hostname
    if introducer_port is not None:
        config["introducer_peer"]["port"] = introducer_port
        config["peer_connect_interval"] = 10
    else:
        config["introducer_peer"] = None

    if full_node_port is not None:
        config["full_node_peer"] = {}
        config["full_node_peer"]["host"] = self_hostname
        config["full_node_peer"]["port"] = full_node_port
    else:
        del config["full_node_peer"]

    kwargs = service_kwargs_for_wallet(local_bt.root_path, config, consensus_constants, keychain)
    kwargs.update(
        parse_cli_args=False,
        connect_to_daemon=False,
    )

    service = Service(**kwargs)

    await service.start(new_wallet=True)

    yield service._node, service._node.server

    service.stop()
    await service.wait_closed()
    if db_path.exists():
        db_path.unlink()
    keychain.delete_all_keys()


async def setup_harvester(port, farmer_port, consensus_constants: ConsensusConstants, b_tools):
    kwargs = service_kwargs_for_harvester(b_tools.root_path, b_tools.config["harvester"], consensus_constants)
    kwargs.update(
        server_listen_ports=[port],
        advertised_port=port,
        connect_peers=[PeerInfo(self_hostname, farmer_port)],
        parse_cli_args=False,
        connect_to_daemon=False,
    )

    service = Service(**kwargs)

    await service.start()

    yield service._node, service._node.server

    service.stop()
    await service.wait_closed()


async def setup_farmer(
    port,
    consensus_constants: ConsensusConstants,
    b_tools,
    full_node_port: Optional[uint16] = None,
):
    config = bt.config["farmer"]
    config_pool = bt.config["pool"]

    config["xch_target_address"] = encode_puzzle_hash(b_tools.farmer_ph)
    config["pool_public_keys"] = [bytes(pk).hex() for pk in b_tools.pool_pubkeys]
    config["port"] = port
    config_pool["xch_target_address"] = encode_puzzle_hash(b_tools.pool_ph)

    if full_node_port:
        config["full_node_peer"]["host"] = self_hostname
        config["full_node_peer"]["port"] = full_node_port
    else:
        del config["full_node_peer"]

    kwargs = service_kwargs_for_farmer(b_tools.root_path, config, config_pool, b_tools.keychain, consensus_constants)
    kwargs.update(
        parse_cli_args=False,
        connect_to_daemon=False,
    )

    service = Service(**kwargs)

    await service.start()

    yield service._api, service._node.server

    service.stop()
    await service.wait_closed()


async def setup_introducer(port):
    kwargs = service_kwargs_for_introducer(
        bt.root_path,
        bt.config["introducer"],
    )
    kwargs.update(
        advertised_port=port,
        parse_cli_args=False,
        connect_to_daemon=False,
    )

    service = Service(**kwargs)

    await service.start()

    yield service._api, service._node.server

    service.stop()
    await service.wait_closed()


async def setup_vdf_clients(port):
    vdf_task_1 = asyncio.create_task(spawn_process(self_hostname, port, 1))
    vdf_task_2 = asyncio.create_task(spawn_process(self_hostname, port, 2))
    vdf_task_3 = asyncio.create_task(spawn_process(self_hostname, port, 3))

    def stop():
        asyncio.create_task(kill_processes())

    asyncio.get_running_loop().add_signal_handler(signal.SIGTERM, stop)
    asyncio.get_running_loop().add_signal_handler(signal.SIGINT, stop)

    yield vdf_task_1, vdf_task_2, vdf_task_3

    await kill_processes()


async def setup_timelord(port, full_node_port, sanitizer, consensus_constants: ConsensusConstants, b_tools):
    config = b_tools.config["timelord"]
    config["port"] = port
    config["full_node_peer"]["port"] = full_node_port
    config["sanitizer_mode"] = sanitizer
    if sanitizer:
        config["vdf_server"]["port"] = 7999

    kwargs = service_kwargs_for_timelord(b_tools.root_path, config, consensus_constants)
    kwargs.update(
        parse_cli_args=False,
        connect_to_daemon=False,
    )

    service = Service(**kwargs)

    await service.start()

    yield service._api, service._node.server

    service.stop()
    await service.wait_closed()


async def setup_two_nodes(consensus_constants: ConsensusConstants):
    """
    Setup and teardown of two full nodes, with blockchains and separate DBs.
    """
    node_iters = [
        setup_full_node(
            consensus_constants, "blockchain_test.db", 21234, BlockTools(constants=test_constants), simulator=False
        ),
        setup_full_node(
            consensus_constants, "blockchain_test_2.db", 21235, BlockTools(constants=test_constants), simulator=False
        ),
    ]

    fn1 = await node_iters[0].__anext__()
    fn2 = await node_iters[1].__anext__()

    yield fn1, fn2, fn1.full_node.server, fn2.full_node.server

    await _teardown_nodes(node_iters)


async def setup_n_nodes(consensus_constants: ConsensusConstants, n: int):
    """
    Setup and teardown of two full nodes, with blockchains and separate DBs.
    """
    port_start = 21244
    node_iters = []
    for i in range(n):
        node_iters.append(
            setup_full_node(
                consensus_constants,
                f"blockchain_test_{i}.db",
                port_start + i,
                BlockTools(constants=test_constants),
                simulator=False,
            )
        )
    nodes = []
    for ni in node_iters:
        nodes.append(await ni.__anext__())

    yield nodes

    await _teardown_nodes(node_iters)


async def setup_node_and_wallet(consensus_constants: ConsensusConstants, starting_height=None, key_seed=None):
    btools = BlockTools(constants=test_constants)
    node_iters = [
        setup_full_node(consensus_constants, "blockchain_test.db", 21234, btools, simulator=False),
        setup_wallet_node(21235, consensus_constants, btools, None, starting_height=starting_height, key_seed=key_seed),
    ]

    full_node_api = await node_iters[0].__anext__()
    wallet, s2 = await node_iters[1].__anext__()

    yield full_node_api, wallet, full_node_api.full_node.server, s2

    await _teardown_nodes(node_iters)


async def setup_simulators_and_wallets(
    simulator_count: int, wallet_count: int, dic: Dict, starting_height=None, key_seed=None, starting_port=50000
):
    simulators: List[FullNodeAPI] = []
    wallets = []
    node_iters = []

    consensus_constants = constants_for_dic(dic)
    for index in range(0, simulator_count):
        port = starting_port + index
        db_name = f"blockchain_test_{port}.db"
        sim = setup_full_node(consensus_constants, db_name, port, BlockTools(consensus_constants), simulator=True)
        simulators.append(await sim.__anext__())
        node_iters.append(sim)

    for index in range(0, wallet_count):
        if key_seed is None:
            seed = std_hash(uint32(index))
        else:
            seed = key_seed
        port = starting_port + 5000 + index
        wlt = setup_wallet_node(
            port,
            consensus_constants,
            BlockTools(consensus_constants),
            None,
            key_seed=seed,
            starting_height=starting_height,
        )
        wallets.append(await wlt.__anext__())
        node_iters.append(wlt)

    yield simulators, wallets

    await _teardown_nodes(node_iters)


async def setup_farmer_harvester(consensus_constants: ConsensusConstants):
    node_iters = [
        setup_harvester(21234, 21235, consensus_constants, bt),
        setup_farmer(21235, consensus_constants, bt),
    ]

    harvester, harvester_server = await node_iters[0].__anext__()
    farmer, farmer_server = await node_iters[1].__anext__()

    yield harvester, farmer

    await _teardown_nodes(node_iters)


async def setup_full_system(consensus_constants: ConsensusConstants):
    b_tools = BlockTools(constants=test_constants)
    b_tools_1 = BlockTools(constants=test_constants)
    node_iters = [
        setup_introducer(21233),
        setup_harvester(21234, 21235, consensus_constants, b_tools),
        setup_farmer(21235, consensus_constants, b_tools, uint16(21237)),
        setup_vdf_clients(8000),
        setup_timelord(21236, 21237, False, consensus_constants, b_tools),
        setup_full_node(consensus_constants, "blockchain_test.db", 21237, b_tools, 21233, False, 10),
        setup_full_node(consensus_constants, "blockchain_test_2.db", 21238, b_tools_1, 21233, False, 10),
        # setup_vdf_clients(7999),
        # setup_timelord(21239, 21238, True, consensus_constants),
    ]

    introducer, introducer_server = await node_iters[0].__anext__()
    harvester, harvester_server = await node_iters[1].__anext__()
    farmer, farmer_server = await node_iters[2].__anext__()

    async def num_connections():
        count = len(harvester.server.all_connections.items())
        return count

    await time_out_assert_custom_interval(10, 3, num_connections, 1)

    vdf_clients = await node_iters[3].__anext__()
    timelord, timelord_server = await node_iters[4].__anext__()
    node_api_1 = await node_iters[5].__anext__()
    node_api_2 = await node_iters[6].__anext__()
    # vdf_sanitizer = await node_iters[7].__anext__()
    # sanitizer, sanitizer_server = await node_iters[8].__anext__()

    yield (
        node_api_1,
        node_api_2,
        harvester,
        farmer,
        introducer,
        timelord,
        vdf_clients,
        node_api_1.full_node.server,
    )

    await _teardown_nodes(node_iters)
