from __future__ import annotations

import asyncio
from math import floor
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pytest
from blspy import G1Element

from chia.cmds.cmds_util import get_any_service_client
from chia.farmer.farmer import Farmer
from chia.farmer.farmer_api import FarmerAPI
from chia.harvester.harvester import Harvester
from chia.harvester.harvester_api import HarvesterAPI
from chia.plotting.util import PlotsRefreshParameter
from chia.protocols import farmer_protocol, harvester_protocol
from chia.protocols.protocol_message_types import ProtocolMessageTypes
from chia.rpc.harvester_rpc_client import HarvesterRpcClient
from chia.server.outbound_message import NodeType, make_msg
from chia.server.start_service import Service
from chia.simulator.block_tools import BlockTools
from chia.simulator.time_out_assert import time_out_assert
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.peer_info import UnresolvedPeerInfo
from chia.util.config import load_config
from chia.util.hash import std_hash
from chia.util.ints import uint8, uint32, uint64
from chia.util.keychain import generate_mnemonic
from tests.conftest import HarvesterFarmerEnvironment


def farmer_is_started(farmer: Farmer) -> bool:
    return farmer.started


async def get_harvester_config(harvester_rpc_port: Optional[int], root_path: Path) -> Dict[str, Any]:
    async with get_any_service_client(HarvesterRpcClient, harvester_rpc_port, root_path) as (harvester_client, _):
        return await harvester_client.get_harvester_config()


async def update_harvester_config(harvester_rpc_port: Optional[int], root_path: Path, config: Dict[str, Any]) -> bool:
    async with get_any_service_client(HarvesterRpcClient, harvester_rpc_port, root_path) as (harvester_client, _):
        return await harvester_client.update_harvester_config(config)


@pytest.mark.asyncio
async def test_start_with_empty_keychain(
    farmer_one_harvester_not_started: Tuple[
        List[Service[Harvester, HarvesterAPI]], Service[Farmer, FarmerAPI], BlockTools
    ]
) -> None:
    _, farmer_service, bt = farmer_one_harvester_not_started
    farmer: Farmer = farmer_service._node
    farmer_service.reconnect_retry_seconds = 1
    # First remove all keys from the keychain
    assert bt.local_keychain is not None
    bt.local_keychain.delete_all_keys()
    # Make sure the farmer service is not initialized yet
    assert not farmer.started
    # Start it, wait 5 seconds and make sure it still isn't initialized (since the keychain is empty)
    await farmer_service.start()
    await asyncio.sleep(5)
    assert not farmer.started
    # Add a key to the keychain, this should lead to the start task passing `setup_keys` and set `Farmer.initialized`
    bt.local_keychain.add_private_key(generate_mnemonic())
    await time_out_assert(5, farmer_is_started, True, farmer)
    # Stop it and wait for `Farmer.initialized` to become reset
    farmer_service.stop()
    await farmer_service.wait_closed()
    assert not farmer.started


@pytest.mark.asyncio
async def test_harvester_handshake(
    farmer_one_harvester_not_started: Tuple[
        List[Service[Harvester, HarvesterAPI]], Service[Farmer, FarmerAPI], BlockTools
    ]
) -> None:
    harvesters, farmer_service, bt = farmer_one_harvester_not_started
    harvester_service = harvesters[0]
    harvester = harvester_service._node
    farmer = farmer_service._node

    farmer_service.reconnect_retry_seconds = 1
    harvester_service.reconnect_retry_seconds = 1

    def farmer_has_connections() -> bool:
        return len(farmer.server.get_connections()) > 0

    def handshake_task_active() -> bool:
        return farmer.harvester_handshake_task is not None

    async def handshake_done() -> bool:
        await asyncio.sleep(1)
        return harvester.plot_manager._refresh_thread is not None and len(harvester.plot_manager.farmer_public_keys) > 0

    # First remove all keys from the keychain
    assert bt.local_keychain is not None
    bt.local_keychain.delete_all_keys()
    # Handshake task and plot manager thread should not be running yet
    assert farmer.harvester_handshake_task is None
    assert harvester.plot_manager._refresh_thread is None
    # Start both services and wait a bit
    await farmer_service.start()
    await harvester_service.start()
    harvester_service.add_peer(UnresolvedPeerInfo(str(farmer_service.self_hostname), farmer_service._server.get_port()))
    # Handshake task should be started but the handshake should not be done
    await time_out_assert(5, handshake_task_active, True)
    assert not await handshake_done()
    # Stop the harvester service and wait for the farmer to lose the connection
    harvester_service.stop()
    await harvester_service.wait_closed()
    await time_out_assert(10, farmer_has_connections, False)
    assert not await handshake_done()
    # Handshake task should be stopped again
    await time_out_assert(5, handshake_task_active, False)
    await asyncio.sleep(1)
    assert harvester.plot_manager._refresh_thread is None
    assert len(harvester.plot_manager.farmer_public_keys) == 0
    # Re-start the harvester and make sure the handshake task gets started but the handshake still doesn't go through
    await harvester_service.start()
    harvester_service.add_peer(UnresolvedPeerInfo(str(farmer_service.self_hostname), farmer_service._server.get_port()))
    await time_out_assert(5, handshake_task_active, True)
    assert not await handshake_done()
    # Stop the farmer and make sure the handshake_task doesn't block the shutdown
    farmer_service.stop()
    await farmer_service.wait_closed()
    await time_out_assert(5, handshake_task_active, False)
    # Re-start the farmer and make sure the handshake task succeeds if a key get added to the keychain
    await farmer_service.start()
    await time_out_assert(5, handshake_task_active, True)
    assert not await handshake_done()
    bt.local_keychain.add_private_key(generate_mnemonic())
    await time_out_assert(5, farmer_is_started, True, farmer)
    await time_out_assert(5, handshake_task_active, False)
    await time_out_assert(5, handshake_done, True)


