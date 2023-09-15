from __future__ import annotations

import logging
from contextlib import AsyncExitStack, ExitStack, asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator, Dict, List, Optional, Tuple

from chia.consensus.constants import ConsensusConstants
from chia.daemon.server import WebSocketServer
from chia.farmer.farmer import Farmer
from chia.farmer.farmer_api import FarmerAPI
from chia.full_node.full_node import FullNode
from chia.full_node.full_node_api import FullNodeAPI
from chia.harvester.harvester import Harvester
from chia.harvester.harvester_api import HarvesterAPI
from chia.protocols.shared_protocol import Capability
from chia.server.server import ChiaServer
from chia.server.start_service import Service
from chia.simulator.block_tools import BlockTools, create_block_tools_async
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
from chia.timelord.timelord_api import TimelordAPI
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.peer_info import UnresolvedPeerInfo
from chia.util.hash import std_hash
from chia.util.ints import uint16, uint32
from chia.util.keychain import Keychain
from chia.wallet.wallet_node import WalletNode
from chia.wallet.wallet_node_api import WalletNodeAPI

SimulatorsAndWallets = Tuple[List[FullNodeSimulator], List[Tuple[WalletNode, ChiaServer]], BlockTools]
SimulatorsAndWalletsServices = Tuple[
    List[Service[FullNode, FullNodeSimulator]], List[Service[WalletNode, WalletNodeAPI]], BlockTools
]


def cleanup_keyring(keyring: TempKeyring) -> None:
    keyring.cleanup()


log = logging.getLogger(__name__)


@asynccontextmanager
async def setup_two_nodes(
    consensus_constants: ConsensusConstants, db_version: int, self_hostname: str
) -> AsyncIterator[Tuple[FullNodeAPI, FullNodeAPI, ChiaServer, ChiaServer, BlockTools]]:
    """
    Setup and teardown of two full nodes, with blockchains and separate DBs.
    """

    with TempKeyring(populate=True) as keychain1, TempKeyring(populate=True) as keychain2:
        bt1 = await create_block_tools_async(constants=consensus_constants, keychain=keychain1)
        async with setup_full_node(
            consensus_constants,
            "blockchain_test.db",
            self_hostname,
            bt1,
            simulator=False,
            db_version=db_version,
        ) as service1:
            async with setup_full_node(
                consensus_constants,
                "blockchain_test_2.db",
                self_hostname,
                await create_block_tools_async(constants=consensus_constants, keychain=keychain2),
                simulator=False,
                db_version=db_version,
            ) as service2:
                fn1 = service1._api
                fn2 = service2._api

                yield fn1, fn2, fn1.full_node.server, fn2.full_node.server, bt1


@asynccontextmanager
async def setup_n_nodes(
    consensus_constants: ConsensusConstants, n: int, db_version: int, self_hostname: str
) -> AsyncIterator[List[FullNodeAPI]]:
    """
    Setup and teardown of n full nodes, with blockchains and separate DBs.
    """
    with ExitStack() as stack:
        keychains = [stack.enter_context(TempKeyring(populate=True)) for _ in range(n)]
        async with AsyncExitStack() as async_exit_stack:
            nodes = [
                await async_exit_stack.enter_async_context(
                    setup_full_node(
                        consensus_constants,
                        f"blockchain_test_{i}.db",
                        self_hostname,
                        await create_block_tools_async(constants=consensus_constants, keychain=keychain),
                        simulator=False,
                        db_version=db_version,
                    )
                )
                for i, keychain in enumerate(keychains)
            ]

            yield [node._api for node in nodes]


@asynccontextmanager
async def setup_simulators_and_wallets(
    simulator_count: int,
    wallet_count: int,
    consensus_constants: ConsensusConstants,
    spam_filter_after_n_txs: int = 200,
    xch_spam_amount: int = 1000000,
    *,
    key_seed: Optional[bytes32] = None,
    initial_num_public_keys: int = 5,
    db_version: int = 1,
    config_overrides: Optional[Dict[str, int]] = None,
    disable_capabilities: Optional[List[Capability]] = None,
) -> AsyncIterator[Tuple[List[FullNodeSimulator], List[Tuple[WalletNode, ChiaServer]], BlockTools]]:
    with TempKeyring(populate=True) as keychain1, TempKeyring(populate=True) as keychain2:
        async with setup_simulators_and_wallets_inner(
            db_version,
            consensus_constants,
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
        ) as (bt_tools, simulators, wallets_services):
            wallets = []
            for wallets_servic in wallets_services:
                wallets.append((wallets_servic._node, wallets_servic._node.server))

            nodes = []
            for nodes_service in simulators:
                nodes.append(nodes_service._api)

            yield nodes, wallets, bt_tools[0]


