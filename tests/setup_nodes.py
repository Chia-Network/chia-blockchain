import asyncio
import logging
from typing import AsyncIterator, Dict, List, Tuple, Optional
from pathlib import Path

from chia.consensus.constants import ConsensusConstants
from chia.full_node.full_node_api import FullNodeAPI
from chia.server.start_service import Service
from chia.util.hash import std_hash
from chia.util.ints import uint16, uint32
from tests.block_tools import BlockTools, create_block_tools_async, test_constants
from tests.setup_services import (
    setup_daemon,
    setup_farmer,
    setup_full_node,
    setup_harvester,
    setup_introducer,
    setup_timelord,
    setup_vdf_client,
    setup_vdf_clients,
    setup_wallet_node,
)
from tests.time_out_assert import time_out_assert_custom_interval
from tests.util.keyring import TempKeyring
from tests.util.socket import find_available_listen_port


def cleanup_keyring(keyring: TempKeyring):
    keyring.cleanup()


log = logging.getLogger(__name__)


def constants_for_dic(dic):
    return test_constants.replace(**dic)


async def _teardown_nodes(node_aiters: List) -> None:
    awaitables = [node_iter.__anext__() for node_iter in node_aiters]
    for sublist_awaitable in asyncio.as_completed(awaitables):
        try:
            await sublist_awaitable
        except StopAsyncIteration:
            pass


async def setup_two_nodes(consensus_constants: ConsensusConstants, db_version: int, self_hostname: str):
    """
    Setup and teardown of two full nodes, with blockchains and separate DBs.
    """

    with TempKeyring(populate=True) as keychain1, TempKeyring(populate=True) as keychain2:
        node_iters = [
            setup_full_node(
                consensus_constants,
                "blockchain_test.db",
                self_hostname,
                await create_block_tools_async(constants=test_constants, keychain=keychain1),
                simulator=False,
                db_version=db_version,
            ),
            setup_full_node(
                consensus_constants,
                "blockchain_test_2.db",
                self_hostname,
                await create_block_tools_async(constants=test_constants, keychain=keychain2),
                simulator=False,
                db_version=db_version,
            ),
        ]

        fn1 = await node_iters[0].__anext__()
        fn2 = await node_iters[1].__anext__()

        yield fn1, fn2, fn1.full_node.server, fn2.full_node.server

        await _teardown_nodes(node_iters)


async def setup_n_nodes(consensus_constants: ConsensusConstants, n: int, db_version: int, self_hostname: str):
    """
    Setup and teardown of n full nodes, with blockchains and separate DBs.
    """
    node_iters = []
    keyrings_to_cleanup = []
    for i in range(n):
        keyring = TempKeyring(populate=True)
        keyrings_to_cleanup.append(keyring)
        node_iters.append(
            setup_full_node(
                consensus_constants,
                f"blockchain_test_{i}.db",
                self_hostname,
                await create_block_tools_async(constants=test_constants, keychain=keyring.get_keychain()),
                simulator=False,
                db_version=db_version,
            )
        )
    nodes = []
    for ni in node_iters:
        nodes.append(await ni.__anext__())

    yield nodes

    await _teardown_nodes(node_iters)

    for keyring in keyrings_to_cleanup:
        keyring.cleanup()


