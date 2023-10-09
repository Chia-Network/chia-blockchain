# flake8: noqa E402 # See imports after multiprocessing.set_start_method
from __future__ import annotations

import dataclasses
import datetime
import multiprocessing
import os
import random
import sysconfig
import tempfile
from enum import Enum
from typing import Any, AsyncIterator, Dict, Iterator, List, Tuple, Union

import aiohttp
import pytest
import pytest_asyncio

# TODO: update after resolution in https://github.com/pytest-dev/pytest/issues/7469
from _pytest.fixtures import SubRequest

from chia.clvm.spend_sim import CostLogger

# Set spawn after stdlib imports, but before other imports
from chia.consensus.constants import ConsensusConstants
from chia.farmer.farmer import Farmer
from chia.farmer.farmer_api import FarmerAPI
from chia.full_node.full_node import FullNode
from chia.full_node.full_node_api import FullNodeAPI
from chia.harvester.harvester import Harvester
from chia.harvester.harvester_api import HarvesterAPI
from chia.protocols import full_node_protocol
from chia.rpc.farmer_rpc_client import FarmerRpcClient
from chia.rpc.harvester_rpc_client import HarvesterRpcClient
from chia.rpc.wallet_rpc_client import WalletRpcClient
from chia.seeder.crawler import Crawler
from chia.seeder.crawler_api import CrawlerAPI
from chia.seeder.dns_server import DNSServer
from chia.server.server import ChiaServer
from chia.server.start_service import Service
from chia.simulator.full_node_simulator import FullNodeSimulator
from chia.simulator.setup_nodes import (
    SimulatorsAndWallets,
    setup_full_system,
    setup_n_nodes,
    setup_simulators_and_wallets,
    setup_simulators_and_wallets_service,
    setup_two_nodes,
)
from chia.simulator.setup_services import setup_crawler, setup_daemon, setup_introducer, setup_seeder, setup_timelord
from chia.simulator.time_out_assert import time_out_assert
from chia.simulator.wallet_tools import WalletTool
from chia.timelord.timelord import Timelord
from chia.timelord.timelord_api import TimelordAPI
from chia.types.peer_info import PeerInfo
from chia.util.config import create_default_chia_config, lock_and_load_config
from chia.util.ints import uint16, uint32, uint64
from chia.util.keychain import Keychain
from chia.util.task_timing import main as task_instrumentation_main
from chia.util.task_timing import start_task_instrumentation, stop_task_instrumentation
from chia.wallet.wallet_node import WalletNode
from chia.wallet.wallet_node_api import WalletNodeAPI
from tests.core.data_layer.util import ChiaRoot
from tests.core.node_height import node_height_at_least
from tests.simulation.test_simulation import test_constants_modified
from tests.util.misc import BenchmarkRunner

multiprocessing.set_start_method("spawn")

from pathlib import Path

from chia.simulator.block_tools import BlockTools, create_block_tools, create_block_tools_async, test_constants
from chia.simulator.keyring import TempKeyring
from chia.simulator.setup_nodes import setup_farmer_multi_harvester
from chia.util.keyring_wrapper import KeyringWrapper


@pytest.fixture(name="seeded_random")
def seeded_random_fixture() -> random.Random:
    seeded_random = random.Random()
    seeded_random.seed(a=0, version=2)
    return seeded_random


@pytest.fixture(name="benchmark_runner")
def benchmark_runner_fixture(request: SubRequest) -> BenchmarkRunner:
    label = request.node.name
    return BenchmarkRunner(label=label)


@pytest.fixture(name="node_name_for_file")
def node_name_for_file_fixture(request: SubRequest) -> str:
    # TODO: handle other characters banned on windows
    return request.node.name.replace(os.sep, "_")


@pytest.fixture(name="test_time_for_file")
def test_time_for_file_fixture(request: SubRequest) -> str:
    return datetime.datetime.now().isoformat().replace(":", "_")


@pytest.fixture(name="task_instrumentation")
def task_instrumentation_fixture(node_name_for_file: str, test_time_for_file: str) -> Iterator[None]:
    target_directory = f"task-profile-{node_name_for_file}-{test_time_for_file}"

    start_task_instrumentation()
    yield
    stop_task_instrumentation(target_dir=target_directory)
    task_instrumentation_main(args=[target_directory])


@pytest.fixture(scope="session")
def get_keychain():
    with TempKeyring() as keychain:
        yield keychain
        KeyringWrapper.cleanup_shared_instance()


class ConsensusMode(Enum):
    PLAIN = 0
    HARD_FORK_2_0 = 1
    SOFT_FORK3 = 2


@pytest.fixture(
    scope="session",
    params=[ConsensusMode.PLAIN, ConsensusMode.HARD_FORK_2_0, ConsensusMode.SOFT_FORK3],
)
def consensus_mode(request):
    return request.param


