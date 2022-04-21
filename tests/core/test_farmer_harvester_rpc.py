import logging
import time

import pytest
import pytest_asyncio

from chia.consensus.coinbase import create_puzzlehash_for_pk
from chia.protocols import farmer_protocol
from chia.rpc.farmer_rpc_api import FarmerRpcApi
from chia.rpc.farmer_rpc_client import FarmerRpcClient
from chia.rpc.harvester_rpc_api import HarvesterRpcApi
from chia.rpc.harvester_rpc_client import HarvesterRpcClient
from chia.rpc.rpc_server import start_rpc_server
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.bech32m import decode_puzzle_hash, encode_puzzle_hash
from chia.util.byte_types import hexstr_to_bytes
from chia.util.config import load_config, lock_and_load_config, save_config
from chia.util.hash import std_hash
from chia.util.ints import uint8, uint16, uint32, uint64
from chia.util.misc import get_list_or_len
from chia.wallet.derive_keys import master_sk_to_wallet_sk, master_sk_to_wallet_sk_unhardened
from tests.setup_nodes import setup_harvester_farmer, test_constants
from tests.time_out_assert import time_out_assert, time_out_assert_custom_interval
from tests.util.rpc import validate_get_routes
from tests.util.socket import find_available_listen_port

log = logging.getLogger(__name__)


@pytest_asyncio.fixture(scope="function")
async def harvester_farmer_simulation(bt):
    async for _ in setup_harvester_farmer(bt, test_constants, start_services=True):
        yield _


@pytest_asyncio.fixture(scope="function")
async def harvester_farmer_environment(bt, harvester_farmer_simulation, self_hostname):
    harvester_service, farmer_service = harvester_farmer_simulation

    def stop_node_cb():
        pass

    config = bt.config
    hostname = config["self_hostname"]
    daemon_port = config["daemon_port"]

    farmer_rpc_api = FarmerRpcApi(farmer_service._api.farmer)
    harvester_rpc_api = HarvesterRpcApi(harvester_service._node)

    rpc_port_farmer = uint16(find_available_listen_port("farmer rpc"))
    rpc_port_harvester = uint16(find_available_listen_port("harvester rpc"))

    rpc_cleanup = await start_rpc_server(
        farmer_rpc_api,
        hostname,
        daemon_port,
        rpc_port_farmer,
        stop_node_cb,
        bt.root_path,
        config,
        connect_to_daemon=False,
    )
    rpc_cleanup_2 = await start_rpc_server(
        harvester_rpc_api,
        hostname,
        daemon_port,
        rpc_port_harvester,
        stop_node_cb,
        bt.root_path,
        config,
        connect_to_daemon=False,
    )

    farmer_rpc_client = await FarmerRpcClient.create(self_hostname, rpc_port_farmer, bt.root_path, config)
    harvester_rpc_client = await HarvesterRpcClient.create(self_hostname, rpc_port_harvester, bt.root_path, config)

    async def have_connections():
        return len(await farmer_rpc_client.get_connections()) > 0

    await time_out_assert(15, have_connections, True)

    yield farmer_service, farmer_rpc_api, farmer_rpc_client, harvester_service, harvester_rpc_api, harvester_rpc_client

    farmer_rpc_client.close()
    harvester_rpc_client.close()
    await farmer_rpc_client.await_closed()
    await harvester_rpc_client.await_closed()
    await rpc_cleanup()
    await rpc_cleanup_2()


@pytest.mark.asyncio
async def test_get_routes(harvester_farmer_environment):
    (
        farmer_service,
        farmer_rpc_api,
        farmer_rpc_client,
        harvester_service,
        harvester_rpc_api,
        harvester_rpc_client,
    ) = harvester_farmer_environment
    await validate_get_routes(farmer_rpc_client, farmer_rpc_api)
    await validate_get_routes(harvester_rpc_client, harvester_rpc_api)


