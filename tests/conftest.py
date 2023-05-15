# flake8: noqa E402 # See imports after multiprocessing.set_start_method
from __future__ import annotations

import datetime
import multiprocessing
import os
import sysconfig
import tempfile
from typing import Any, AsyncIterator, Dict, Iterator, List, Tuple, Union

import aiohttp
import pytest
import pytest_asyncio

# TODO: update after resolution in https://github.com/pytest-dev/pytest/issues/7469
from _pytest.fixtures import SubRequest

# Set spawn after stdlib imports, but before other imports
from chia.clvm.spend_sim import CostLogger
from chia.full_node.full_node import FullNode
from chia.full_node.full_node_api import FullNodeAPI
from chia.protocols import full_node_protocol
from chia.server.server import ChiaServer
from chia.server.start_service import Service
from chia.simulator.full_node_simulator import FullNodeSimulator
from chia.simulator.setup_nodes import (
    SimulatorsAndWallets,
    setup_full_system_connect_to_deamon,
    setup_n_nodes,
    setup_simulators_and_wallets,
    setup_simulators_and_wallets_service,
    setup_two_nodes,
)
from chia.simulator.setup_services import setup_daemon, setup_introducer, setup_timelord
from chia.simulator.time_out_assert import time_out_assert
from chia.simulator.wallet_tools import WalletTool
from chia.types.peer_info import PeerInfo
from chia.util.config import create_default_chia_config, lock_and_load_config
from chia.util.ints import uint16, uint64
from chia.util.keychain import Keychain
from chia.util.task_timing import main as task_instrumentation_main
from chia.util.task_timing import start_task_instrumentation, stop_task_instrumentation
from chia.wallet.wallet import Wallet
from chia.wallet.wallet_node import WalletNode
from tests.core.data_layer.util import ChiaRoot
from tests.core.node_height import node_height_at_least
from tests.simulation.test_simulation import test_constants_modified

multiprocessing.set_start_method("spawn")

from pathlib import Path

from chia.simulator.block_tools import BlockTools, create_block_tools, create_block_tools_async, test_constants
from chia.simulator.keyring import TempKeyring
from chia.simulator.setup_nodes import setup_farmer_multi_harvester
from chia.util.keyring_wrapper import KeyringWrapper


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


@pytest.fixture(scope="session", name="bt")
def block_tools_fixture(get_keychain) -> BlockTools:
    # Note that this causes a lot of CPU and disk traffic - disk, DB, ports, process creation ...
    _shared_block_tools = create_block_tools(constants=test_constants, keychain=get_keychain)
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


@pytest_asyncio.fixture(scope="function", params=[1, 2])
async def empty_blockchain(request):
    """
    Provides a list of 10 valid blocks, as well as a blockchain with 9 blocks added to it.
    """
    from chia.simulator.setup_nodes import test_constants
    from tests.util.blockchain import create_blockchain

    bc1, db_wrapper, db_path = await create_blockchain(test_constants, request.param)
    yield bc1

    await db_wrapper.close()
    bc1.shut_down()
    db_path.unlink()


@pytest.fixture(scope="function")
def latest_db_version() -> int:
    return 2


@pytest.fixture(scope="function", params=[1, 2])
def db_version(request) -> int:
    return request.param


@pytest.fixture(scope="function", params=[1000000, 3630000, 3886635])
def softfork_height(request) -> int:
    return request.param


saved_blocks_version = "rc5"


@pytest.fixture(scope="session")
def default_400_blocks(bt):
    from tests.util.blockchain import persistent_blocks

    return persistent_blocks(400, f"test_blocks_400_{saved_blocks_version}.db", bt, seed=b"400")


@pytest.fixture(scope="session")
def default_1000_blocks(bt):
    from tests.util.blockchain import persistent_blocks

    return persistent_blocks(1000, f"test_blocks_1000_{saved_blocks_version}.db", bt, seed=b"1000")


@pytest.fixture(scope="session")
def pre_genesis_empty_slots_1000_blocks(bt):
    from tests.util.blockchain import persistent_blocks

    return persistent_blocks(
        1000,
        f"pre_genesis_empty_slots_1000_blocks{saved_blocks_version}.db",
        bt,
        seed=b"empty_slots",
        empty_sub_slots=1,
    )