@pytest.fixture(scope="session")
def blockchain_constants(consensus_mode) -> ConsensusConstants:
    if consensus_mode == ConsensusMode.PLAIN:
        return test_constants
    if consensus_mode == ConsensusMode.SOFT_FORK3:
        return dataclasses.replace(test_constants, SOFT_FORK3_HEIGHT=uint32(3))
    if consensus_mode == ConsensusMode.HARD_FORK_2_0:
        return dataclasses.replace(
            test_constants,
            HARD_FORK_HEIGHT=uint32(2),
            HARD_FORK_FIX_HEIGHT=uint32(2),
            PLOT_FILTER_128_HEIGHT=uint32(10),
            PLOT_FILTER_64_HEIGHT=uint32(15),
            PLOT_FILTER_32_HEIGHT=uint32(20),
        )
    raise AssertionError("Invalid Blockchain mode in simulation")


@pytest.fixture(scope="session", name="bt")
def block_tools_fixture(get_keychain, blockchain_constants) -> BlockTools:
    # Note that this causes a lot of CPU and disk traffic - disk, DB, ports, process creation ...
    _shared_block_tools = create_block_tools(constants=blockchain_constants, keychain=get_keychain)
    return _shared_block_tools


# if you have a system that has an unusual hostname for localhost and you want
# to run the tests, change the `self_hostname` fixture
@pytest_asyncio.fixture(scope="session")
def self_hostname():
    return "127.0.0.1"


# NOTE:
#       Instantiating the bt fixture results in an attempt to create the chia root directory
#       which the build scripts symlink to a sometimes-not-there directory.
#       When not there, Python complains since, well, the symlink is not a directory nor points to a directory.
#
#       Now that we have removed the global at tests.setup_nodes.bt, we can move the imports out of
#       the fixtures below. Just be aware of the filesystem modification during bt fixture creation


@pytest_asyncio.fixture(scope="function")
async def empty_blockchain(latest_db_version, blockchain_constants):
    """
    Provides a list of 10 valid blocks, as well as a blockchain with 9 blocks added to it.
    """
    from tests.util.blockchain import create_blockchain

    bc1, db_wrapper, db_path = await create_blockchain(blockchain_constants, latest_db_version)
    yield bc1

    await db_wrapper.close()
    bc1.shut_down()
    db_path.unlink()


@pytest.fixture(scope="function")
def latest_db_version() -> int:
    return 2


@pytest.fixture(scope="function", params=[2])
def db_version(request) -> int:
    return request.param


SOFTFORK_HEIGHTS = [1000000, 4510000, 5496000, 5496100]


@pytest.fixture(scope="function", params=SOFTFORK_HEIGHTS)
def softfork_height(request) -> int:
    return request.param


saved_blocks_version = "rc5"


@pytest.fixture(scope="session")
def default_400_blocks(bt, consensus_mode):
    version = ""
    if consensus_mode == ConsensusMode.HARD_FORK_2_0:
        version = "_hardfork"

    from tests.util.blockchain import persistent_blocks

    return persistent_blocks(400, f"test_blocks_400_{saved_blocks_version}{version}.db", bt, seed=b"400")


@pytest.fixture(scope="session")
def default_1000_blocks(bt, consensus_mode):
    version = ""
    if consensus_mode == ConsensusMode.HARD_FORK_2_0:
        version = "_hardfork"

    from tests.util.blockchain import persistent_blocks

    return persistent_blocks(1000, f"test_blocks_1000_{saved_blocks_version}{version}.db", bt, seed=b"1000")


@pytest.fixture(scope="session")
def pre_genesis_empty_slots_1000_blocks(bt, consensus_mode):
    version = ""
    if consensus_mode == ConsensusMode.HARD_FORK_2_0:
        version = "_hardfork"

    from tests.util.blockchain import persistent_blocks

    return persistent_blocks(
        1000,
        f"pre_genesis_empty_slots_1000_blocks{saved_blocks_version}{version}.db",
        bt,
        seed=b"empty_slots",
        empty_sub_slots=1,
    )


@pytest.fixture(scope="session")
def default_1500_blocks(bt, consensus_mode):
    version = ""
    if consensus_mode == ConsensusMode.HARD_FORK_2_0:
        version = "_hardfork"

    from tests.util.blockchain import persistent_blocks

    return persistent_blocks(1500, f"test_blocks_1500_{saved_blocks_version}{version}.db", bt, seed=b"1500")


@pytest.fixture(scope="session")
def default_10000_blocks(bt, consensus_mode):
    from tests.util.blockchain import persistent_blocks

    version = ""
    if consensus_mode == ConsensusMode.HARD_FORK_2_0:
        version = "_hardfork"

    return persistent_blocks(10000, f"test_blocks_10000_{saved_blocks_version}{version}.db", bt, seed=b"10000")


@pytest.fixture(scope="session")
def test_long_reorg_blocks(bt, consensus_mode, default_1500_blocks):
    version = ""
    if consensus_mode == ConsensusMode.HARD_FORK_2_0:
        version = "_hardfork"

    from tests.util.blockchain import persistent_blocks

    return persistent_blocks(
        758,
        f"test_blocks_long_reorg_{saved_blocks_version}{version}.db",
        bt,
        block_list_input=default_1500_blocks[:320],
        seed=b"reorg_blocks",
        time_per_block=8,
    )


