from __future__ import annotations

import asyncio
import contextlib
import logging
from contextlib import AsyncExitStack, ExitStack, asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import AsyncIterator, Dict, List, Optional, Tuple, Union

import anyio

from chia._tests.environments.full_node import FullNodeEnvironment
from chia._tests.environments.wallet import WalletEnvironment
from chia.consensus.constants import ConsensusConstants
from chia.daemon.server import WebSocketServer
from chia.farmer.farmer import Farmer
from chia.full_node.full_node_api import FullNodeAPI
from chia.harvester.harvester import Harvester
from chia.introducer.introducer_api import IntroducerAPI
from chia.protocols.shared_protocol import Capability
from chia.rpc.wallet_rpc_client import WalletRpcClient
from chia.server.server import ChiaServer
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
from chia.simulator.start_simulator import SimulatorFullNodeService
from chia.types.aliases import FarmerService, FullNodeService, HarvesterService, TimelordService, WalletService
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.peer_info import UnresolvedPeerInfo
from chia.util.hash import std_hash
from chia.util.ints import uint16, uint32
from chia.util.keychain import Keychain
from chia.util.timing import adjusted_timeout, backoff_times
from chia.wallet.wallet_node import WalletNode

OldSimulatorsAndWallets = Tuple[List[FullNodeSimulator], List[Tuple[WalletNode, ChiaServer]], BlockTools]
SimulatorsAndWalletsServices = Tuple[List[SimulatorFullNodeService], List[WalletService], BlockTools]


@dataclass(frozen=True)
class FullSystem:
    node_1: Union[FullNodeService, SimulatorFullNodeService]
    node_2: Union[FullNodeService, SimulatorFullNodeService]
    harvester: Harvester
    farmer: Farmer
    introducer: IntroducerAPI
    timelord: TimelordService
    timelord_bluebox: TimelordService
    daemon: WebSocketServer