@pytest.fixture(scope="session")
def default_1500_blocks(bt):
    from tests.util.blockchain import persistent_blocks

    return persistent_blocks(1500, f"test_blocks_1500_{saved_blocks_version}.db", bt, seed=b"1500")


@pytest.fixture(scope="session")
def default_10000_blocks(bt):
    from tests.util.blockchain import persistent_blocks

    return persistent_blocks(10000, f"test_blocks_10000_{saved_blocks_version}.db", bt, seed=b"10000")


@pytest.fixture(scope="session")
def default_20000_blocks(bt):
    from tests.util.blockchain import persistent_blocks

    return persistent_blocks(20000, f"test_blocks_20000_{saved_blocks_version}.db", bt, seed=b"20000")


@pytest.fixture(scope="session")
def test_long_reorg_blocks(bt, default_1500_blocks):
    from tests.util.blockchain import persistent_blocks

    return persistent_blocks(
        758,
        f"test_blocks_long_reorg_{saved_blocks_version}.db",
        bt,
        block_list_input=default_1500_blocks[:320],
        seed=b"reorg_blocks",
        time_per_block=8,
    )


@pytest.fixture(scope="session")
def default_2000_blocks_compact(bt):
    from tests.util.blockchain import persistent_blocks

    return persistent_blocks(
        2000,
        f"test_blocks_2000_compact_{saved_blocks_version}.db",
        bt,
        normalized_to_identity_cc_eos=True,
        normalized_to_identity_icc_eos=True,
        normalized_to_identity_cc_ip=True,
        normalized_to_identity_cc_sp=True,
        seed=b"2000_compact",
    )