@pytest.fixture(scope="session")
def default_2000_blocks_compact(bt, consensus_mode):
    version = ""
    if consensus_mode == ConsensusMode.HARD_FORK_2_0:
        version = "_hardfork"

    from tests.util.blockchain import persistent_blocks

    return persistent_blocks(
        2000,
        f"test_blocks_2000_compact_{saved_blocks_version}{version}.db",
        bt,
        normalized_to_identity_cc_eos=True,
        normalized_to_identity_icc_eos=True,
        normalized_to_identity_cc_ip=True,
        normalized_to_identity_cc_sp=True,
        seed=b"2000_compact",
    )


@pytest.fixture(scope="session")
def default_10000_blocks_compact(bt, consensus_mode):
    from tests.util.blockchain import persistent_blocks

    version = ""
    if consensus_mode == ConsensusMode.HARD_FORK_2_0:
        version = "_hardfork"

    return persistent_blocks(
        10000,
        f"test_blocks_10000_compact_{saved_blocks_version}{version}.db",
        bt,
        normalized_to_identity_cc_eos=True,
        normalized_to_identity_icc_eos=True,
        normalized_to_identity_cc_ip=True,
        normalized_to_identity_cc_sp=True,
        seed=b"1000_compact",
    )


@pytest.fixture(scope="function")
def tmp_dir():
    with tempfile.TemporaryDirectory() as folder:
        yield Path(folder)


# For the below see https://stackoverflow.com/a/62563106/15133773
if os.getenv("_PYTEST_RAISE", "0") != "0":

    @pytest.hookimpl(tryfirst=True)
    def pytest_exception_interact(call):
        raise call.excinfo.value

    @pytest.hookimpl(tryfirst=True)
    def pytest_internalerror(excinfo):
        raise excinfo.value


def pytest_configure(config):
    config.addinivalue_line("markers", "benchmark: automatically assigned by the benchmark_runner fixture")


def pytest_collection_modifyitems(session, config: pytest.Config, items: List[pytest.Function]):
    # https://github.com/pytest-dev/pytest/issues/3730#issuecomment-567142496
    removed = []
    kept = []
    all_error_lines: List[str] = []
    limit_consensus_modes_problems: List[str] = []
    for item in items:
        limit_consensus_modes_marker = item.get_closest_marker("limit_consensus_modes")
        if limit_consensus_modes_marker is not None:
            callspec = getattr(item, "callspec", None)
            if callspec is None:
                limit_consensus_modes_problems.append(item.name)
                continue

            mode = callspec.params.get("consensus_mode")
            if mode is None:
                limit_consensus_modes_problems.append(item.name)
                continue

            modes = limit_consensus_modes_marker.kwargs.get("allowed", [ConsensusMode.PLAIN])
            if mode not in modes:
                removed.append(item)
                continue

        kept.append(item)
    if removed:
        config.hook.pytest_deselected(items=removed)
        items[:] = kept

    if len(limit_consensus_modes_problems) > 0:
        all_error_lines.append("@pytest.mark.limit_consensus_modes used without consensus_mode:")
        all_error_lines.extend(f"    {line}" for line in limit_consensus_modes_problems)

    benchmark_problems: List[str] = []
    for item in items:
        existing_benchmark_mark = item.get_closest_marker("benchmark")
        if existing_benchmark_mark is not None:
            benchmark_problems.append(item.name)

        if "benchmark_runner" in getattr(item, "fixturenames", ()):
            item.add_marker("benchmark")

    if len(benchmark_problems) > 0:
        all_error_lines.append("use the benchmark_runner fixture, not @pytest.mark.benchmark:")
        all_error_lines.extend(f"    {line}" for line in benchmark_problems)

    if len(all_error_lines) > 0:
        all_error_lines.insert(0, "custom chia collection rules failed")
        raise Exception("\n".join(all_error_lines))


@pytest_asyncio.fixture(scope="function")
async def node_with_params(request, blockchain_constants: ConsensusConstants):
    params = {}
    if request:
        params = request.param
    async with setup_simulators_and_wallets(1, 0, blockchain_constants, **params) as (sims, wallets, bt):
        yield sims[0]


@pytest_asyncio.fixture(scope="function")
async def two_nodes(db_version: int, self_hostname, blockchain_constants: ConsensusConstants):
    async with setup_two_nodes(blockchain_constants, db_version=db_version, self_hostname=self_hostname) as _:
        yield _


@pytest_asyncio.fixture(scope="function")
async def setup_two_nodes_fixture(db_version: int, blockchain_constants: ConsensusConstants):
    async with setup_simulators_and_wallets(2, 0, blockchain_constants, db_version=db_version) as _:
        yield _


