from __future__ import annotations

import asyncio
import dataclasses
from math import floor
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pytest
from chia_rs import ClassgroupElement, G1Element
from pytest_mock import MockerFixture

from chia.cmds.cmds_util import get_any_service_client
from chia.consensus.blockchain import AddBlockResult
from chia.consensus.multiprocess_validation import PreValidationResult
from chia.farmer.farmer import Farmer, calculate_harvester_fee_quality
from chia.farmer.farmer_api import FarmerAPI
from chia.full_node.full_node import FullNode
from chia.harvester.harvester import Harvester
from chia.harvester.harvester_api import HarvesterAPI
from chia.plotting.util import PlotsRefreshParameter, PlotInfo, parse_plot_info
from chia.protocols import farmer_protocol, harvester_protocol, timelord_protocol
from chia.protocols.farmer_protocol import NewSignagePoint, RequestSignedValues, DeclareProofOfSpace, \
    SignagePointSourceData, SPVDFSourceData
from chia.protocols.full_node_protocol import NewSignagePointOrEndOfSubSlot
from chia.protocols.harvester_protocol import ProofOfSpaceFeeInfo, RespondSignatures, SigningDataKind
from chia.protocols.protocol_message_types import ProtocolMessageTypes
from chia.rpc.harvester_rpc_client import HarvesterRpcClient
from chia.server.outbound_message import Message, NodeType, make_msg
from chia.server.server import ChiaServer
from chia.server.ws_connection import WSChiaConnection
from chia.simulator.block_tools import BlockTools
from chia.types.blockchain_format.foliage import FoliageBlockData, FoliageTransactionBlock
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.blockchain_format.slots import ChallengeChainSubSlot, RewardChainSubSlot
from chia.types.peer_info import UnresolvedPeerInfo
from chia.util.bech32m import decode_puzzle_hash, encode_puzzle_hash
from chia.util.config import load_config
from chia.util.hash import std_hash
from chia.util.ints import uint8, uint32, uint64, uint128
from chia.util.keychain import generate_mnemonic
from chia.util.misc import split_async_manager
from chia.util.streamable import Streamable
from chia.wallet.derive_keys import master_sk_to_local_sk
from chia.wallet.wallet_node import WalletNode
from chia.wallet.wallet_node_api import WalletNodeAPIfrom chia.util.streamable import Streamable
from tests.conftest import HarvesterFarmerEnvironment
from tests.util.time_out_assert import time_out_assert


def farmer_is_started(farmer: Farmer) -> bool:
    return farmer.started


async def get_harvester_config(harvester_rpc_port: Optional[int], root_path: Path) -> Dict[str, Any]:
    async with get_any_service_client(HarvesterRpcClient, harvester_rpc_port, root_path) as (harvester_client, _):
        return await harvester_client.get_harvester_config()


async def update_harvester_config(harvester_rpc_port: Optional[int], root_path: Path, config: Dict[str, Any]) -> bool:
    async with get_any_service_client(HarvesterRpcClient, harvester_rpc_port, root_path) as (harvester_client, _):
        return await harvester_client.update_harvester_config(config)