@pytest.mark.asyncio
async def test_farmer_respond_signatures(
    caplog: pytest.LogCaptureFixture, harvester_farmer_environment: HarvesterFarmerEnvironment
) -> None:
    # This test ensures that the farmer correctly rejects invalid RespondSignatures
    # messages from the harvester.
    # In this test we're leveraging the fact that the farmer can handle RespondSignatures
    # messages even though it didn't request them, to cover when the farmer doesn't know
    # about an sp_hash, so it fails at the sp record check.

    def log_is_ready() -> bool:
        return len(caplog.text) > 0

    _, _, harvester_service, _, _ = harvester_farmer_environment
    # We won't have an sp record for this one
    challenge_hash = bytes32(b"1" * 32)
    sp_hash = bytes32(b"2" * 32)
    response: harvester_protocol.RespondSignatures = harvester_protocol.RespondSignatures(
        plot_identifier="test",
        challenge_hash=challenge_hash,
        sp_hash=sp_hash,
        local_pk=G1Element(),
        farmer_pk=G1Element(),
        message_signatures=[],
    )
    msg = make_msg(ProtocolMessageTypes.respond_signatures, response)
    await harvester_service._node.server.send_to_all([msg], NodeType.FARMER)
    await time_out_assert(5, log_is_ready)
    # We fail the sps record check
    expected_error = f"Do not have challenge hash {challenge_hash}"
    assert expected_error in caplog.text


@pytest.mark.asyncio
async def test_harvester_config(
    farmer_one_harvester: Tuple[List[Service[Harvester, HarvesterAPI]], Service[Farmer, FarmerAPI], BlockTools]
) -> None:
    harvester_services, farmer_service, bt = farmer_one_harvester
    harvester_service = harvester_services[0]

    assert harvester_service.rpc_server and harvester_service.rpc_server.webserver

    harvester_rpc_port = harvester_service.rpc_server.webserver.listen_port
    harvester_config = await get_harvester_config(harvester_rpc_port, bt.root_path)
    assert harvester_config["success"] is True

    def check_config_match(config1: Dict[str, Any], config2: Dict[str, Any]) -> None:
        assert config1["harvester"]["use_gpu_harvesting"] == config2["use_gpu_harvesting"]
        assert config1["harvester"]["gpu_index"] == config2["gpu_index"]
        assert config1["harvester"]["enforce_gpu_index"] == config2["enforce_gpu_index"]
        assert config1["harvester"]["disable_cpu_affinity"] == config2["disable_cpu_affinity"]
        assert config1["harvester"]["parallel_decompressor_count"] == config2["parallel_decompressor_count"]
        assert config1["harvester"]["decompressor_thread_count"] == config2["decompressor_thread_count"]
        assert config1["harvester"]["recursive_plot_scan"] == config2["recursive_plot_scan"]
        assert (
            config2["refresh_parameter_interval_seconds"] == config1["harvester"]["refresh_parameter_interval_seconds"]
            if "refresh_parameter_interval_seconds" in config1["harvester"]
            else PlotsRefreshParameter().interval_seconds
        )

    check_config_match(bt.config, harvester_config)

    harvester_config["use_gpu_harvesting"] = not harvester_config["use_gpu_harvesting"]
    harvester_config["gpu_index"] += 1
    harvester_config["enforce_gpu_index"] = not harvester_config["enforce_gpu_index"]
    harvester_config["disable_cpu_affinity"] = not harvester_config["disable_cpu_affinity"]
    harvester_config["parallel_decompressor_count"] += 1
    harvester_config["decompressor_thread_count"] += 1
    harvester_config["recursive_plot_scan"] = not harvester_config["recursive_plot_scan"]
    harvester_config["refresh_parameter_interval_seconds"] = harvester_config["refresh_parameter_interval_seconds"] + 1

    res = await update_harvester_config(harvester_rpc_port, bt.root_path, harvester_config)
    assert res is True
    new_config = load_config(harvester_service.root_path, "config.yaml")
    check_config_match(new_config, harvester_config)