@asynccontextmanager
async def setup_simulators_and_wallets_service(
    simulator_count: int,
    wallet_count: int,
    consensus_constants: ConsensusConstants,
    spam_filter_after_n_txs: int = 200,
    xch_spam_amount: int = 1000000,
    *,
    key_seed: Optional[bytes32] = None,
    initial_num_public_keys: int = 5,
    db_version: int = 1,
    config_overrides: Optional[Dict[str, int]] = None,
    disable_capabilities: Optional[List[Capability]] = None,
) -> AsyncIterator[
    Tuple[List[Service[FullNode, FullNodeSimulator]], List[Service[WalletNode, WalletNodeAPI]], BlockTools]
]:
    with TempKeyring(populate=True) as keychain1, TempKeyring(populate=True) as keychain2:
        async with setup_simulators_and_wallets_inner(
            db_version,
            consensus_constants,
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
        ) as (bt_tools, simulators, wallets_services):
            yield simulators, wallets_services, bt_tools[0]


@asynccontextmanager
async def setup_simulators_and_wallets_inner(
    db_version: int,
    consensus_constants: ConsensusConstants,
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
) -> AsyncIterator[
    Tuple[List[BlockTools], List[Service[FullNode, FullNodeSimulator]], List[Service[WalletNode, WalletNodeAPI]]]
]:
    async with AsyncExitStack() as async_exit_stack:
        bt_tools: List[BlockTools] = [
            await create_block_tools_async(consensus_constants, keychain=keychain1, config_overrides=config_overrides)
            for _ in range(0, simulator_count)
        ]
        if wallet_count > simulator_count:
            for _ in range(0, wallet_count - simulator_count):
                bt_tools.append(
                    await create_block_tools_async(
                        consensus_constants, keychain=keychain2, config_overrides=config_overrides
                    )
                )

        simulators: List[Service[FullNode, FullNodeSimulator]] = [
            await async_exit_stack.enter_async_context(
                # Passing simulator=True gets us this type guaranteed
                setup_full_node(  # type: ignore[arg-type]
                    consensus_constants=bt_tools[index].constants,
                    db_name=f"blockchain_test_{index}_sim_and_wallets.db",
                    self_hostname=bt_tools[index].config["self_hostname"],
                    local_bt=bt_tools[index],
                    simulator=True,
                    db_version=db_version,
                    disable_capabilities=disable_capabilities,
                )
            )
            for index in range(0, simulator_count)
        ]

        wallets: List[Service[WalletNode, WalletNodeAPI]] = [
            await async_exit_stack.enter_async_context(
                setup_wallet_node(
                    bt_tools[index].config["self_hostname"],
                    bt_tools[index].constants,
                    bt_tools[index],
                    spam_filter_after_n_txs,
                    xch_spam_amount,
                    None,
                    key_seed=std_hash(uint32(index)) if key_seed is None else key_seed,
                    initial_num_public_keys=initial_num_public_keys,
                )
            )
            for index in range(0, wallet_count)
        ]

        yield bt_tools, simulators, wallets


@asynccontextmanager
async def setup_farmer_multi_harvester(
    block_tools: BlockTools,
    harvester_count: int,
    temp_dir: Path,
    consensus_constants: ConsensusConstants,
    *,
    start_services: bool,
) -> AsyncIterator[Tuple[List[Service[Harvester, HarvesterAPI]], Service[Farmer, FarmerAPI], BlockTools]]:
    async with AsyncExitStack() as async_exit_stack:
        farmer_service = await async_exit_stack.enter_async_context(
            setup_farmer(
                block_tools,
                temp_dir / "farmer",
                block_tools.config["self_hostname"],
                consensus_constants,
                port=uint16(0),
                start_service=start_services,
            )
        )
        if start_services:
            farmer_peer = UnresolvedPeerInfo(block_tools.config["self_hostname"], uint16(farmer_service._server._port))
        else:
            farmer_peer = None
        harvester_services = [
            await async_exit_stack.enter_async_context(
                setup_harvester(
                    block_tools,
                    temp_dir / f"harvester_{i}",
                    farmer_peer,
                    consensus_constants,
                    start_service=start_services,
                )
            )
            for i in range(0, harvester_count)
        ]

        yield harvester_services, farmer_service, block_tools


@asynccontextmanager
async def setup_full_system(
    consensus_constants: ConsensusConstants,
    shared_b_tools: BlockTools,
    b_tools: Optional[BlockTools] = None,
    b_tools_1: Optional[BlockTools] = None,
    db_version: int = 1,
) -> AsyncIterator[
    Tuple[Any, Any, Harvester, Farmer, Any, Service[Timelord, TimelordAPI], object, object, Any, ChiaServer]
]:
    with TempKeyring(populate=True) as keychain1, TempKeyring(populate=True) as keychain2:
        async with setup_full_system_inner(
            b_tools, b_tools_1, False, consensus_constants, db_version, keychain1, keychain2, shared_b_tools
        ) as (_, ret):
            yield ret


