import asyncio
import atexit
import signal

from secrets import token_bytes
from typing import Dict, List, Optional

from chia.consensus.constants import ConsensusConstants
from chia.daemon.server import WebSocketServer, create_server_for_daemon, daemon_launch_lock_path, singleton
from chia.full_node.full_node_api import FullNodeAPI
from chia.server.start_farmer import service_kwargs_for_farmer
from chia.server.start_full_node import service_kwargs_for_full_node
from chia.server.start_harvester import service_kwargs_for_harvester
from chia.server.start_introducer import service_kwargs_for_introducer
from chia.server.start_service import Service
from chia.server.start_timelord import service_kwargs_for_timelord
from chia.server.start_wallet import service_kwargs_for_wallet
from chia.simulator.start_simulator import service_kwargs_for_full_node_simulator
from chia.timelord.timelord_launcher import kill_processes, spawn_process
from chia.types.peer_info import PeerInfo
from chia.util.bech32m import encode_puzzle_hash
from tests.block_tools import create_block_tools, create_block_tools_async, test_constants
from tests.util.keyring import TempKeyring
from chia.util.hash import std_hash
from chia.util.ints import uint16, uint32
from chia.util.keychain import bytes_to_mnemonic
from tests.time_out_assert import time_out_assert_custom_interval


def cleanup_keyring(keyring: TempKeyring):
    keyring.cleanup()


temp_keyring = TempKeyring()
keychain = temp_keyring.get_keychain()
atexit.register(cleanup_keyring, temp_keyring)  # Attempt to cleanup the temp keychain
bt = create_block_tools(constants=test_constants, keychain=keychain)

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


async def setup_daemon(btools):
    root_path = btools.root_path
    config = btools.config
    lockfile = singleton(daemon_launch_lock_path(root_path))
    crt_path = root_path / config["daemon_ssl"]["private_crt"]
    key_path = root_path / config["daemon_ssl"]["private_key"]
    ca_crt_path = root_path / config["private_ssl_ca"]["crt"]
    ca_key_path = root_path / config["private_ssl_ca"]["key"]
    assert lockfile is not None
    create_server_for_daemon(btools.root_path)
    ws_server = WebSocketServer(root_path, ca_crt_path, ca_key_path, crt_path, key_path)
    await ws_server.start()

    yield ws_server

    await ws_server.stop()