@pytest.mark.anyio
async def test_start_with_empty_keychain(
    farmer_one_harvester_not_started: Tuple[List[HarvesterService], FarmerService, BlockTools]
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
    async with farmer_service.manage():
        await asyncio.sleep(5)
        assert not farmer.started
        # Add a key to the keychain, this should lead to the start task passing
        # `setup_keys` and set `Farmer.initialized`
        bt.local_keychain.add_private_key(generate_mnemonic())
        await time_out_assert(5, farmer_is_started, True, farmer)
    assert not farmer.started


@pytest.mark.anyio
async def test_harvester_handshake(
    farmer_one_harvester_not_started: Tuple[List[HarvesterService], FarmerService, BlockTools]
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
    async with split_async_manager(
        manager=harvester_service.manage(), object=harvester_service
    ) as split_harvester_manager:
        # Start both services and wait a bit
        async with farmer_service.manage():
            async with harvester_service.manage():
                harvester_service.add_peer(
                    UnresolvedPeerInfo(str(farmer_service.self_hostname), farmer_service._server.get_port())
                )
                # Handshake task should be started but the handshake should not be done
                await time_out_assert(5, handshake_task_active, True)
                assert not await handshake_done()
            # wait for the farmer to lose the connection
            await time_out_assert(10, farmer_has_connections, False)
            assert not await handshake_done()
            # Handshake task should be stopped again
            await time_out_assert(5, handshake_task_active, False)
            await asyncio.sleep(1)
            assert harvester.plot_manager._refresh_thread is None
            assert len(harvester.plot_manager.farmer_public_keys) == 0
            # Re-start the harvester and make sure the handshake task gets started but
            # the handshake still doesn't go through
            await split_harvester_manager.enter()
            harvester_service.add_peer(
                UnresolvedPeerInfo(str(farmer_service.self_hostname), farmer_service._server.get_port())
            )
            await time_out_assert(5, handshake_task_active, True)
            assert not await handshake_done()
        # make sure the handshake_task doesn't block the shutdown
        await time_out_assert(5, handshake_task_active, False)
        # Re-start the farmer and make sure the handshake task succeeds if a key get added to the keychain
        async with farmer_service.manage():
            await time_out_assert(5, handshake_task_active, True)
            assert not await handshake_done()
            bt.local_keychain.add_private_key(generate_mnemonic())
            await time_out_assert(5, farmer_is_started, True, farmer)
            await time_out_assert(5, handshake_task_active, False)
            await time_out_assert(5, handshake_done, True)


@pytest.mark.anyio
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


@pytest.mark.anyio
async def test_harvester_config(farmer_one_harvester: Tuple[List[HarvesterService], FarmerService, BlockTools]) -> None:
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


@pytest.mark.anyio
async def test_missing_signage_point(
    farmer_one_harvester: Tuple[List[HarvesterService], FarmerService, BlockTools]
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


@pytest.mark.anyio
async def test_harvester_has_no_server(
    farmer_one_harvester: Tuple[List[FarmerService], HarvesterService, BlockTools],
) -> None:
    harvesters, _, bt = farmer_one_harvester
    harvester_server = harvesters[0]._server

    assert harvester_server.webserver is None


@pytest.mark.anyio
async def test_harvester_receive_source_signing_data(
    farmer_harvester_full_node_timelord_zero_bits_plot_filter, mocker: MockerFixture
) -> None:
    (
        harvester_service,
        farmer_service,
        full_node_service_1,
        _,
        bt,
    ) = farmer_harvester_full_node_timelord_zero_bits_plot_filter

    farmer: Farmer = farmer_service._node
    harvester: Harvester = harvester_service._node
    full_node: FullNode = full_node_service_1._node

    # Connect peers to each other
    farmer_service.add_peer(
        UnresolvedPeerInfo(str(full_node_service_1.self_hostname), full_node_service_1._server.get_port())
    )
    harvester_service.add_peer(UnresolvedPeerInfo(str(farmer_service.self_hostname), farmer_service._server.get_port()))

    validated_foliage_data = False
    validated_foliage_transaction = False
    validated_cc_vdf = False
    validated_rc_vdf = False
    validated_sub_slot_cc = False
    validated_sub_slot_rc = False
    # validated_partial = False

    finished_validating_data = False
    farmer_reward_address = decode_puzzle_hash("txch1psqeaw0h244v5sy2r4se8pheyl62n8778zl6t5e7dep0xch9xfkqhx2mej")

    async def intercept_harvester_request_signatures(*args):
        request: harvester_protocol.RequestSignatures = harvester_protocol.RequestSignatures.from_bytes(args[0])
        nonlocal harvester
        nonlocal farmer_reward_address

        validate_harvester_request_signatures(request)
        result_msg: Message = await HarvesterAPI.request_signatures(harvester.server.api, request)

        # Inject overridden farmer reward address
        response: RespondSignatures = dataclasses.replace(
            RespondSignatures.from_bytes(result_msg.data), farmer_reward_address_override=farmer_reward_address
        )

        return make_msg(ProtocolMessageTypes.respond_signatures, response)

    def validate_harvester_request_signatures(request: harvester_protocol.RequestSignatures):
        nonlocal full_node
        nonlocal farmer_reward_address
        nonlocal validated_foliage_data
        nonlocal validated_foliage_transaction
        nonlocal validated_cc_vdf
        nonlocal validated_rc_vdf
        nonlocal validated_sub_slot_cc
        nonlocal validated_sub_slot_rc
        nonlocal finished_validating_data

        assert len(request.messages) > 0
        assert len(request.messages) == len(request.message_data)
        for i in range(len(request.messages)):
            hash = request.messages[i]
            src = request.message_data[i]

            data: Streamable = None
            if src.kind == SigningDataKind.FOLIAGE_BLOCK_DATA:
                data = FoliageBlockData.from_bytes(src.data)
                assert (
                    data.farmer_reward_puzzle_hash == farmer_reward_address
                    or data.farmer_reward_puzzle_hash
                    == bytes32(full_node.constants.GENESIS_PRE_FARM_FARMER_PUZZLE_HASH)
                )
                if data.farmer_reward_puzzle_hash == farmer_reward_address:
                    validated_foliage_data = True
            elif src.kind == SigningDataKind.FOLIAGE_TRANSACTION_BLOCK:
                data = FoliageTransactionBlock.from_bytes(src.data)
                validated_foliage_transaction = True
            elif src.kind == SigningDataKind.CHALLENGE_CHAIN_VDF:
                data = ClassgroupElement.from_bytes(src.data)
                validated_cc_vdf = True
            elif src.kind == SigningDataKind.REWARD_CHAIN_VDF:
                data = ClassgroupElement.from_bytes(src.data)
                validated_rc_vdf = True
            elif src.kind == SigningDataKind.CHALLENGE_CHAIN_SUB_SLOT:
                data = ChallengeChainSubSlot.from_bytes(src.data)
                validated_sub_slot_cc = True
            elif src.kind == SigningDataKind.REWARD_CHAIN_SUB_SLOT:
                data = RewardChainSubSlot.from_bytes(src.data)
                validated_sub_slot_rc = True
            elif src.kind == SigningDataKind.PARTIAL:
                # #NOTE: This data type is difficult to trigger, so it is
                #        not tested for the time being.
                # data = PostPartialPayload.from_bytes(src.data)
                # validated_partial = True
                pass

            finished_validating_data = (
                validated_foliage_data
                and validated_foliage_transaction
                and validated_cc_vdf
                and validated_rc_vdf
                and validated_sub_slot_cc
                and validated_sub_slot_rc
            )

            assert data is not None
            data_hash = data.get_hash()
            assert data_hash == hash

    async def intercept_farmer_new_proof_of_space(*args) -> None:
        nonlocal farmer
        nonlocal farmer_reward_address

        request: harvester_protocol.NewProofOfSpace = dataclasses.replace(
            harvester_protocol.NewProofOfSpace.from_bytes(args[0]), farmer_reward_address_override=farmer_reward_address
        )
        peer: WSChiaConnection = args[1]

        await FarmerAPI.new_proof_of_space(farmer.server.api, request, peer)

    async def intercept_farmer_request_signed_values(*args) -> Optional[Message]:
        nonlocal farmer
        nonlocal farmer_reward_address
        nonlocal full_node

        request: RequestSignedValues = RequestSignedValues.from_bytes(args[0])

        # Ensure the FullNode included the source data for the signatures
        assert request.foliage_block_data
        assert request.foliage_block_data.get_hash() == request.foliage_block_data_hash
        assert request.foliage_transaction_block_data
        assert request.foliage_transaction_block_data.get_hash() == request.foliage_transaction_block_hash

        assert (
            request.foliage_block_data.farmer_reward_puzzle_hash == farmer_reward_address
            or request.foliage_block_data.farmer_reward_puzzle_hash
            == bytes32(full_node.constants.GENESIS_PRE_FARM_FARMER_PUZZLE_HASH)
        )

        return await FarmerAPI.request_signed_values(farmer.server.api, request)

    mocker.patch.object(farmer.server.api, "request_signed_values", side_effect=intercept_farmer_request_signed_values)
    mocker.patch.object(farmer.server.api, "new_proof_of_space", side_effect=intercept_farmer_new_proof_of_space)
    mocker.patch.object(harvester.server.api, "request_signatures", side_effect=intercept_harvester_request_signatures)

    await wait_until_node_type_connected(farmer.server, NodeType.FULL_NODE)
    await wait_until_node_type_connected(farmer.server, NodeType.HARVESTER)

    # wait until test finishes
    def did_finished_validating_data():
        return finished_validating_data

    await time_out_assert(90, did_finished_validating_data, True)


@pytest.mark.anyio
async def test_harvester_fee_convention(
    farmer_harvester_full_node_timelord_zero_bits_plot_filter, caplog: pytest.LogCaptureFixture, mocker: MockerFixture
) -> None:
    (
        harvester_service,
        farmer_service,
        full_node_service_1,
        _,
        _,
    ) = farmer_harvester_full_node_timelord_zero_bits_plot_filter

    farmer: Farmer = farmer_service._node

    # Connect peers to each other
    farmer_service.add_peer(
        UnresolvedPeerInfo(str(full_node_service_1.self_hostname), full_node_service_1._server.get_port())
    )
    harvester_service.add_peer(UnresolvedPeerInfo(str(farmer_service.self_hostname), farmer_service._server.get_port()))

    fee_threshold = 0.5
    max_fee_proofs = 5
    fee_count = 0
    proof_count = 0

    farmer_reward_puzzle_hash = decode_puzzle_hash("txch1psqeaw0h244v5sy2r4se8pheyl62n8778zl6t5e7dep0xch9xfkqhx2mej")

    async def intercept_farmer_new_proof_of_space(*args) -> None:
        nonlocal farmer
        nonlocal fee_threshold
        nonlocal max_fee_proofs
        nonlocal proof_count
        nonlocal fee_count
        nonlocal farmer_reward_puzzle_hash

        request: harvester_protocol.NewProofOfSpace = harvester_protocol.NewProofOfSpace.from_bytes(args[0])

        fee_threshold_int = uint32(int(0xFFFFFFFF * fee_threshold))

        fee_quality = calculate_harvester_fee_quality(request.proof.proof, request.challenge_hash)
        if fee_quality <= fee_threshold_int and fee_count < max_fee_proofs:
            fee_count += 1
            request = dataclasses.replace(
                request,
                farmer_reward_address_override=farmer_reward_puzzle_hash,
                fee_info=ProofOfSpaceFeeInfo(applied_fee_threshold=fee_threshold_int),
            )

        if proof_count <= max_fee_proofs:
            proof_count += 1

        peer: WSChiaConnection = args[1]
        await FarmerAPI.new_proof_of_space(farmer.server.api, request, peer)

    mocker.patch.object(farmer.server.api, "new_proof_of_space", side_effect=intercept_farmer_new_proof_of_space)

    await wait_until_node_type_connected(farmer.server, NodeType.FULL_NODE)
    await wait_until_node_type_connected(farmer.server, NodeType.HARVESTER)

    log_text_len = 0

    def log_has_new_text() -> bool:
        nonlocal log_text_len

        text_len = len(caplog.text)
        if text_len > log_text_len:
            log_text_len = text_len
            return True

        return False

    # wait until we've received all the proofs
    def received_all_proofs():
        nonlocal max_fee_proofs
        nonlocal fee_count

        return fee_count >= max_fee_proofs

    await time_out_assert(120, received_all_proofs, True)

    # Wait for the farmer to pick up the last proofs
    await asyncio.sleep(2)

    assert fee_count > 0
    await time_out_assert(10, log_has_new_text, True)

    find_message = "Fee threshold passed for challenge"
    find_index = 0
    log_text = caplog.text
    fail_count = 0

    for _ in range(fee_count):
        index = log_text.find(find_message, find_index) + len(find_message)
        if index < 0:
            fail_count += 1
            assert fail_count < 10
            await time_out_assert(10, log_has_new_text, True)
        else:
            find_index = index


async def wait_until_node_type_connected(server: ChiaServer, node_type: NodeType) -> WSChiaConnection:
    while True:
        for peer in server.all_connections.values():
            if peer.connection_type == node_type.value:
                return peer
        await asyncio.sleep(1)