@asynccontextmanager
async def setup_full_system_connect_to_deamon(
    consensus_constants: ConsensusConstants,
    shared_b_tools: BlockTools,
    b_tools: Optional[BlockTools] = None,
    b_tools_1: Optional[BlockTools] = None,
    db_version: int = 1,
) -> AsyncIterator[
    Tuple[
        Any,
        Any,
        Harvester,
        Farmer,
        Any,
        Service[Timelord, TimelordAPI],
        object,
        object,
        Any,
        ChiaServer,
        Optional[WebSocketServer],
    ],
]:
    with TempKeyring(populate=True) as keychain1, TempKeyring(populate=True) as keychain2:
        async with setup_full_system_inner(
            b_tools, b_tools_1, True, consensus_constants, db_version, keychain1, keychain2, shared_b_tools
        ) as (daemon_ws, ret):
            yield ret + (daemon_ws,)


@asynccontextmanager
async def setup_full_system_inner(
    b_tools: Optional[BlockTools],
    b_tools_1: Optional[BlockTools],
    connect_to_daemon: bool,
    consensus_constants: ConsensusConstants,
    db_version: int,
    keychain1: Keychain,
    keychain2: Keychain,
    shared_b_tools: BlockTools,
) -> AsyncIterator[
    Tuple[
        Optional[WebSocketServer],
        Tuple[Any, Any, Harvester, Farmer, Any, Service[Timelord, TimelordAPI], object, object, Any, ChiaServer],
    ]
]:
    if b_tools is None:
        b_tools = await create_block_tools_async(constants=consensus_constants, keychain=keychain1)
    if b_tools_1 is None:
        b_tools_1 = await create_block_tools_async(constants=consensus_constants, keychain=keychain2)
    async with AsyncExitStack() as async_exit_stack:
        # Start the introducer first so we can find out the port, and use that for the nodes
        introducer_service = await async_exit_stack.enter_async_context(setup_introducer(shared_b_tools, uint16(0)))
        introducer = introducer_service._api
        introducer_server = introducer_service._node.server

        # Then start the full node so we can use the port for the farmer and timelord
        nodes = [
            await async_exit_stack.enter_async_context(
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
            )
            for i in range(2)
        ]
        node_apis = [fni._api for fni in nodes]
        full_node_0_port = node_apis[0].full_node.server.get_port()
        farmer_service = await async_exit_stack.enter_async_context(
            setup_farmer(
                shared_b_tools,
                shared_b_tools.root_path / "harvester",
                shared_b_tools.config["self_hostname"],
                consensus_constants,
                full_node_0_port,
            )
        )
        harvester_service = await async_exit_stack.enter_async_context(
            setup_harvester(
                shared_b_tools,
                shared_b_tools.root_path / "harvester",
                UnresolvedPeerInfo(shared_b_tools.config["self_hostname"], farmer_service._server.get_port()),
                consensus_constants,
            )
        )
        harvester = harvester_service._node

        vdf1_port = uint16(find_available_listen_port("vdf1"))
        vdf2_port = uint16(find_available_listen_port("vdf2"))

        timelord = await async_exit_stack.enter_async_context(
            setup_timelord(
                full_node_0_port,
                False,
                consensus_constants,
                b_tools.config,
                b_tools.root_path,
                vdf_port=vdf1_port,
            )
        )
        timelord_bluebox_service = await async_exit_stack.enter_async_context(
            setup_timelord(
                uint16(1000),
                True,
                consensus_constants,
                b_tools_1.config,
                b_tools_1.root_path,
                vdf_port=vdf2_port,
            )
        )

        async def num_connections() -> int:
            count = len(harvester.server.all_connections.items())
            return count

        await time_out_assert_custom_interval(10, 3, num_connections, 1)
        vdf_clients = await async_exit_stack.enter_async_context(
            setup_vdf_clients(shared_b_tools, shared_b_tools.config["self_hostname"], vdf1_port)
        )
        vdf_bluebox_clients = await async_exit_stack.enter_async_context(
            setup_vdf_client(shared_b_tools, shared_b_tools.config["self_hostname"], vdf2_port)
        )
        timelord_bluebox = timelord_bluebox_service._api
        timelord_bluebox_server = timelord_bluebox_service._node.server
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
        daemon_ws = await async_exit_stack.enter_async_context(setup_daemon(btools=b_tools))
        yield daemon_ws, ret