@pytest_asyncio.fixture(scope="function")
async def three_nodes(db_version: int, self_hostname, blockchain_constants):
    async with setup_n_nodes(blockchain_constants, 3, db_version=db_version, self_hostname=self_hostname) as _:
        yield _


@pytest_asyncio.fixture(scope="function")
async def five_nodes(db_version: int, self_hostname, blockchain_constants):
    async with setup_n_nodes(blockchain_constants, 5, db_version=db_version, self_hostname=self_hostname) as _:
        yield _


@pytest_asyncio.fixture(scope="function")
async def wallet_nodes(blockchain_constants, consensus_mode):
    constants = blockchain_constants
    async with setup_simulators_and_wallets(
        2,
        1,
        dataclasses.replace(blockchain_constants, MEMPOOL_BLOCK_BUFFER=1, MAX_BLOCK_COST_CLVM=400000000),
    ) as (nodes, wallets, bt):
        full_node_1 = nodes[0]
        full_node_2 = nodes[1]
        server_1 = full_node_1.full_node.server
        server_2 = full_node_2.full_node.server
        wallet_a = bt.get_pool_wallet_tool()
        wallet_receiver = WalletTool(full_node_1.full_node.constants)
        yield full_node_1, full_node_2, server_1, server_2, wallet_a, wallet_receiver, bt


@pytest_asyncio.fixture(scope="function")
async def setup_four_nodes(db_version, blockchain_constants: ConsensusConstants):
    async with setup_simulators_and_wallets(4, 0, blockchain_constants, db_version=db_version) as _:
        yield _


@pytest_asyncio.fixture(scope="function")
async def two_nodes_sim_and_wallets_services(blockchain_constants, consensus_mode):
    async with setup_simulators_and_wallets_service(2, 0, blockchain_constants) as _:
        yield _


@pytest_asyncio.fixture(scope="function")
async def one_wallet_and_one_simulator_services(blockchain_constants: ConsensusConstants):
    async with setup_simulators_and_wallets_service(1, 1, blockchain_constants) as _:
        yield _


@pytest_asyncio.fixture(scope="function")
async def wallet_node_100_pk(blockchain_constants: ConsensusConstants):
    async with setup_simulators_and_wallets(1, 1, blockchain_constants, initial_num_public_keys=100) as _:
        yield _


@pytest_asyncio.fixture(scope="function")
async def simulator_and_wallet(
    blockchain_constants: ConsensusConstants,
) -> AsyncIterator[Tuple[List[FullNodeSimulator], List[Tuple[WalletNode, ChiaServer]], BlockTools]]:
    async with setup_simulators_and_wallets(1, 1, blockchain_constants) as _:
        yield _


@pytest_asyncio.fixture(scope="function")
async def two_wallet_nodes(request, blockchain_constants: ConsensusConstants):
    params = {}
    if request and request.param_index > 0:
        params = request.param
    async with setup_simulators_and_wallets(1, 2, blockchain_constants, **params) as _:
        yield _


@pytest_asyncio.fixture(scope="function")
async def two_wallet_nodes_services(
    blockchain_constants: ConsensusConstants,
) -> AsyncIterator[
    Tuple[List[Service[FullNode, FullNodeSimulator]], List[Service[WalletNode, WalletNodeAPI]], BlockTools]
]:
    async with setup_simulators_and_wallets_service(1, 2, blockchain_constants) as _:
        yield _


@pytest_asyncio.fixture(scope="function")
async def two_wallet_nodes_custom_spam_filtering(
    spam_filter_after_n_txs, xch_spam_amount, blockchain_constants: ConsensusConstants
):
    async with setup_simulators_and_wallets(1, 2, blockchain_constants, spam_filter_after_n_txs, xch_spam_amount) as _:
        yield _


@pytest_asyncio.fixture(scope="function")
async def three_sim_two_wallets(blockchain_constants: ConsensusConstants):
    async with setup_simulators_and_wallets(3, 2, blockchain_constants) as _:
        yield _


@pytest_asyncio.fixture(scope="function")
async def setup_two_nodes_and_wallet(blockchain_constants: ConsensusConstants):
    async with setup_simulators_and_wallets(2, 1, blockchain_constants, db_version=2) as _:
        yield _


@pytest_asyncio.fixture(scope="function")
async def setup_two_nodes_and_wallet_fast_retry(blockchain_constants: ConsensusConstants):
    async with setup_simulators_and_wallets(
        1, 1, blockchain_constants, config_overrides={"wallet.tx_resend_timeout_secs": 1}, db_version=2
    ) as _:
        yield _


@pytest_asyncio.fixture(scope="function")
async def three_wallet_nodes(blockchain_constants: ConsensusConstants):
    async with setup_simulators_and_wallets(1, 3, blockchain_constants) as _:
        yield _


@pytest_asyncio.fixture(scope="function")
async def wallet_two_node_simulator(blockchain_constants: ConsensusConstants):
    async with setup_simulators_and_wallets(2, 1, blockchain_constants) as _:
        yield _