@pytest.mark.parametrize("endpoint", ["get_harvesters", "get_harvesters_summary"])
@pytest.mark.asyncio
async def test_farmer_get_harvesters_and_summary(harvester_farmer_environment, endpoint: str):
    (
        farmer_service,
        farmer_rpc_api,
        farmer_rpc_client,
        harvester_service,
        harvester_rpc_api,
        harvester_rpc_client,
    ) = harvester_farmer_environment
    harvester = harvester_service._node

    harvester_plots = []

    async def non_zero_plots() -> bool:
        res = await harvester_rpc_client.get_plots()
        nonlocal harvester_plots
        harvester_plots = res["plots"]
        return len(harvester_plots) > 0

    await time_out_assert(10, non_zero_plots)

    async def test_get_harvesters():
        nonlocal harvester_plots
        harvester.plot_manager.trigger_refresh()
        await time_out_assert(5, harvester.plot_manager.needs_refresh, value=False)
        farmer_res = await getattr(farmer_rpc_client, endpoint)()

        if len(list(farmer_res["harvesters"])) != 1:
            log.error(f"test_get_harvesters: invalid harvesters {list(farmer_res['harvesters'])}")
            return False

        harvester_dict = farmer_res["harvesters"][0]
        counts_only: bool = endpoint == "get_harvesters_summary"

        if not counts_only:
            harvester_dict["plots"] = sorted(harvester_dict["plots"], key=lambda item: item["filename"])
            harvester_plots = sorted(harvester_plots, key=lambda item: item["filename"])

        assert harvester_dict["plots"] == get_list_or_len(harvester_plots, counts_only)
        assert harvester_dict["failed_to_open_filenames"] == get_list_or_len([], counts_only)
        assert harvester_dict["no_key_filenames"] == get_list_or_len([], counts_only)
        assert harvester_dict["duplicates"] == get_list_or_len([], counts_only)

        return True

    await time_out_assert_custom_interval(30, 1, test_get_harvesters)


@pytest.mark.asyncio
async def test_farmer_signage_point_endpoints(harvester_farmer_environment):
    (
        farmer_service,
        farmer_rpc_api,
        farmer_rpc_client,
        harvester_service,
        harvester_rpc_api,
        harvester_rpc_client,
    ) = harvester_farmer_environment
    farmer_api = farmer_service._api

    assert (await farmer_rpc_client.get_signage_point(std_hash(b"2"))) is None
    assert len(await farmer_rpc_client.get_signage_points()) == 0

    async def have_signage_points():
        return len(await farmer_rpc_client.get_signage_points()) > 0

    sp = farmer_protocol.NewSignagePoint(
        std_hash(b"1"), std_hash(b"2"), std_hash(b"3"), uint64(1), uint64(1000000), uint8(2)
    )
    await farmer_api.new_signage_point(sp)

    await time_out_assert(5, have_signage_points, True)
    assert (await farmer_rpc_client.get_signage_point(std_hash(b"2"))) is not None


@pytest.mark.asyncio
async def test_farmer_reward_target_endpoints(bt, harvester_farmer_environment):
    (
        farmer_service,
        farmer_rpc_api,
        farmer_rpc_client,
        harvester_service,
        harvester_rpc_api,
        harvester_rpc_client,
    ) = harvester_farmer_environment
    farmer_api = farmer_service._api

    targets_1 = await farmer_rpc_client.get_reward_targets(False)
    assert "have_pool_sk" not in targets_1
    assert "have_farmer_sk" not in targets_1
    targets_2 = await farmer_rpc_client.get_reward_targets(True, 2)
    assert targets_2["have_pool_sk"] and targets_2["have_farmer_sk"]

    new_ph: bytes32 = create_puzzlehash_for_pk(master_sk_to_wallet_sk(bt.farmer_master_sk, uint32(2)).get_g1())
    new_ph_2: bytes32 = create_puzzlehash_for_pk(master_sk_to_wallet_sk(bt.pool_master_sk, uint32(7)).get_g1())

    await farmer_rpc_client.set_reward_targets(encode_puzzle_hash(new_ph, "xch"), encode_puzzle_hash(new_ph_2, "xch"))
    targets_3 = await farmer_rpc_client.get_reward_targets(True, 10)
    assert decode_puzzle_hash(targets_3["farmer_target"]) == new_ph
    assert decode_puzzle_hash(targets_3["pool_target"]) == new_ph_2
    assert targets_3["have_pool_sk"] and targets_3["have_farmer_sk"]

    # limit the derivation search to 3 should fail to find the pool sk
    targets_4 = await farmer_rpc_client.get_reward_targets(True, 3)
    assert not targets_4["have_pool_sk"] and targets_4["have_farmer_sk"]

    # check observer addresses
    observer_farmer: bytes32 = create_puzzlehash_for_pk(
        master_sk_to_wallet_sk_unhardened(bt.farmer_master_sk, uint32(2)).get_g1()
    )
    observer_pool: bytes32 = create_puzzlehash_for_pk(
        master_sk_to_wallet_sk_unhardened(bt.pool_master_sk, uint32(7)).get_g1()
    )
    await farmer_rpc_client.set_reward_targets(
        encode_puzzle_hash(observer_farmer, "xch"), encode_puzzle_hash(observer_pool, "xch")
    )
    targets = await farmer_rpc_client.get_reward_targets(True, 10)
    assert decode_puzzle_hash(targets["farmer_target"]) == observer_farmer
    assert decode_puzzle_hash(targets["pool_target"]) == observer_pool
    assert targets["have_pool_sk"] and targets["have_farmer_sk"]

    root_path = farmer_api.farmer._root_path
    config = load_config(root_path, "config.yaml")
    assert config["farmer"]["xch_target_address"] == encode_puzzle_hash(observer_farmer, "xch")
    assert config["pool"]["xch_target_address"] == encode_puzzle_hash(observer_pool, "xch")

    new_ph_2_encoded = encode_puzzle_hash(new_ph_2, "xch")
    added_char = new_ph_2_encoded + "a"
    with pytest.raises(ValueError):
        await farmer_rpc_client.set_reward_targets(None, added_char)

    replaced_char = new_ph_2_encoded[0:-1] + "a"
    with pytest.raises(ValueError):
        await farmer_rpc_client.set_reward_targets(None, replaced_char)