@pytest.fixture(scope="session")
def default_10000_blocks_compact(bt):
    from tests.util.blockchain import persistent_blocks

    return persistent_blocks(
        10000,
        f"test_blocks_10000_compact_{saved_blocks_version}.db",
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


@pytest_asyncio.fixture(scope="function")
async def node_with_params(request):
    params = {}
    if request:
        params = request.param
    async for (sims, wallets, bt) in setup_simulators_and_wallets(1, 0, {}, **params):
        yield sims[0]


@pytest_asyncio.fixture(scope="function")
async def two_nodes(db_version, self_hostname):
    async for _ in setup_two_nodes(test_constants, db_version=db_version, self_hostname=self_hostname):
        yield _


@pytest_asyncio.fixture(scope="function")
async def setup_two_nodes_fixture(db_version):
    async for _ in setup_simulators_and_wallets(2, 0, {}, db_version=db_version):
        yield _


@pytest_asyncio.fixture(scope="function")
async def three_nodes(db_version, self_hostname):
    async for _ in setup_n_nodes(test_constants, 3, db_version=db_version, self_hostname=self_hostname):
        yield _


@pytest_asyncio.fixture(scope="function")
async def four_nodes(db_version, self_hostname):
    async for _ in setup_n_nodes(test_constants, 4, db_version=db_version, self_hostname=self_hostname):
        yield _


@pytest_asyncio.fixture(scope="function")
async def five_nodes(db_version, self_hostname):
    async for _ in setup_n_nodes(test_constants, 5, db_version=db_version, self_hostname=self_hostname):
        yield _


@pytest_asyncio.fixture(scope="function")
async def wallet_nodes():
    async_gen = setup_simulators_and_wallets(2, 1, {"MEMPOOL_BLOCK_BUFFER": 1, "MAX_BLOCK_COST_CLVM": 400000000})
    nodes, wallets, bt = await async_gen.__anext__()
    full_node_1 = nodes[0]
    full_node_2 = nodes[1]
    server_1 = full_node_1.full_node.server
    server_2 = full_node_2.full_node.server
    wallet_a = bt.get_pool_wallet_tool()
    wallet_receiver = WalletTool(full_node_1.full_node.constants)
    yield full_node_1, full_node_2, server_1, server_2, wallet_a, wallet_receiver, bt

    async for _ in async_gen:
        yield _


@pytest_asyncio.fixture(scope="function")
async def setup_four_nodes(db_version):
    async for _ in setup_simulators_and_wallets(4, 0, {}, db_version=db_version):
        yield _


@pytest_asyncio.fixture(scope="function")
async def two_nodes_sim_and_wallets():
    async for _ in setup_simulators_and_wallets(2, 0, {}):
        yield _


@pytest_asyncio.fixture(scope="function")
async def two_nodes_sim_and_wallets_services():
    async for _ in setup_simulators_and_wallets_service(2, 0, {}):
        yield _


@pytest_asyncio.fixture(scope="function")
async def one_wallet_and_one_simulator_services():
    async for _ in setup_simulators_and_wallets_service(1, 1, {}):
        yield _


@pytest_asyncio.fixture(scope="function")
async def wallet_node_100_pk():
    async for _ in setup_simulators_and_wallets(1, 1, {}, initial_num_public_keys=100):
        yield _


@pytest_asyncio.fixture(scope="function")
async def simulator_and_wallet() -> AsyncIterator[
    Tuple[List[FullNodeSimulator], List[Tuple[WalletNode, ChiaServer]], BlockTools]
]:
    async for _ in setup_simulators_and_wallets(simulator_count=1, wallet_count=1, dic={}):
        yield _


@pytest_asyncio.fixture(scope="function")
async def two_wallet_nodes(request):
    params = {}
    if request and request.param_index > 0:
        params = request.param
    async for _ in setup_simulators_and_wallets(1, 2, {}, **params):
        yield _


@pytest_asyncio.fixture(scope="function")
async def two_wallet_nodes_services() -> AsyncIterator[
    Tuple[List[Service[FullNode]], List[Service[WalletNode]], BlockTools]
]:
    async for _ in setup_simulators_and_wallets_service(1, 2, {}):
        yield _


@pytest_asyncio.fixture(scope="function")
async def two_wallet_nodes_custom_spam_filtering(spam_filter_after_n_txs, xch_spam_amount):
    async for _ in setup_simulators_and_wallets(1, 2, {}, spam_filter_after_n_txs, xch_spam_amount):
        yield _


@pytest_asyncio.fixture(scope="function")
async def three_sim_two_wallets():
    async for _ in setup_simulators_and_wallets(3, 2, {}):
        yield _


@pytest_asyncio.fixture(scope="function")
async def setup_two_nodes_and_wallet():
    async for _ in setup_simulators_and_wallets(2, 1, {}, db_version=2):
        yield _


@pytest_asyncio.fixture(scope="function")
async def setup_two_nodes_and_wallet_fast_retry():
    async for _ in setup_simulators_and_wallets(
        1, 1, {}, config_overrides={"wallet.tx_resend_timeout_secs": 1}, db_version=2
    ):
        yield _


@pytest_asyncio.fixture(scope="function")
async def three_wallet_nodes():
    async for _ in setup_simulators_and_wallets(1, 3, {}):
        yield _


@pytest_asyncio.fixture(scope="function")
async def wallet_two_node_simulator():
    async for _ in setup_simulators_and_wallets(2, 1, {}):
        yield _


@pytest_asyncio.fixture(scope="function")
async def wallet_nodes_mempool_perf(bt):
    key_seed = bt.farmer_master_sk_entropy
    async for _ in setup_simulators_and_wallets(2, 1, {}, key_seed=key_seed):
        yield _


@pytest_asyncio.fixture(scope="function")
async def two_nodes_two_wallets_with_same_keys(bt) -> AsyncIterator[SimulatorsAndWallets]:
    key_seed = bt.farmer_master_sk_entropy
    async for _ in setup_simulators_and_wallets(2, 2, {}, key_seed=key_seed):
        yield _


@pytest_asyncio.fixture(scope="module")
async def wallet_nodes_perf():
    async_gen = setup_simulators_and_wallets(1, 1, {"MEMPOOL_BLOCK_BUFFER": 1, "MAX_BLOCK_COST_CLVM": 11000000000})
    nodes, wallets, bt = await async_gen.__anext__()
    full_node_1 = nodes[0]
    server_1 = full_node_1.full_node.server
    wallet_a = bt.get_pool_wallet_tool()
    wallet_receiver = WalletTool(full_node_1.full_node.constants)
    yield full_node_1, server_1, wallet_a, wallet_receiver, bt

    async for _ in async_gen:
        yield _


@pytest_asyncio.fixture(scope="function")
async def wallet_nodes_mainnet(db_version):
    async_gen = setup_simulators_and_wallets(2, 1, {}, db_version=db_version)
    nodes, wallets, bt = await async_gen.__anext__()
    full_node_1 = nodes[0]
    full_node_2 = nodes[1]
    server_1 = full_node_1.full_node.server
    server_2 = full_node_2.full_node.server
    wallet_a = bt.get_pool_wallet_tool()
    wallet_receiver = WalletTool(full_node_1.full_node.constants)
    yield full_node_1, full_node_2, server_1, server_2, wallet_a, wallet_receiver, bt

    async for _ in async_gen:
        yield _


@pytest_asyncio.fixture(scope="function")
async def three_nodes_two_wallets():
    async for _ in setup_simulators_and_wallets(3, 2, {}):
        yield _


@pytest_asyncio.fixture(scope="function")
async def one_node() -> AsyncIterator[Tuple[List[Service], List[FullNodeSimulator], BlockTools]]:
    async for _ in setup_simulators_and_wallets_service(1, 0, {}):
        yield _


@pytest.fixture(scope="function", params=[True, False])
def enable_softfork2(request):
    return request.param


@pytest_asyncio.fixture(scope="function")
async def one_node_one_block_with_softfork2(
    enable_softfork2,
) -> AsyncIterator[Tuple[Union[FullNodeAPI, FullNodeSimulator], ChiaServer, BlockTools]]:
    if enable_softfork2:
        constant_replacements = {"SOFT_FORK2_HEIGHT": 0}
    else:
        constant_replacements = {}

    async_gen = setup_simulators_and_wallets(1, 0, constant_replacements)
    nodes, _, bt = await async_gen.__anext__()
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

    async for _ in async_gen:
        yield _


@pytest_asyncio.fixture(scope="function")
async def one_node_one_block() -> AsyncIterator[Tuple[Union[FullNodeAPI, FullNodeSimulator], ChiaServer, BlockTools]]:
    async_gen = setup_simulators_and_wallets(1, 0, {})
    nodes, _, bt = await async_gen.__anext__()
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

    async for _ in async_gen:
        yield _


@pytest_asyncio.fixture(scope="function")
async def two_nodes_one_block():
    async_gen = setup_simulators_and_wallets(2, 0, {})
    nodes, _, bt = await async_gen.__anext__()
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
        genesis_timestamp=10000,
        time_per_block=10,
    )
    assert blocks[0].height == 0

    for block in blocks:
        await full_node_1.full_node.add_block(block)

    await time_out_assert(60, node_height_at_least, True, full_node_1, blocks[-1].height)

    yield full_node_1, full_node_2, server_1, server_2, bt

    async for _ in async_gen:
        yield _