@pytest_asyncio.fixture(scope="function")
async def wallet_nodes_mempool_perf(bt):
    key_seed = bt.farmer_master_sk_entropy
    async with setup_simulators_and_wallets(2, 1, bt.constants, key_seed=key_seed) as _:
        yield _


@pytest_asyncio.fixture(scope="function")
async def two_nodes_two_wallets_with_same_keys(bt) -> AsyncIterator[SimulatorsAndWallets]:
    key_seed = bt.farmer_master_sk_entropy
    async with setup_simulators_and_wallets(2, 2, bt.constants, key_seed=key_seed) as _:
        yield _


@pytest_asyncio.fixture(scope="module")
async def wallet_nodes_perf(blockchain_constants: ConsensusConstants):
    async with setup_simulators_and_wallets(
        1, 1, blockchain_constants, config_overrides={"MEMPOOL_BLOCK_BUFFER": 1, "MAX_BLOCK_COST_CLVM": 11000000000}
    ) as (
        nodes,
        wallets,
        bt,
    ):
        full_node_1 = nodes[0]
        server_1 = full_node_1.full_node.server
        wallet_a = bt.get_pool_wallet_tool()
        wallet_receiver = WalletTool(full_node_1.full_node.constants)
        yield full_node_1, server_1, wallet_a, wallet_receiver, bt


@pytest_asyncio.fixture(scope="function")
async def three_nodes_two_wallets(blockchain_constants: ConsensusConstants):
    async with setup_simulators_and_wallets(3, 2, blockchain_constants) as _:
        yield _


@pytest_asyncio.fixture(scope="function")
async def one_node(
    blockchain_constants: ConsensusConstants,
) -> AsyncIterator[Tuple[List[Service], List[FullNodeSimulator], BlockTools]]:
    async with setup_simulators_and_wallets_service(1, 0, blockchain_constants) as _:
        yield _


@pytest_asyncio.fixture(scope="function")
async def one_node_one_block(
    blockchain_constants: ConsensusConstants,
) -> AsyncIterator[Tuple[Union[FullNodeAPI, FullNodeSimulator], ChiaServer, BlockTools]]:
    async with setup_simulators_and_wallets(1, 0, blockchain_constants) as (nodes, _, bt):
        full_node_1 = nodes[0]
        server_1 = full_node_1.full_node.server
        wallet_a = bt.get_pool_wallet_tool()

        reward_ph = wallet_a.get_new_puzzlehash()
        blocks = bt.get_consecutive_blocks(
            1,
            guarantee_transaction_block=True,
            farmer_reward_puzzle_hash=reward_ph,
            pool_reward_puzzle_hash=reward_ph,
            genesis_timestamp=uint64(10000),
            time_per_block=10,
        )
        assert blocks[0].height == 0

        for block in blocks:
            await full_node_1.full_node.add_block(block)

        await time_out_assert(60, node_height_at_least, True, full_node_1, blocks[-1].height)

        yield full_node_1, server_1, bt


@pytest_asyncio.fixture(scope="function")
async def two_nodes_one_block(blockchain_constants: ConsensusConstants):
    async with setup_simulators_and_wallets(2, 0, blockchain_constants) as (nodes, _, bt):
        full_node_1 = nodes[0]
        full_node_2 = nodes[1]
        server_1 = full_node_1.full_node.server
        server_2 = full_node_2.full_node.server
        wallet_a = bt.get_pool_wallet_tool()

        reward_ph = wallet_a.get_new_puzzlehash()
        blocks = bt.get_consecutive_blocks(
            1,
            guarantee_transaction_block=True,
            farmer_reward_puzzle_hash=reward_ph,
            pool_reward_puzzle_hash=reward_ph,
            genesis_timestamp=uint64(10000),
            time_per_block=10,
        )
        assert blocks[0].height == 0

        for block in blocks:
            await full_node_1.full_node.add_block(block)

        await time_out_assert(60, node_height_at_least, True, full_node_1, blocks[-1].height)

        yield full_node_1, full_node_2, server_1, server_2, bt


@pytest_asyncio.fixture(scope="function")
async def farmer_one_harvester_simulator_wallet(
    tmp_path: Path,
    blockchain_constants: ConsensusConstants,
) -> AsyncIterator[
    Tuple[
        Service[Harvester, HarvesterAPI],
        Service[Farmer, FarmerAPI],
        Service[FullNode, FullNodeSimulator],
        Service[WalletNode, WalletNodeAPI],
        BlockTools,
    ]
]:
    async with setup_simulators_and_wallets_service(1, 1, blockchain_constants) as (nodes, wallets, bt):
        async with setup_farmer_multi_harvester(bt, 1, tmp_path, bt.constants, start_services=True) as (
            harvester_services,
            farmer_service,
            _,
        ):
            yield harvester_services[0], farmer_service, nodes[0], wallets[0], bt


FarmerOneHarvester = Tuple[List[Service[Harvester, HarvesterAPI]], Service[Farmer, FarmerAPI], BlockTools]


