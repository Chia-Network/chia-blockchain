from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any, AsyncGenerator, AsyncIterator, Dict, List, Optional, Tuple, Union

from chia.consensus.constants import ConsensusConstants
from chia.daemon.server import WebSocketServer
from chia.farmer.farmer import Farmer
from chia.full_node.full_node import FullNode
from chia.full_node.full_node_api import FullNodeAPI
from chia.harvester.harvester import Harvester
from chia.protocols.shared_protocol import Capability
from chia.server.server import ChiaServer
from chia.server.start_service import Service
from chia.simulator.block_tools import BlockTools, create_block_tools_async, test_constants
from chia.simulator.full_node_simulator import FullNodeSimulator
from chia.simulator.keyring import TempKeyring
from chia.simulator.setup_services import (
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
from chia.simulator.socket import find_available_listen_port
from chia.simulator.time_out_assert import time_out_assert_custom_interval
from chia.timelord.timelord import Timelord
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.peer_info import PeerInfo
from chia.util.hash import std_hash
from chia.util.ints import uint16, uint32
from chia.util.keychain import Keychain
from chia.wallet.wallet_node import WalletNode

SimulatorsAndWallets = Tuple[List[FullNodeSimulator], List[Tuple[WalletNode, ChiaServer]], BlockTools]
SimulatorsAndWalletsServices = Tuple[List[Service[FullNode]], List[Service[WalletNode]], BlockTools]


def cleanup_keyring(keyring: TempKeyring) -> None:
    keyring.cleanup()


log = logging.getLogger(__name__)


def constants_for_dic(dic: Dict[str, int]) -> ConsensusConstants:
    return test_constants.replace(**dic)


async def _teardown_nodes(node_aiters: List[AsyncGenerator[Any, None]]) -> None:
    awaitables = [node_iter.__anext__() for node_iter in node_aiters]
    for sublist_awaitable in asyncio.as_completed(awaitables):
        try:
            await sublist_awaitable
        except StopAsyncIteration:
            pass


async def setup_two_nodes(
    consensus_constants: ConsensusConstants, db_version: int, self_hostname: str
) -> AsyncGenerator[Tuple[FullNodeAPI, FullNodeAPI, ChiaServer, ChiaServer, BlockTools], None]:
    """
    Setup and teardown of two full nodes, with blockchains and separate DBs.
    """

    with TempKeyring(populate=True) as keychain1, TempKeyring(populate=True) as keychain2:
        bt1 = await create_block_tools_async(constants=test_constants, keychain=keychain1)
        node_iters = [
            setup_full_node(
                consensus_constants,
                "blockchain_test.db",
                self_hostname,
                bt1,
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

        service1 = await node_iters[0].__anext__()
        service2 = await node_iters[1].__anext__()
        fn1 = service1._api
        fn2 = service2._api

        yield fn1, fn2, fn1.full_node.server, fn2.full_node.server, bt1

        await _teardown_nodes(node_iters)


async def setup_n_nodes(
    consensus_constants: ConsensusConstants, n: int, db_version: int, self_hostname: str
) -> AsyncGenerator[List[FullNodeAPI], None]:
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
        service = await ni.__anext__()
        nodes.append(service._api)

    yield nodes

    await _teardown_nodes(node_iters)

    for keyring in keyrings_to_cleanup:
        keyring.cleanup()


async def setup_node_and_wallet(
    consensus_constants: ConsensusConstants,
    self_hostname: str,
    key_seed: Optional[bytes32] = None,
    db_version: int = 1,
    disable_capabilities: Optional[List[Capability]] = None,
) -> AsyncGenerator[Tuple[FullNodeAPI, WalletNode, ChiaServer, ChiaServer, BlockTools], None]:
    with TempKeyring(populate=True) as keychain:
        btools = await create_block_tools_async(constants=test_constants, keychain=keychain)
        full_node_iter = setup_full_node(
            consensus_constants,
            "blockchain_test.db",
            self_hostname,
            btools,
            simulator=False,
            db_version=db_version,
            disable_capabilities=disable_capabilities,
        )

        wallet_node_iter = setup_wallet_node(
            btools.config["self_hostname"],
            consensus_constants,
            btools,
            None,
            key_seed=key_seed,
        )

        full_node_service = await full_node_iter.__anext__()
        full_node_api = full_node_service._api
        wallet_node_service = await wallet_node_iter.__anext__()
        wallet = wallet_node_service._node
        s2 = wallet_node_service._node.server

        yield full_node_api, wallet, full_node_api.full_node.server, s2, btools

        await _teardown_nodes([full_node_iter])
        await _teardown_nodes([wallet_node_iter])


async def setup_simulators_and_wallets(
    simulator_count: int,
    wallet_count: int,
    dic: Dict[str, int],
    spam_filter_after_n_txs: int = 200,
    xch_spam_amount: int = 1000000,
    *,
    key_seed: Optional[bytes32] = None,
    initial_num_public_keys: int = 5,
    db_version: int = 1,
    config_overrides: Optional[Dict[str, int]] = None,
    disable_capabilities: Optional[List[Capability]] = None,
) -> AsyncGenerator[Tuple[List[FullNodeAPI], List[Tuple[WalletNode, ChiaServer]], BlockTools], None]:
    with TempKeyring(populate=True) as keychain1, TempKeyring(populate=True) as keychain2:
        res = await setup_simulators_and_wallets_inner(
            db_version,
            dic,
            initial_num_public_keys,
            key_seed,
            keychain1,
            keychain2,
            simulator_count,
            spam_filter_after_n_txs,
            wallet_count,
            xch_spam_amount,
            config_overrides,
            disable_capabilities,
        )

        bt_tools, node_iters, simulators, wallets_services = res
        wallets = []
        for wallets_servic in wallets_services:
            wallets.append((wallets_servic._node, wallets_servic._node.server))

        nodes = []
        for nodes_service in simulators:
            nodes.append(nodes_service._api)

        yield nodes, wallets, bt_tools[0]

        await _teardown_nodes(node_iters)


async def setup_simulators_and_wallets_service(
    simulator_count: int,
    wallet_count: int,
    dic: Dict[str, int],
    spam_filter_after_n_txs: int = 200,
    xch_spam_amount: int = 1000000,
    *,
    key_seed: Optional[bytes32] = None,
    initial_num_public_keys: int = 5,
    db_version: int = 1,
    config_overrides: Optional[Dict[str, int]] = None,
    disable_capabilities: Optional[List[Capability]] = None,
) -> AsyncGenerator[Tuple[List[Service[FullNode]], List[Service[WalletNode]], BlockTools], None]:
    with TempKeyring(populate=True) as keychain1, TempKeyring(populate=True) as keychain2:
        res = await setup_simulators_and_wallets_inner(
            db_version,
            dic,
            initial_num_public_keys,
            key_seed,
            keychain1,
            keychain2,
            simulator_count,
            spam_filter_after_n_txs,
            wallet_count,
            xch_spam_amount,
            config_overrides,
            disable_capabilities,
        )

        bt_tools, node_iters, simulators, wallets_services = res
        yield simulators, wallets_services, bt_tools[0]

        await _teardown_nodes(node_iters)


async def setup_simulators_and_wallets_inner(
    db_version: int,
    dic: Dict[str, int],
    initial_num_public_keys: int,
    key_seed: Optional[bytes32],
    keychain1: Keychain,
    keychain2: Keychain,
    simulator_count: int,
    spam_filter_after_n_txs: int,
    wallet_count: int,
    xch_spam_amount: int,
    config_overrides: Optional[Dict[str, int]],
    disable_capabilities: Optional[List[Capability]],
) -> Tuple[
    List[BlockTools],
    List[AsyncGenerator[Union[Service[FullNode], Service[WalletNode]], None]],
    List[Service[FullNode]],
    List[Service[WalletNode]],
]:
    simulators: List[Service[FullNode]] = []
    wallets: List[Service[WalletNode]] = []
    node_iters: List[AsyncGenerator[Union[Service[FullNode], Service[WalletNode]], None]] = []
    bt_tools: List[BlockTools] = []
    consensus_constants: ConsensusConstants = constants_for_dic(dic)
    for index in range(0, simulator_count):
        db_name = f"blockchain_test_{index}_sim_and_wallets.db"
        bt_tools.append(
            await create_block_tools_async(
                consensus_constants, const_dict=dic, keychain=keychain1, config_overrides=config_overrides
            )
        )  # block tools modifies constants
        sim = setup_full_node(
            bt_tools[index].constants,
            bt_tools[index].config["self_hostname"],
            db_name,
            bt_tools[index],
            simulator=True,
            db_version=db_version,
            disable_capabilities=disable_capabilities,
        )
        service = await sim.__anext__()
        simulators.append(service)
        node_iters.append(sim)
    for index in range(0, wallet_count):
        if key_seed is None:
            seed = std_hash(uint32(index))
        else:
            seed = key_seed
        if index > (len(bt_tools) - 1):
            wallet_bt_tools = await create_block_tools_async(
                consensus_constants, const_dict=dic, keychain=keychain2, config_overrides=config_overrides
            )  # block tools modifies constants
        else:
            wallet_bt_tools = bt_tools[index]
        wlt = setup_wallet_node(
            wallet_bt_tools.config["self_hostname"],
            wallet_bt_tools.constants,
            wallet_bt_tools,
            spam_filter_after_n_txs,
            xch_spam_amount,
            None,
            key_seed=seed,
            initial_num_public_keys=initial_num_public_keys,
        )
        wallet_service = await wlt.__anext__()
        wallets.append(wallet_service)
        node_iters.append(wlt)
    return bt_tools, node_iters, simulators, wallets


async def setup_farmer_multi_harvester(
    block_tools: BlockTools,
    harvester_count: int,
    temp_dir: Path,
    consensus_constants: ConsensusConstants,
    *,
    start_services: bool,
) -> AsyncIterator[Tuple[List[Service[Harvester]], Service[Farmer], BlockTools]]:

    farmer_node_iterators = [
        setup_farmer(
            block_tools,
            temp_dir / "farmer",
            block_tools.config["self_hostname"],
            consensus_constants,
            port=uint16(0),
            start_service=start_services,
        )
    ]
    farmer_service = await farmer_node_iterators[0].__anext__()
    if start_services:
        farmer_peer = PeerInfo(block_tools.config["self_hostname"], uint16(farmer_service._server._port))
    else:
        farmer_peer = None
    harvester_node_iterators = []
    for i in range(0, harvester_count):
        root_path: Path = temp_dir / f"harvester_{i}"
        harvester_node_iterators.append(
            setup_harvester(
                block_tools,
                root_path,
                farmer_peer,
                consensus_constants,
                start_service=start_services,
            )
        )

    harvester_services = []
    for node in harvester_node_iterators:
        harvester_service = await node.__anext__()
        harvester_services.append(harvester_service)

    yield harvester_services, farmer_service, block_tools

    for harvester_service in harvester_services:
        harvester_service.stop()
        await harvester_service.wait_closed()

    farmer_service.stop()
    await farmer_service.wait_closed()

    await _teardown_nodes(harvester_node_iterators)
    await _teardown_nodes(farmer_node_iterators)


async def setup_full_system(
    consensus_constants: ConsensusConstants,
    shared_b_tools: BlockTools,
    b_tools: Optional[BlockTools] = None,
    b_tools_1: Optional[BlockTools] = None,
    db_version: int = 1,
) -> AsyncGenerator[Tuple[Any, Any, Harvester, Farmer, Any, Service[Timelord], object, object, Any, ChiaServer], None]:
    with TempKeyring(populate=True) as keychain1, TempKeyring(populate=True) as keychain2:
        daemon_ws, node_iters, ret = await setup_full_system_inner(
            b_tools, b_tools_1, False, consensus_constants, db_version, keychain1, keychain2, shared_b_tools
        )

        yield ret

        await _teardown_nodes(node_iters)


async def setup_full_system_connect_to_deamon(
    consensus_constants: ConsensusConstants,
    shared_b_tools: BlockTools,
    b_tools: Optional[BlockTools] = None,
    b_tools_1: Optional[BlockTools] = None,
    db_version: int = 1,
) -> AsyncGenerator[
    Tuple[
        Any, Any, Harvester, Farmer, Any, Service[Timelord], object, object, Any, ChiaServer, Optional[WebSocketServer]
    ],
    None,
]:
    with TempKeyring(populate=True) as keychain1, TempKeyring(populate=True) as keychain2:
        daemon_ws, node_iters, ret = await setup_full_system_inner(
            b_tools, b_tools_1, True, consensus_constants, db_version, keychain1, keychain2, shared_b_tools
        )

        yield ret + (daemon_ws,)
        await _teardown_nodes(node_iters[:-1])
        await _teardown_nodes([node_iters[-1]])


async def setup_full_system_inner(
    b_tools: Optional[BlockTools],
    b_tools_1: Optional[BlockTools],
    connect_to_daemon: bool,
    consensus_constants: ConsensusConstants,
    db_version: int,
    keychain1: Keychain,
    keychain2: Keychain,
    shared_b_tools: BlockTools,
) -> Tuple[
    Optional[WebSocketServer],
    List[AsyncGenerator[object, None]],
    Tuple[Any, Any, Harvester, Farmer, Any, Service[Timelord], object, object, Any, ChiaServer],
]:
    if b_tools is None:
        b_tools = await create_block_tools_async(constants=test_constants, keychain=keychain1)
    if b_tools_1 is None:
        b_tools_1 = await create_block_tools_async(constants=test_constants, keychain=keychain2)
    daemon_ws = None
    if connect_to_daemon:
        daemon_iter = setup_daemon(btools=b_tools)
        daemon_ws = await daemon_iter.__anext__()
    # Start the introducer first so we can find out the port, and use that for the nodes
    introducer_iter = setup_introducer(shared_b_tools, uint16(0))
    introducer_service = await introducer_iter.__anext__()
    introducer = introducer_service._api
    introducer_server = introducer_service._node.server
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
    nodes = [await fni.__anext__() for fni in full_node_iters]
    node_apis = [fni._api for fni in nodes]
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
        PeerInfo(shared_b_tools.config["self_hostname"], farmer_service._server.get_port()),
        consensus_constants,
    )
    vdf1_port = uint16(find_available_listen_port("vdf1"))
    vdf2_port = uint16(find_available_listen_port("vdf2"))
    timelord_iter = setup_timelord(full_node_0_port, False, consensus_constants, b_tools, vdf_port=vdf1_port)
    timelord_bluebox_iter = setup_timelord(uint16(1000), True, consensus_constants, b_tools_1, vdf_port=vdf2_port)
    harvester_service = await harvester_iter.__anext__()
    harvester = harvester_service._node

    async def num_connections() -> int:
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
    timelord = await timelord_iter.__anext__()
    vdf_clients = await node_iters[3].__anext__()
    timelord_bluebox_service = await timelord_bluebox_iter.__anext__()
    timelord_bluebox = timelord_bluebox_service._api
    timelord_bluebox_server = timelord_bluebox_service._node.server
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
    return daemon_ws, node_iters, ret