@pytest_asyncio.fixture(scope="function")
async def farmer_one_harvester(tmp_path: Path, bt: BlockTools) -> AsyncIterator[Tuple[List[Service], Service]]:
    async for _ in setup_farmer_multi_harvester(bt, 1, tmp_path, test_constants, start_services=True):
        yield _


@pytest_asyncio.fixture(scope="function")
async def farmer_one_harvester_not_started(
    tmp_path: Path, bt: BlockTools
) -> AsyncIterator[Tuple[List[Service], Service]]:
    async for _ in setup_farmer_multi_harvester(bt, 1, tmp_path, test_constants, start_services=False):
        yield _


@pytest_asyncio.fixture(scope="function")
async def farmer_two_harvester_not_started(
    tmp_path: Path, bt: BlockTools
) -> AsyncIterator[Tuple[List[Service], Service]]:
    async for _ in setup_farmer_multi_harvester(bt, 2, tmp_path, test_constants, start_services=False):
        yield _


@pytest_asyncio.fixture(scope="function")
async def farmer_three_harvester_not_started(
    tmp_path: Path, bt: BlockTools
) -> AsyncIterator[Tuple[List[Service], Service]]:
    async for _ in setup_farmer_multi_harvester(bt, 3, tmp_path, test_constants, start_services=False):
        yield _