@pytest_asyncio.fixture(scope="function")
async def farmer_one_harvester(tmp_path: Path, get_b_tools: BlockTools) -> AsyncIterator[FarmerOneHarvester]:
    async with setup_farmer_multi_harvester(get_b_tools, 1, tmp_path, get_b_tools.constants, start_services=True) as _:
        yield _


@pytest_asyncio.fixture(scope="function")
async def farmer_one_harvester_not_started(
    tmp_path: Path, get_b_tools: BlockTools
) -> AsyncIterator[Tuple[List[Service], Service]]:
    async with setup_farmer_multi_harvester(get_b_tools, 1, tmp_path, get_b_tools.constants, start_services=False) as _:
        yield _


@pytest_asyncio.fixture(scope="function")
async def farmer_two_harvester_not_started(
    tmp_path: Path, get_b_tools: BlockTools
) -> AsyncIterator[Tuple[List[Service], Service]]:
    async with setup_farmer_multi_harvester(get_b_tools, 2, tmp_path, get_b_tools.constants, start_services=False) as _:
        yield _


@pytest_asyncio.fixture(scope="function")
async def farmer_three_harvester_not_started(
    tmp_path: Path, get_b_tools: BlockTools
) -> AsyncIterator[Tuple[List[Service], Service]]:
    async with setup_farmer_multi_harvester(get_b_tools, 3, tmp_path, get_b_tools.constants, start_services=False) as _:
        yield _


@pytest_asyncio.fixture(scope="function")
async def get_daemon(bt):
    async with setup_daemon(btools=bt) as _:
        yield _


@pytest.fixture(scope="function")
def empty_keyring():
    with TempKeyring(user="user-chia-1.8", service="chia-user-chia-1.8") as keychain:
        yield keychain
        KeyringWrapper.cleanup_shared_instance()


@pytest_asyncio.fixture(scope="function")
async def get_temp_keyring():
    with TempKeyring() as keychain:
        yield keychain


@pytest_asyncio.fixture(scope="function")
async def get_b_tools_1(get_temp_keyring):
    return await create_block_tools_async(constants=test_constants_modified, keychain=get_temp_keyring)


@pytest_asyncio.fixture(scope="function")
async def get_b_tools(get_temp_keyring):
    local_b_tools = await create_block_tools_async(constants=test_constants_modified, keychain=get_temp_keyring)
    new_config = local_b_tools._config
    local_b_tools.change_config(new_config)
    return local_b_tools


@pytest_asyncio.fixture(scope="function")
async def daemon_connection_and_temp_keychain(
    get_b_tools: BlockTools,
) -> AsyncIterator[Tuple[aiohttp.ClientWebSocketResponse, Keychain]]:
    async with setup_daemon(btools=get_b_tools) as daemon:
        keychain = daemon.keychain_server._default_keychain
        async with aiohttp.ClientSession() as session:
            async with session.ws_connect(
                f"wss://127.0.0.1:{get_b_tools._config['daemon_port']}",
                autoclose=True,
                autoping=True,
                ssl=get_b_tools.get_daemon_ssl_context(),
                max_msg_size=52428800,
            ) as ws:
                yield ws, keychain


@pytest_asyncio.fixture(scope="function")
async def wallets_prefarm_services(two_wallet_nodes_services, self_hostname, trusted, request):
    """
    Sets up the node with 10 blocks, and returns a payer and payee wallet.
    """
    try:
        farm_blocks = request.param
    except AttributeError:
        farm_blocks = 3
    buffer = 1
    full_nodes, wallets, bt = two_wallet_nodes_services
    full_node_api = full_nodes[0]._api
    full_node_server = full_node_api.server
    wallet_service_0 = wallets[0]
    wallet_service_1 = wallets[1]
    wallet_node_0 = wallet_service_0._node
    wallet_node_1 = wallet_service_1._node
    wallet_0 = wallet_node_0.wallet_state_manager.main_wallet
    wallet_1 = wallet_node_1.wallet_state_manager.main_wallet

    if trusted:
        wallet_node_0.config["trusted_peers"] = {full_node_server.node_id.hex(): full_node_server.node_id.hex()}
        wallet_node_1.config["trusted_peers"] = {full_node_server.node_id.hex(): full_node_server.node_id.hex()}
    else:
        wallet_node_0.config["trusted_peers"] = {}
        wallet_node_1.config["trusted_peers"] = {}

    wallet_0_rpc_client = await WalletRpcClient.create(
        bt.config["self_hostname"],
        wallet_service_0.rpc_server.listen_port,
        wallet_service_0.root_path,
        wallet_service_0.config,
    )
    wallet_1_rpc_client = await WalletRpcClient.create(
        bt.config["self_hostname"],
        wallet_service_1.rpc_server.listen_port,
        wallet_service_1.root_path,
        wallet_service_1.config,
    )

    await wallet_node_0.server.start_client(PeerInfo(self_hostname, full_node_server.get_port()), None)
    await wallet_node_1.server.start_client(PeerInfo(self_hostname, full_node_server.get_port()), None)

    wallet_0_rewards = await full_node_api.farm_blocks_to_wallet(count=farm_blocks, wallet=wallet_0)
    wallet_1_rewards = await full_node_api.farm_blocks_to_wallet(count=farm_blocks, wallet=wallet_1)
    await full_node_api.farm_blocks_to_puzzlehash(count=buffer, guarantee_transaction_blocks=True)

    await full_node_api.wait_for_wallets_synced(wallet_nodes=[wallet_node_0, wallet_node_1], timeout=30)

    assert await wallet_0.get_confirmed_balance() == wallet_0_rewards
    assert await wallet_0.get_unconfirmed_balance() == wallet_0_rewards
    assert await wallet_1.get_confirmed_balance() == wallet_1_rewards
    assert await wallet_1.get_unconfirmed_balance() == wallet_1_rewards

    return (
        (wallet_node_0, wallet_0_rewards),
        (wallet_node_1, wallet_1_rewards),
        (wallet_0_rpc_client, wallet_1_rpc_client),
        (wallet_service_0, wallet_service_1),
        full_node_api,
    )