@pytest.mark.asyncio
async def test_farmer_get_pool_state(harvester_farmer_environment, self_hostname):
    (
        farmer_service,
        farmer_rpc_api,
        farmer_rpc_client,
        harvester_service,
        harvester_rpc_api,
        harvester_rpc_client,
    ) = harvester_farmer_environment
    farmer_api = farmer_service._api

    assert len((await farmer_rpc_client.get_pool_state())["pool_state"]) == 0
    pool_list = [
        {
            "launcher_id": "ae4ef3b9bfe68949691281a015a9c16630fc8f66d48c19ca548fb80768791afa",
            "owner_public_key": "aa11e92274c0f6a2449fd0c7cfab4a38f943289dbe2214c808b36390c34eacfaa1d4c8f3c6ec582ac502ff32228679a0",  # noqa
            "payout_instructions": "c2b08e41d766da4116e388357ed957d04ad754623a915f3fd65188a8746cf3e8",
            "pool_url": self_hostname,
            "p2_singleton_puzzle_hash": "16e4bac26558d315cded63d4c5860e98deb447cc59146dd4de06ce7394b14f17",
            "target_puzzle_hash": "344587cf06a39db471d2cc027504e8688a0a67cce961253500c956c73603fd58",
        }
    ]

    root_path = farmer_api.farmer._root_path
    with lock_and_load_config(root_path, "config.yaml") as config:
        config["pool"]["pool_list"] = pool_list
        save_config(root_path, "config.yaml", config)
    await farmer_api.farmer.update_pool_state()

    pool_state = (await farmer_rpc_client.get_pool_state())["pool_state"]
    assert len(pool_state) == 1
    assert (
        pool_state[0]["pool_config"]["payout_instructions"]
        == "c2b08e41d766da4116e388357ed957d04ad754623a915f3fd65188a8746cf3e8"
    )
    await farmer_rpc_client.set_payout_instructions(
        hexstr_to_bytes(pool_state[0]["pool_config"]["launcher_id"]), "1234vy"
    )
    await farmer_api.farmer.update_pool_state()
    pool_state = (await farmer_rpc_client.get_pool_state())["pool_state"]
    assert pool_state[0]["pool_config"]["payout_instructions"] == "1234vy"

    now = time.time()
    # Big arbitrary numbers used to be unlikely to accidentally collide.
    before_24h = (now - (25 * 60 * 60), 29984713)
    since_24h = (now - (23 * 60 * 60), 93049817)
    for p2_singleton_puzzle_hash, pool_dict in farmer_api.farmer.pool_state.items():
        for key in ["points_found_24h", "points_acknowledged_24h"]:
            pool_dict[key].insert(0, since_24h)
            pool_dict[key].insert(0, before_24h)

    sp = farmer_protocol.NewSignagePoint(
        std_hash(b"1"), std_hash(b"2"), std_hash(b"3"), uint64(1), uint64(1000000), uint8(2)
    )
    await farmer_api.new_signage_point(sp)
    client_pool_state = await farmer_rpc_client.get_pool_state()
    for pool_dict in client_pool_state["pool_state"]:
        for key in ["points_found_24h", "points_acknowledged_24h"]:
            assert pool_dict[key][0] == list(since_24h)