# TODO: Ideally, the db_version should be the (parameterized) db_version
# fixture, to test all versions of the database schema. This doesn't work
# because of a hack in shutting down the full node, which means you cannot run
# more than one simulations per process.
@pytest_asyncio.fixture(scope="function")
async def daemon_simulation(bt, get_b_tools, get_b_tools_1):
    async for _ in setup_full_system_connect_to_deamon(
        test_constants_modified,
        bt,
        b_tools=get_b_tools,
        b_tools_1=get_b_tools_1,
        db_version=1,
    ):
        yield _, get_b_tools, get_b_tools_1


@pytest_asyncio.fixture(scope="function")
async def get_daemon(bt):
    async for _ in setup_daemon(btools=bt):
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
    async for daemon in setup_daemon(btools=get_b_tools):
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
async def wallets_prefarm(two_wallet_nodes, self_hostname, trusted):
    """
    Sets up the node with 10 blocks, and returns a payer and payee wallet.
    """
    farm_blocks = 3
    buffer = 1
    full_nodes, wallets, _ = two_wallet_nodes
    full_node_api = full_nodes[0]
    full_node_server = full_node_api.server
    wallet_node_0, wallet_server_0 = wallets[0]
    wallet_node_1, wallet_server_1 = wallets[1]
    wallet_0 = wallet_node_0.wallet_state_manager.main_wallet
    wallet_1 = wallet_node_1.wallet_state_manager.main_wallet

    if trusted:
        wallet_node_0.config["trusted_peers"] = {full_node_server.node_id.hex(): full_node_server.node_id.hex()}
        wallet_node_1.config["trusted_peers"] = {full_node_server.node_id.hex(): full_node_server.node_id.hex()}
    else:
        wallet_node_0.config["trusted_peers"] = {}
        wallet_node_1.config["trusted_peers"] = {}

    await wallet_server_0.start_client(PeerInfo(self_hostname, uint16(full_node_server._port)), None)
    await wallet_server_1.start_client(PeerInfo(self_hostname, uint16(full_node_server._port)), None)

    wallet_0_rewards = await full_node_api.farm_blocks_to_wallet(count=farm_blocks, wallet=wallet_0)
    wallet_1_rewards = await full_node_api.farm_blocks_to_wallet(count=farm_blocks, wallet=wallet_1)
    await full_node_api.farm_blocks_to_puzzlehash(count=buffer, guarantee_transaction_blocks=True)

    await full_node_api.wait_for_wallets_synced(wallet_nodes=[wallet_node_0, wallet_node_1], timeout=30)

    assert await wallet_0.get_confirmed_balance() == wallet_0_rewards
    assert await wallet_0.get_unconfirmed_balance() == wallet_0_rewards
    assert await wallet_1.get_confirmed_balance() == wallet_1_rewards
    assert await wallet_1.get_unconfirmed_balance() == wallet_1_rewards

    return (wallet_node_0, wallet_0_rewards), (wallet_node_1, wallet_1_rewards), full_node_api


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

    await wallet_server_0.start_client(PeerInfo(self_hostname, uint16(full_node_server._port)), None)
    await wallet_server_1.start_client(PeerInfo(self_hostname, uint16(full_node_server._port)), None)
    await wallet_server_2.start_client(PeerInfo(self_hostname, uint16(full_node_server._port)), None)

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
async def introducer(bt):
    async for service in setup_introducer(bt, 0):
        yield service._api, service._node.server


@pytest_asyncio.fixture(scope="function")
async def introducer_service(bt):
    async for _ in setup_introducer(bt, 0):
        yield _


@pytest_asyncio.fixture(scope="function")
async def timelord(bt):
    async for service in setup_timelord(uint16(0), False, test_constants, bt):
        yield service._api, service._node.server


@pytest_asyncio.fixture(scope="function")
async def timelord_service(bt):
    async for _ in setup_timelord(uint16(0), False, test_constants, bt):
        yield _


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