@pytest_asyncio.fixture(scope="function")
async def wallets_prefarm(wallets_prefarm_services):
    return wallets_prefarm_services[0], wallets_prefarm_services[1], wallets_prefarm_services[4]


@pytest_asyncio.fixture(scope="function")
async def three_wallets_prefarm(three_wallet_nodes, self_hostname, trusted):
    """
    Sets up the node with 10 blocks, and returns a payer and payee wallet.
    """
    farm_blocks = 3
    buffer = 1
    full_nodes, wallets, _ = three_wallet_nodes
    full_node_api = full_nodes[0]
    full_node_server = full_node_api.server
    wallet_node_0, wallet_server_0 = wallets[0]
    wallet_node_1, wallet_server_1 = wallets[1]
    wallet_node_2, wallet_server_2 = wallets[2]
    wallet_0 = wallet_node_0.wallet_state_manager.main_wallet
    wallet_1 = wallet_node_1.wallet_state_manager.main_wallet
    wallet_2 = wallet_node_2.wallet_state_manager.main_wallet

    if trusted:
        wallet_node_0.config["trusted_peers"] = {full_node_server.node_id.hex(): full_node_server.node_id.hex()}
        wallet_node_1.config["trusted_peers"] = {full_node_server.node_id.hex(): full_node_server.node_id.hex()}
        wallet_node_2.config["trusted_peers"] = {full_node_server.node_id.hex(): full_node_server.node_id.hex()}
    else:
        wallet_node_0.config["trusted_peers"] = {}
        wallet_node_1.config["trusted_peers"] = {}
        wallet_node_2.config["trusted_peers"] = {}

    await wallet_server_0.start_client(PeerInfo(self_hostname, full_node_server.get_port()), None)
    await wallet_server_1.start_client(PeerInfo(self_hostname, full_node_server.get_port()), None)
    await wallet_server_2.start_client(PeerInfo(self_hostname, full_node_server.get_port()), None)

    wallet_0_rewards = await full_node_api.farm_blocks_to_wallet(count=farm_blocks, wallet=wallet_0)
    wallet_1_rewards = await full_node_api.farm_blocks_to_wallet(count=farm_blocks, wallet=wallet_1)
    wallet_2_rewards = await full_node_api.farm_blocks_to_wallet(count=farm_blocks, wallet=wallet_2)
    await full_node_api.farm_blocks_to_puzzlehash(count=buffer, guarantee_transaction_blocks=True)

    await full_node_api.wait_for_wallets_synced(wallet_nodes=[wallet_node_0, wallet_node_1], timeout=30)

    assert await wallet_0.get_confirmed_balance() == wallet_0_rewards
    assert await wallet_0.get_unconfirmed_balance() == wallet_0_rewards
    assert await wallet_1.get_confirmed_balance() == wallet_1_rewards
    assert await wallet_1.get_unconfirmed_balance() == wallet_1_rewards
    assert await wallet_2.get_confirmed_balance() == wallet_2_rewards
    assert await wallet_2.get_unconfirmed_balance() == wallet_2_rewards

    return (
        (wallet_node_0, wallet_0_rewards),
        (wallet_node_1, wallet_1_rewards),
        (wallet_node_2, wallet_2_rewards),
        full_node_api,
    )


@pytest_asyncio.fixture(scope="function")
async def introducer_service(bt):
    async with setup_introducer(bt, 0) as _:
        yield _


@pytest_asyncio.fixture(scope="function")
async def timelord(bt):
    async with setup_timelord(uint16(0), False, bt.constants, bt.config, bt.root_path) as service:
        yield service._api, service._node.server


@pytest_asyncio.fixture(scope="function")
async def timelord_service(bt: BlockTools) -> AsyncIterator[Service[Timelord, TimelordAPI]]:
    async with setup_timelord(uint16(0), False, bt.constants, bt.config, bt.root_path) as _:
        yield _