async def setup_node_and_wallet(
    consensus_constants: ConsensusConstants, self_hostname: str, starting_height=None, key_seed=None, db_version=1
):
    with TempKeyring(populate=True) as keychain:
        btools = await create_block_tools_async(constants=test_constants, keychain=keychain)
        node_iters = [
            setup_full_node(
                consensus_constants,
                "blockchain_test.db",
                self_hostname,
                btools,
                simulator=False,
                db_version=db_version,
            ),
            setup_wallet_node(
                btools.config["self_hostname"],
                consensus_constants,
                btools,
                None,
                starting_height=starting_height,
                key_seed=key_seed,
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
    *,
    starting_height=None,
    key_seed=None,
    initial_num_public_keys=5,
    db_version=1,
    config_overrides: Optional[Dict] = None,
):
    with TempKeyring(populate=True) as keychain1, TempKeyring(populate=True) as keychain2:
        simulators: List[FullNodeAPI] = []
        wallets = []
        node_iters = []

        consensus_constants = constants_for_dic(dic)
        for index in range(0, simulator_count):
            db_name = f"blockchain_test_{index}_sim_and_wallets.db"
            bt_tools = await create_block_tools_async(
                consensus_constants, const_dict=dic, keychain=keychain1, config_overrides=config_overrides
            )  # block tools modifies constants
            sim = setup_full_node(
                bt_tools.constants,
                bt_tools.config["self_hostname"],
                db_name,
                bt_tools,
                simulator=True,
                db_version=db_version,
            )
            simulators.append(await sim.__anext__())
            node_iters.append(sim)

        for index in range(0, wallet_count):
            if key_seed is None:
                seed = std_hash(uint32(index))
            else:
                seed = key_seed
            bt_tools = await create_block_tools_async(
                consensus_constants, const_dict=dic, keychain=keychain2, config_overrides=config_overrides
            )  # block tools modifies constants
            wlt = setup_wallet_node(
                bt_tools.config["self_hostname"],
                bt_tools.constants,
                bt_tools,
                None,
                key_seed=seed,
                starting_height=starting_height,
                initial_num_public_keys=initial_num_public_keys,
            )
            wallets.append(await wlt.__anext__())
            node_iters.append(wlt)

        yield simulators, wallets

        await _teardown_nodes(node_iters)


async def setup_harvester_farmer(
    bt: BlockTools, tmp_path: Path, consensus_constants: ConsensusConstants, *, start_services: bool
):
    if start_services:
        farmer_port = uint16(0)
    else:
        # If we don't start the services, we won't be able to get the farmer port, which the harvester needs
        farmer_port = uint16(find_available_listen_port("farmer_server"))

    farmer_setup_iter = setup_farmer(
        bt,
        tmp_path / "farmer",
        bt.config["self_hostname"],
        consensus_constants,
        uint16(0),
        start_service=start_services,
        port=farmer_port,
    )

    farmer_service = await farmer_setup_iter.__anext__()
    farmer_port = farmer_service._server._port
    node_iters = [
        setup_harvester(
            bt,
            tmp_path / "harvester",
            bt.config["self_hostname"],
            farmer_port,
            consensus_constants,
            start_services,
        ),
        farmer_setup_iter,
    ]

    harvester_service = await node_iters[0].__anext__()

    yield harvester_service, farmer_service

    await _teardown_nodes(node_iters)


async def setup_farmer_multi_harvester(
    block_tools: BlockTools,
    harvester_count: int,
    temp_dir: Path,
    consensus_constants: ConsensusConstants,
) -> AsyncIterator[Tuple[List[Service], Service]]:

    node_iterators = [
        setup_farmer(
            block_tools,
            temp_dir / "farmer",
            block_tools.config["self_hostname"],
            consensus_constants,
            uint16(0),
        )
    ]
    farmer_service = await node_iterators[0].__anext__()
    farmer_port = farmer_service._server._port

    for i in range(0, harvester_count):
        root_path: Path = temp_dir / f"harvester_{i}"
        node_iterators.append(
            setup_harvester(
                block_tools,
                root_path,
                block_tools.config["self_hostname"],
                farmer_port,
                consensus_constants,
                False,
            )
        )

    harvester_services = []
    for node in node_iterators[1:]:
        harvester_service = await node.__anext__()
        harvester_services.append(harvester_service)

    yield harvester_services, farmer_service

    for harvester_service in harvester_services:
        harvester_service.stop()
        await harvester_service.wait_closed()

    farmer_service.stop()
    await farmer_service.wait_closed()

    await _teardown_nodes(node_iterators)


async def setup_full_system(
    consensus_constants: ConsensusConstants,
    shared_b_tools: BlockTools,
    b_tools: BlockTools = None,
    b_tools_1: BlockTools = None,
    db_version=1,
    connect_to_daemon=False,
):
    with TempKeyring(populate=True) as keychain1, TempKeyring(populate=True) as keychain2:
        if b_tools is None:
            b_tools = await create_block_tools_async(constants=test_constants, keychain=keychain1)
        if b_tools_1 is None:
            b_tools_1 = await create_block_tools_async(constants=test_constants, keychain=keychain2)

        if connect_to_daemon:
            daemon_iter = setup_daemon(btools=b_tools)
            daemon_ws = await daemon_iter.__anext__()

        # Start the introducer first so we can find out the port, and use that for the nodes
        introducer_iter = setup_introducer(shared_b_tools, uint16(0))
        introducer, introducer_server = await introducer_iter.__anext__()

        # Then start the full node so we can use the port for the farmer and timelord
        full_node_iters = [
            setup_full_node(
                consensus_constants,
                f"blockchain_test_{i}.db",
                shared_b_tools.config["self_hostname"],
                b_tools if i == 0 else b_tools_1,
                introducer_server._port,
                False,
                10,
                True,
                connect_to_daemon=connect_to_daemon,
                db_version=db_version,
            )
            for i in range(2)
        ]

        node_apis = [await fni.__anext__() for fni in full_node_iters]
        full_node_0_port = node_apis[0].full_node.server.get_port()

        farmer_iter = setup_farmer(
            shared_b_tools,
            shared_b_tools.root_path / "harvester",
            shared_b_tools.config["self_hostname"],
            consensus_constants,
            full_node_0_port,
        )
        farmer_service = await farmer_iter.__anext__()

        harvester_iter = setup_harvester(
            shared_b_tools,
            shared_b_tools.root_path / "harvester",
            shared_b_tools.config["self_hostname"],
            farmer_service._server.get_port(),
            consensus_constants,
        )

        vdf1_port = uint16(find_available_listen_port("vdf1"))
        vdf2_port = uint16(find_available_listen_port("vdf2"))
        timelord_iter = setup_timelord(full_node_0_port, False, consensus_constants, b_tools, vdf_port=vdf1_port)
        timelord_bluebox_iter = setup_timelord(1000, True, consensus_constants, b_tools_1, vdf_port=vdf2_port)

        harvester_service = await harvester_iter.__anext__()
        harvester = harvester_service._node

        async def num_connections():
            count = len(harvester.server.all_connections.items())
            return count

        await time_out_assert_custom_interval(10, 3, num_connections, 1)

        node_iters = [
            introducer_iter,
            harvester_iter,
            farmer_iter,
            setup_vdf_clients(shared_b_tools, shared_b_tools.config["self_hostname"], vdf1_port),
            timelord_iter,
            full_node_iters[0],
            full_node_iters[1],
            setup_vdf_client(shared_b_tools, shared_b_tools.config["self_hostname"], vdf2_port),
            timelord_bluebox_iter,
        ]
        if connect_to_daemon:
            node_iters.append(daemon_iter)

        timelord, _ = await timelord_iter.__anext__()
        vdf_clients = await node_iters[3].__anext__()
        timelord_bluebox, timelord_bluebox_server = await timelord_bluebox_iter.__anext__()
        vdf_bluebox_clients = await node_iters[7].__anext__()

        ret = (
            node_apis[0],
            node_apis[1],
            harvester,
            farmer_service._node,
            introducer,
            timelord,
            vdf_clients,
            vdf_bluebox_clients,
            timelord_bluebox,
            timelord_bluebox_server,
        )

        if connect_to_daemon:
            yield ret + (daemon_ws,)
        else:
            yield ret

        if connect_to_daemon:
            await _teardown_nodes(node_iters[:-1])
            await _teardown_nodes([node_iters[-1]])
        else:
            await _teardown_nodes(node_iters)