async def setup_full_node(
    consensus_constants: ConsensusConstants,
    db_name,
    port,
    local_bt,
    introducer_port=None,
    simulator=False,
    send_uncompact_interval=0,
    sanitize_weight_proof_only=False,
    connect_to_daemon=False,
):
    db_path = local_bt.root_path / f"{db_name}"
    if db_path.exists():
        db_path.unlink()
    config = local_bt.config["full_node"]
    config["database_path"] = db_name
    config["send_uncompact_interval"] = send_uncompact_interval
    config["target_uncompact_proofs"] = 30
    config["peer_connect_interval"] = 50
    config["sanitize_weight_proof_only"] = sanitize_weight_proof_only
    if introducer_port is not None:
        config["introducer_peer"]["host"] = self_hostname
        config["introducer_peer"]["port"] = introducer_port
    else:
        config["introducer_peer"] = None
    config["dns_servers"] = []
    config["port"] = port
    config["rpc_port"] = port + 1000
    overrides = config["network_overrides"]["constants"][config["selected_network"]]
    updated_constants = consensus_constants.replace_str_to_bytes(**overrides)
    if simulator:
        kwargs = service_kwargs_for_full_node_simulator(local_bt.root_path, config, local_bt)
    else:
        kwargs = service_kwargs_for_full_node(local_bt.root_path, config, updated_constants)

    kwargs.update(
        parse_cli_args=False,
        connect_to_daemon=connect_to_daemon,
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
    with TempKeyring() as keychain:
        config = bt.config["wallet"]
        config["port"] = port
        config["rpc_port"] = port + 1000
        if starting_height is not None:
            config["starting_height"] = starting_height
        config["initial_num_public_keys"] = 5

        entropy = token_bytes(32)
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

    config["xch_target_address"] = encode_puzzle_hash(b_tools.farmer_ph, "xch")
    config["pool_public_keys"] = [bytes(pk).hex() for pk in b_tools.pool_pubkeys]
    config["port"] = port
    config_pool["xch_target_address"] = encode_puzzle_hash(b_tools.pool_ph, "xch")

    if full_node_port:
        config["full_node_peer"]["host"] = self_hostname
        config["full_node_peer"]["port"] = full_node_port
    else:
        del config["full_node_peer"]

    kwargs = service_kwargs_for_farmer(
        b_tools.root_path, config, config_pool, consensus_constants, b_tools.local_keychain
    )
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


async def setup_vdf_client(port):
    vdf_task_1 = asyncio.create_task(spawn_process(self_hostname, port, 1))

    def stop():
        asyncio.create_task(kill_processes())

    asyncio.get_running_loop().add_signal_handler(signal.SIGTERM, stop)
    asyncio.get_running_loop().add_signal_handler(signal.SIGINT, stop)

    yield vdf_task_1
    await kill_processes()


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
    config["fast_algorithm"] = False
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

    with TempKeyring() as keychain1, TempKeyring() as keychain2:
        node_iters = [
            setup_full_node(
                consensus_constants,
                "blockchain_test.db",
                21234,
                await create_block_tools_async(constants=test_constants, keychain=keychain1),
                simulator=False,
            ),
            setup_full_node(
                consensus_constants,
                "blockchain_test_2.db",
                21235,
                await create_block_tools_async(constants=test_constants, keychain=keychain2),
                simulator=False,
            ),
        ]

        fn1 = await node_iters[0].__anext__()
        fn2 = await node_iters[1].__anext__()

        yield fn1, fn2, fn1.full_node.server, fn2.full_node.server

        await _teardown_nodes(node_iters)


async def setup_n_nodes(consensus_constants: ConsensusConstants, n: int):
    """
    Setup and teardown of n full nodes, with blockchains and separate DBs.
    """
    port_start = 21244
    node_iters = []
    keyrings_to_cleanup = []
    for i in range(n):
        keyring = TempKeyring()
        keyrings_to_cleanup.append(keyring)
        node_iters.append(
            setup_full_node(
                consensus_constants,
                f"blockchain_test_{i}.db",
                port_start + i,
                await create_block_tools_async(constants=test_constants, keychain=keyring.get_keychain()),
                simulator=False,
            )
        )
    nodes = []
    for ni in node_iters:
        nodes.append(await ni.__anext__())

    yield nodes

    await _teardown_nodes(node_iters)

    for keyring in keyrings_to_cleanup:
        keyring.cleanup()


async def setup_node_and_wallet(consensus_constants: ConsensusConstants, starting_height=None, key_seed=None):
    with TempKeyring() as keychain:
        btools = await create_block_tools_async(constants=test_constants, keychain=keychain)
        node_iters = [
            setup_full_node(consensus_constants, "blockchain_test.db", 21234, btools, simulator=False),
            setup_wallet_node(
                21235, consensus_constants, btools, None, starting_height=starting_height, key_seed=key_seed
            ),
        ]

        full_node_api = await node_iters[0].__anext__()
        wallet, s2 = await node_iters[1].__anext__()

        yield full_node_api, wallet, full_node_api.full_node.server, s2

        await _teardown_nodes(node_iters)


async def setup_simulators_and_wallets(
    simulator_count: int,
    wallet_count: int,
    dic: Dict,
    starting_height=None,
    key_seed=None,
    starting_port=50000,
):
    with TempKeyring() as keychain1, TempKeyring() as keychain2:
        simulators: List[FullNodeAPI] = []
        wallets = []
        node_iters = []

        consensus_constants = constants_for_dic(dic)
        for index in range(0, simulator_count):
            port = starting_port + index
            db_name = f"blockchain_test_{port}.db"
            bt_tools = await create_block_tools_async(
                consensus_constants, const_dict=dic, keychain=keychain1
            )  # block tools modifies constants
            sim = setup_full_node(
                bt_tools.constants,
                db_name,
                port,
                bt_tools,
                simulator=True,
            )
            simulators.append(await sim.__anext__())
            node_iters.append(sim)

        for index in range(0, wallet_count):
            if key_seed is None:
                seed = std_hash(uint32(index))
            else:
                seed = key_seed
            port = starting_port + 5000 + index
            bt_tools = await create_block_tools_async(
                consensus_constants, const_dict=dic, keychain=keychain2
            )  # block tools modifies constants
            wlt = setup_wallet_node(
                port,
                bt_tools.constants,
                bt_tools,
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


async def setup_full_system(
    consensus_constants: ConsensusConstants, b_tools=None, b_tools_1=None, connect_to_daemon=False
):
    with TempKeyring() as keychain1, TempKeyring() as keychain2:
        if b_tools is None:
            b_tools = await create_block_tools_async(constants=test_constants, keychain=keychain1)
        if b_tools_1 is None:
            b_tools_1 = await create_block_tools_async(constants=test_constants, keychain=keychain2)
        node_iters = [
            setup_introducer(21233),
            setup_harvester(21234, 21235, consensus_constants, b_tools),
            setup_farmer(21235, consensus_constants, b_tools, uint16(21237)),
            setup_vdf_clients(8000),
            setup_timelord(21236, 21237, False, consensus_constants, b_tools),
            setup_full_node(
                consensus_constants, "blockchain_test.db", 21237, b_tools, 21233, False, 10, True, connect_to_daemon
            ),
            setup_full_node(
                consensus_constants, "blockchain_test_2.db", 21238, b_tools_1, 21233, False, 10, True, connect_to_daemon
            ),
            setup_vdf_client(7999),
            setup_timelord(21239, 21238, True, consensus_constants, b_tools_1),
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
        vdf_sanitizer = await node_iters[7].__anext__()
        sanitizer, sanitizer_server = await node_iters[8].__anext__()

        yield (
            node_api_1,
            node_api_2,
            harvester,
            farmer,
            introducer,
            timelord,
            vdf_clients,
            vdf_sanitizer,
            sanitizer,
            node_api_1.full_node.server,
        )

        await _teardown_nodes(node_iters)