@pytest.mark.asyncio
async def test_missing_signage_point(
    farmer_one_harvester: Tuple[List[Service[Harvester, HarvesterAPI]], Service[Farmer, FarmerAPI], BlockTools]
) -> None:
    _, farmer_service, bt = farmer_one_harvester
    farmer_api = farmer_service._api
    farmer = farmer_api.farmer

    def create_sp(index: int, challenge_hash: bytes32) -> Tuple[uint64, farmer_protocol.NewSignagePoint]:
        time = uint64(index + 1)
        sp = farmer_protocol.NewSignagePoint(
            challenge_hash, std_hash(b"2"), std_hash(b"3"), uint64(1), uint64(1000000), uint8(index), uint32(1)
        )
        return time, sp

    # First sp. No missing sps
    time0, sp0 = create_sp(index=0, challenge_hash=std_hash(b"1"))
    assert farmer.prev_signage_point is None
    ret = farmer.check_missing_signage_points(time0, sp0)
    assert ret is None
    assert farmer.prev_signage_point == (time0, sp0)

    # 2nd sp. No missing sps
    time1, sp1 = create_sp(index=1, challenge_hash=std_hash(b"1"))
    ret = farmer.check_missing_signage_points(time1, sp1)
    assert ret is None

    # 3rd sp. 1 missing sp
    time3, sp3 = create_sp(index=3, challenge_hash=std_hash(b"1"))
    ret = farmer.check_missing_signage_points(time3, sp3)
    assert ret == (time3, uint32(1))

    # New challenge hash. Not counted as missing sp
    _, sp_new_cc1 = create_sp(index=0, challenge_hash=std_hash(b"2"))
    time_new_cc1 = time3
    ret = farmer.check_missing_signage_points(time_new_cc1, sp_new_cc1)
    assert ret is None

    # Another new challenge hash. Calculating missing sps by timestamp
    _, sp_new_cc2 = create_sp(index=0, challenge_hash=std_hash(b"3"))
    # New sp is not in 9s but 12s is allowed
    # since allowance multiplier is 1.6. (12 < 9 * 1.6)
    time_new_cc2 = uint64(time_new_cc1 + 12)
    ret = farmer.check_missing_signage_points(time_new_cc2, sp_new_cc2)
    assert ret is None

    # Another new challenge hash. Calculating missing sps by timestamp
    _, sp_new_cc3 = create_sp(index=0, challenge_hash=std_hash(b"4"))
    time_new_cc3 = uint64(time_new_cc2 + 601)  # roughly 10 minutes passed.
    ret = farmer.check_missing_signage_points(time_new_cc3, sp_new_cc3)
    assert ret is not None
    ret_time, ret_skipped_sps = ret
    assert ret_time == time_new_cc3
    assert ret_skipped_sps == uint32(
        floor(601 / (farmer.constants.SUB_SLOT_TIME_TARGET / farmer.constants.NUM_SPS_SUB_SLOT))
    )

    original_state_changed_callback = farmer.state_changed_callback
    assert original_state_changed_callback is not None
    number_of_missing_sps: uint32 = uint32(0)

    def state_changed(change: str, data: Dict[str, Any]) -> None:
        nonlocal number_of_missing_sps
        number_of_missing_sps = data["missing_signage_points"][1]
        original_state_changed_callback(change, data)

    farmer.state_changed_callback = state_changed  # type: ignore
    _, sp_for_farmer_api = create_sp(index=2, challenge_hash=std_hash(b"4"))
    await farmer_api.new_signage_point(sp_for_farmer_api)
    assert number_of_missing_sps == uint32(1)