@pytest_asyncio.fixture(scope="function")
async def crawler_service(
    root_path_populated_with_config: Path, database_uri: str
) -> AsyncIterator[Service[Crawler, CrawlerAPI]]:
    async with setup_crawler(root_path_populated_with_config, database_uri) as service:
        yield service


@pytest_asyncio.fixture(scope="function")
async def seeder_service(root_path_populated_with_config: Path, database_uri: str) -> AsyncIterator[DNSServer]:
    async with setup_seeder(root_path_populated_with_config, database_uri) as seeder:
        yield seeder


@pytest.fixture(scope="function")
def tmp_chia_root(tmp_path):
    """
    Create a temp directory and populate it with an empty chia_root directory.
    """
    path: Path = tmp_path / "chia_root"
    path.mkdir(parents=True, exist_ok=True)
    return path


@pytest.fixture(scope="function")
def root_path_populated_with_config(tmp_chia_root) -> Path:
    """
    Create a temp chia_root directory and populate it with a default config.yaml.
    Returns the chia_root path.
    """
    root_path: Path = tmp_chia_root
    create_default_chia_config(root_path)
    return root_path


@pytest.fixture(scope="function")
def config(root_path_populated_with_config: Path) -> Dict[str, Any]:
    with lock_and_load_config(root_path_populated_with_config, "config.yaml") as config:
        return config


@pytest.fixture(scope="function")
def config_with_address_prefix(root_path_populated_with_config: Path, prefix: str) -> Dict[str, Any]:
    with lock_and_load_config(root_path_populated_with_config, "config.yaml") as config:
        if prefix is not None:
            config["network_overrides"]["config"][config["selected_network"]]["address_prefix"] = prefix
    return config


@pytest.fixture(name="scripts_path", scope="session")
def scripts_path_fixture() -> Path:
    scripts_string = sysconfig.get_path("scripts")
    if scripts_string is None:
        raise Exception("These tests depend on the scripts path existing")

    return Path(scripts_string)


@pytest.fixture(name="chia_root", scope="function")
def chia_root_fixture(tmp_path: Path, scripts_path: Path) -> ChiaRoot:
    root = ChiaRoot(path=tmp_path.joinpath("chia_root"), scripts_path=scripts_path)
    root.run(args=["init"])
    root.run(args=["configure", "--set-log-level", "INFO"])

    return root


@pytest.fixture(name="cost_logger", scope="session")
def cost_logger_fixture() -> Iterator[CostLogger]:
    cost_logger = CostLogger()
    yield cost_logger
    print()
    print()
    print(cost_logger.log_cost_statistics())


@pytest_asyncio.fixture(scope="function")
async def simulation(bt, get_b_tools):
    async with setup_full_system(test_constants_modified, bt, get_b_tools, db_version=2) as full_system:
        yield full_system, get_b_tools


HarvesterFarmerEnvironment = Tuple[
    Service[Farmer, FarmerAPI], FarmerRpcClient, Service[Harvester, HarvesterAPI], HarvesterRpcClient, BlockTools
]


@pytest_asyncio.fixture(scope="function")
async def harvester_farmer_environment(
    farmer_one_harvester: Tuple[List[Service[Harvester, HarvesterAPI]], Service[Farmer, FarmerAPI], BlockTools],
    self_hostname: str,
) -> AsyncIterator[HarvesterFarmerEnvironment]:
    harvesters, farmer_service, bt = farmer_one_harvester
    harvester_service = harvesters[0]

    assert farmer_service.rpc_server is not None
    farmer_rpc_cl = await FarmerRpcClient.create(
        self_hostname, farmer_service.rpc_server.listen_port, farmer_service.root_path, farmer_service.config
    )
    assert harvester_service.rpc_server is not None
    harvester_rpc_cl = await HarvesterRpcClient.create(
        self_hostname, harvester_service.rpc_server.listen_port, harvester_service.root_path, harvester_service.config
    )

    async def have_connections() -> bool:
        return len(await farmer_rpc_cl.get_connections()) > 0

    await time_out_assert(15, have_connections, True)

    yield farmer_service, farmer_rpc_cl, harvester_service, harvester_rpc_cl, bt

    farmer_rpc_cl.close()
    harvester_rpc_cl.close()
    await farmer_rpc_cl.await_closed()
    await harvester_rpc_cl.await_closed()


@pytest.fixture(name="database_uri")
def database_uri_fixture() -> str:
    return f"file:db_{random.randint(0, 99999999)}?mode=memory&cache=shared"


@pytest.fixture(name="empty_temp_file_keyring")
def empty_temp_file_keyring_fixture() -> Iterator[TempKeyring]:
    with TempKeyring(populate=False) as keyring:
        yield keyring


@pytest.fixture(name="populated_temp_file_keyring")
def populated_temp_file_keyring_fixture() -> Iterator[TempKeyring]:
    """Populated with a payload containing 0 keys using the default passphrase."""
    with TempKeyring(populate=True) as keyring:
        yield keyring