@dataclass
class SimulatorsAndWallets:
    simulators: List[FullNodeEnvironment]
    wallets: List[WalletEnvironment]
    bt: BlockTools


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

    config_overrides = {"full_node.max_sync_wait": 0}
    with TempKeyring(populate=True) as keychain1, TempKeyring(populate=True) as keychain2:
        bt1 = await create_block_tools_async(
            constants=consensus_constants, keychain=keychain1, config_overrides=config_overrides
        )
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
                await create_block_tools_async(
                    constants=consensus_constants, keychain=keychain2, config_overrides=config_overrides
                ),
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
    config_overrides = {"full_node.max_sync_wait": 0}
    with ExitStack() as stack:
        keychains = [stack.enter_context(TempKeyring(populate=True)) for _ in range(n)]
        async with AsyncExitStack() as async_exit_stack:
            nodes = [
                await async_exit_stack.enter_async_context(
                    setup_full_node(
                        consensus_constants,
                        f"blockchain_test_{i}.db",
                        self_hostname,
                        await create_block_tools_async(
                            constants=consensus_constants, keychain=keychain, config_overrides=config_overrides
                        ),
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
    db_version: int = 2,
    config_overrides: Optional[Dict[str, int]] = None,
    disable_capabilities: Optional[List[Capability]] = None,
) -> AsyncIterator[SimulatorsAndWallets]:
    with TempKeyring(populate=True) as keychain1, TempKeyring(populate=True) as keychain2:
        if config_overrides is None:
            config_overrides = {}
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
            async with contextlib.AsyncExitStack() as exit_stack:
                wallets: List[WalletEnvironment] = []
                for service in wallets_services:
                    assert service.rpc_server is not None

                    rpc_client = await exit_stack.enter_async_context(
                        WalletRpcClient.create_as_context(
                            self_hostname=service.self_hostname,
                            port=service.rpc_server.listen_port,
                            root_path=service.root_path,
                            net_config=service.config,
                        ),
                    )
                    wallets.append(WalletEnvironment(service=service, rpc_client=rpc_client))

                yield SimulatorsAndWallets(
                    simulators=[FullNodeEnvironment(service=service) for service in simulators],
                    wallets=wallets,
                    bt=bt_tools[0],
                )


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
    db_version: int = 2,
    config_overrides: Optional[Dict[str, int]] = None,
    disable_capabilities: Optional[List[Capability]] = None,
) -> AsyncIterator[Tuple[List[SimulatorFullNodeService], List[WalletService], BlockTools]]:
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
) -> AsyncIterator[Tuple[List[BlockTools], List[SimulatorFullNodeService], List[WalletService]]]:
    if config_overrides is not None and "full_node.max_sync_wait" not in config_overrides:
        config_overrides["full_node.max_sync_wait"] = 0
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

        simulators: List[SimulatorFullNodeService] = [
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

        wallets: List[WalletService] = [
            await async_exit_stack.enter_async_context(
                setup_wallet_node(
                    bt_tools[index].config["self_hostname"],
                    bt_tools[index].constants,
                    bt_tools[index],
                    spam_filter_after_n_txs,
                    xch_spam_amount,
                    None,
                    key_seed=std_hash(uint32(index).stream_to_bytes()) if key_seed is None else key_seed,
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
) -> AsyncIterator[Tuple[List[HarvesterService], FarmerService, BlockTools]]:
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
            farmer_peer = UnresolvedPeerInfo(block_tools.config["self_hostname"], farmer_service._server.get_port())
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
    db_version: int = 2,
) -> AsyncIterator[FullSystem]:
    with TempKeyring(populate=True) as keychain1, TempKeyring(populate=True) as keychain2:
        async with setup_full_system_inner(
            b_tools, b_tools_1, False, consensus_constants, db_version, keychain1, keychain2, shared_b_tools
        ) as full_system:
            yield full_system


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
) -> AsyncIterator[FullSystem]:
    config_overrides = {"full_node.max_sync_wait": 0}
    if b_tools is None:
        b_tools = await create_block_tools_async(
            constants=consensus_constants, keychain=keychain1, config_overrides=config_overrides
        )
    if b_tools_1 is None:
        b_tools_1 = await create_block_tools_async(
            constants=consensus_constants, keychain=keychain2, config_overrides=config_overrides
        )

    self_hostname = shared_b_tools.config["self_hostname"]

    async with AsyncExitStack() as async_exit_stack:
        vdf1_port = uint16(find_available_listen_port("vdf1"))
        vdf2_port = uint16(find_available_listen_port("vdf2"))

        await async_exit_stack.enter_async_context(
            setup_vdf_clients(bt=b_tools, self_hostname=self_hostname, port=vdf1_port)
        )
        await async_exit_stack.enter_async_context(
            setup_vdf_client(bt=shared_b_tools, self_hostname=self_hostname, port=vdf2_port)
        )

        daemon_ws = await async_exit_stack.enter_async_context(setup_daemon(btools=b_tools))

        # Start the introducer first so we can find out the port, and use that for the nodes
        introducer_service = await async_exit_stack.enter_async_context(setup_introducer(shared_b_tools, uint16(0)))
        introducer = introducer_service._api
        introducer_server = introducer_service._node.server

        # Then start the full node so we can use the port for the farmer and timelord
        node_1 = await async_exit_stack.enter_async_context(
            setup_full_node(
                consensus_constants,
                "blockchain_test_1.db",
                self_hostname=self_hostname,
                local_bt=b_tools,
                introducer_port=introducer_server._port,
                simulator=False,
                send_uncompact_interval=0,
                sanitize_weight_proof_only=False,
                connect_to_daemon=connect_to_daemon,
                db_version=db_version,
            )
        )
        node_2 = await async_exit_stack.enter_async_context(
            setup_full_node(
                consensus_constants,
                "blockchain_test_2.db",
                self_hostname=self_hostname,
                local_bt=b_tools_1,
                introducer_port=introducer_server._port,
                simulator=False,
                send_uncompact_interval=10,
                sanitize_weight_proof_only=True,
                connect_to_daemon=False,  # node 2 doesn't connect to the daemon
                db_version=db_version,
            )
        )

        farmer_service = await async_exit_stack.enter_async_context(
            setup_farmer(
                shared_b_tools,
                shared_b_tools.root_path / "harvester",
                self_hostname=self_hostname,
                consensus_constants=consensus_constants,
                full_node_port=node_1._api.full_node.server.get_port(),
            )
        )
        harvester_service = await async_exit_stack.enter_async_context(
            setup_harvester(
                shared_b_tools,
                shared_b_tools.root_path / "harvester",
                UnresolvedPeerInfo(self_hostname, farmer_service._server.get_port()),
                consensus_constants,
            )
        )
        harvester = harvester_service._node

        timelord = await async_exit_stack.enter_async_context(
            setup_timelord(
                full_node_port=node_1._api.full_node.server.get_port(),
                sanitizer=False,
                consensus_constants=consensus_constants,
                config=b_tools.config,
                root_path=b_tools.root_path,
                vdf_port=vdf1_port,
            )
        )
        timelord_bluebox_service = await async_exit_stack.enter_async_context(
            setup_timelord(
                node_2._api.full_node.server.get_port(),
                True,
                consensus_constants,
                b_tools_1.config,
                b_tools_1.root_path,
                vdf_port=vdf2_port,
            )
        )

        with anyio.fail_after(delay=adjusted_timeout(10)):
            for backoff in backoff_times():
                if len(harvester.server.all_connections.items()) > 0:
                    break

                await asyncio.sleep(backoff)

        full_system = FullSystem(
            node_1=node_1,
            node_2=node_2,
            harvester=harvester,
            farmer=farmer_service._node,
            introducer=introducer,
            timelord=timelord,
            timelord_bluebox=timelord_bluebox_service,
            daemon=daemon_ws,
        )
        yield full_system
