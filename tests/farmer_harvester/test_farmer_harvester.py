from __future__ import annotations

import asyncio
from math import floor
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pytest
from pytest_mock import MockerFixture

from chia_rs import G1Element, G2Element, AugSchemeMPL

from chia.cmds.cmds_util import get_any_service_client
from chia.consensus.blockchain import AddBlockResult
from chia.consensus.multiprocess_validation import PreValidationResult
from chia.farmer.farmer import Farmer
from chia.farmer.farmer_api import FarmerAPI
from chia.full_node.full_node import FullNode
from chia.harvester.harvester import Harvester
from chia.harvester.harvester_api import HarvesterAPI
from chia.plotting.util import PlotsRefreshParameter, PlotInfo, parse_plot_info
from chia.protocols import farmer_protocol, harvester_protocol
from chia.protocols.farmer_protocol import NewSignagePoint, RequestSignedValues, DeclareProofOfSpace
from chia.protocols.harvester_protocol import RespondSignatures, RequestSignatures
from chia.protocols.protocol_message_types import ProtocolMessageTypes
from chia.rpc.harvester_rpc_client import HarvesterRpcClient
from chia.server.outbound_message import NodeType, make_msg, Message
from chia.server.server import ChiaServer
from chia.server.ws_connection import WSChiaConnection
from chia.simulator.block_tools import BlockTools, get_signage_point
from chia.simulator.full_node_simulator import FullNodeSimulator
from chia.types.aliases import FarmerService, HarvesterService
from chia.types.blockchain_format.foliage import FoliageBlockData
from chia.types.blockchain_format.proof_of_space import generate_plot_public_key, ProofOfSpace, calculate_pos_challenge, \
    get_quality_string
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.peer_info import UnresolvedPeerInfo
from chia.util.bech32m import decode_puzzle_hash
from chia.util.config import load_config
from chia.util.hash import std_hash
from chia.util.ints import uint8, uint32, uint64, uint128
from chia.util.keychain import generate_mnemonic
from chia.util.misc import split_async_manager
from chia.util.streamable import Streamable
from chia.wallet.derive_keys import master_sk_to_local_sk
from chia.wallet.wallet_node import WalletNode
from chia.wallet.wallet_node_api import WalletNodeAPI
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

@pytest.mark.asyncio
async def test_farmer_handles_farmer_reward_address_overwrite(
    caplog: pytest.LogCaptureFixture,
    farmer_one_harvester_zero_bits_plot_filter,
    mocker: MockerFixture
) -> None:
    """
    Tests support for overwriting the farmer reward address by a third party Harvester
    by injecting a RespondSignatures message from the Harvester to the Farmer which
    contains the overwritten reward address. It intercepts subsequent messages between
    the Farmer and FullNode to ensure the values given the overwritten farmer reward address ar used.
    """

    async def wait_until_node_type_connected(server: ChiaServer, node_type: NodeType) -> WSChiaConnection:
        while True:
            for peer in server.all_connections.values():
                if peer.connection_type == node_type.value:
                    return peer
            await asyncio.sleep(1)

    harvester_service, farmer_service, full_node_service, bt = farmer_one_harvester_zero_bits_plot_filter

    farmer: Farmer = farmer_service._node
    harvester: Harvester = harvester_service._node
    full_node: FullNode = full_node_service._node

    # Connect peers to each other
    farmer_service.add_peer(UnresolvedPeerInfo(str(full_node_service.self_hostname), full_node_service._server.get_port()))
    harvester_service.add_peer(UnresolvedPeerInfo(str(farmer_service.self_hostname), farmer_service._server.get_port()))

    plot: PlotInfo = next(iter(bt.plot_manager.plots.values()))

    plot_id_bytes = bytes32(plot.prover.get_id())
    plot_id: str = plot_id_bytes.hex()

    # Go beyond the first block
    blocks = bt.get_consecutive_blocks(uint8(7))
    pre_validation_results: List[
        PreValidationResult
    ] = await full_node.blockchain.pre_validate_blocks_multiprocessing(
        blocks, {}, validate_signatures=True
    )
    assert pre_validation_results is not None
    assert len(pre_validation_results) == len(blocks)
    for i in range(len(blocks)):
        r, _, _ = await full_node.blockchain.add_block(blocks[i], pre_validation_results[i])
        assert r == AddBlockResult.NEW_PEAK

    # Create fake SP
    blockchain = full_node.blockchain
    peak = blockchain.get_peak()
    # sub_slot_total_iters = uint128(0)
    sp_index = uint8(4)

    sp = get_signage_point(
        bt.constants,
        blockchain,
        peak,
        peak.ip_sub_slot_total_iters(bt.constants),
        sp_index,
        [],
        bt.constants.SUB_SLOT_ITERS_STARTING,
    )

    assert sp.rc_vdf.challenge != bt.constants.GENESIS_CHALLENGE
    # assert sp.cc_vdf.challenge != bt.constants.GENESIS_CHALLENGE

    # Add SP to the full node
    assert full_node.full_node_store.new_signage_point(sp_index, blockchain, peak, peak.sub_slot_iters, sp, True)

    challenge_chain_sp: bytes32 = sp.cc_vdf.output.get_hash()
    vdf_challenge_hash: bytes32 = sp.cc_vdf.challenge
    reward_chain_sp: bytes32 = sp.rc_vdf.output.get_hash()
    pos_challenge: bytes32 = calculate_pos_challenge(plot_id_bytes, vdf_challenge_hash, challenge_chain_sp)

    # challenge_seed: uint32 = 1
    # while True:
    #     try:
    #         seed_bytes = challenge_seed.to_bytes(4, 'little') + bytes(28)
    #         vdf_challenge_hash = bytes32.from_bytes(seed_bytes)
    #         pos_challenge = calculate_pos_challenge(plot_id_bytes, vdf_challenge_hash, challenge_chain_sp)
    #         _ = plot.prover.get_full_proof(pos_challenge, 0)
    #         break
    #     except RuntimeError:
    #         challenge_seed += 1
    #         continue

    # Ensure the proof of space exists given the challenge
    pospace = plot.prover.get_full_proof(pos_challenge, 0)

    # Look up local_sk from plot to save locked memory
    (
        pool_public_key_or_puzzle_hash,
        farmer_public_key,
        local_master_sk,
    ) = parse_plot_info(plot.prover.get_memo())
    local_sk = master_sk_to_local_sk(local_master_sk)

    if isinstance(pool_public_key_or_puzzle_hash, G1Element):
        include_taproot = False
    else:
        assert isinstance(pool_public_key_or_puzzle_hash, bytes32)
        include_taproot = True

    agg_pk = generate_plot_public_key(local_sk.get_g1(), farmer_public_key, include_taproot)

    # Sign messages
    messages_to_sign = [challenge_chain_sp, reward_chain_sp]
    signatures: List[Tuple[bytes32, G2Element]] = []
    for message in messages_to_sign:
        signature: G2Element = AugSchemeMPL.sign(local_sk, message, agg_pk)
        signatures.append((message, signature))

    # Add the fake SP to the farmer
    farmer.sps[challenge_chain_sp] = [NewSignagePoint(
        challenge_hash=vdf_challenge_hash,
        challenge_chain_sp=challenge_chain_sp,
        reward_chain_sp=reward_chain_sp,
        difficulty=bt.constants.DIFFICULTY_STARTING,
        sub_slot_iters=bt.constants.SUB_SLOT_ITERS_STARTING,
        signage_point_index=sp_index,
        peak_height=0
    )]

    # Add fake proof of space
    farmer_proof_of_space = ProofOfSpace(
        challenge=pos_challenge,
        pool_public_key=pool_public_key_or_puzzle_hash,
        pool_contract_puzzle_hash=None,
        plot_public_key=plot.plot_public_key,
        size=uint8(plot.prover.get_size()),
        proof=pospace
    )

    quality_string = get_quality_string(farmer_proof_of_space, plot_id_bytes)
    full_plot_identifier = quality_string.hex() + plot.prover.get_filename()

    farmer.proofs_of_space[challenge_chain_sp] = [(full_plot_identifier, farmer_proof_of_space)]

    farmer.quality_str_to_identifiers[quality_string] = (
        full_plot_identifier,
        vdf_challenge_hash,
        challenge_chain_sp,
        harvester.server.node_id
    )

    # Send a signature response message from the harvester with an overwritten farmer reward address
    farmer_reward_address = decode_puzzle_hash('xch1uf48n3f50xrs7zds0uek9wp9wmyza6crnex6rw8kwm3jnm39y82q5mvps6')

    response_signatures = RespondSignatures(
        plot_identifier=full_plot_identifier,
        challenge_hash=vdf_challenge_hash,
        sp_hash=challenge_chain_sp,
        local_pk=local_sk.get_g1(),
        farmer_pk=farmer_public_key,
        message_signatures=signatures,
        farmer_reward_address_overwrite=farmer_reward_address
    )

    # Send message to farmer
    msg = make_msg(ProtocolMessageTypes.respond_signatures, response_signatures)

    # Make sure all the peers are connected to each other
    await wait_until_node_type_connected(farmer.server, NodeType.HARVESTER)
    await wait_until_node_type_connected(farmer.server, NodeType.FULL_NODE)
    full_node_peer_farmer = await wait_until_node_type_connected(full_node.server, NodeType.FARMER)
    harvester_peer_farmer = await wait_until_node_type_connected(harvester.server, NodeType.FARMER)

    request_signed_values_copy: RequestSignedValues     # FullNode -> Farmer
    request_signatures_copy: RequestSignatures          # Farmer -> Harvester
    finished_message_chain: bool = False

    # Intercept messages between peers
    def inspect_message(msg: Message):
        nonlocal request_signed_values_copy
        nonlocal finished_message_chain

        if msg.type == ProtocolMessageTypes.request_signed_values.value:
            data: RequestSignedValues = RequestSignedValues.from_bytes(msg.data)
            request_signed_values_copy = data
            assert data.foliage_block_data is not None
            assert data.foliage_block_data.farmer_reward_puzzle_hash == farmer_reward_address
        elif msg.type == ProtocolMessageTypes.declare_proof_of_space.value:
            data: DeclareProofOfSpace = DeclareProofOfSpace.from_bytes(msg.data)
            assert data.include_foliage_block_data is True
        elif msg.type == ProtocolMessageTypes.respond_signatures.value:
            assert request_signed_values_copy is not None
            finished_message_chain = True

    async def send_intercept_farmer(*args, **kwargs):
        messages: List[Message] = args[0]
        node_type: NodeType = args[1]
        [inspect_message(m) for m in messages]
        await ChiaServer.send_to_all(farmer.server, messages, node_type)
        return

    async def intercept_farmer_call_api_of_specific(*args, **kwargs):
        nonlocal request_signatures_copy

        fn = args[0]
        request: Streamable = args[1]
        node_id: bytes32 = args[2]

        if isinstance(request, RequestSignatures):
            request_signatures_copy = request

        await ChiaServer.call_api_of_specific(farmer.server, fn, request, node_id)

    async def send_intercept_full_node(*args, **kwargs):
        msg: Message = args[0]
        inspect_message(msg)
        await WSChiaConnection.send_message(full_node_peer_farmer, msg)

    async def send_intercept_harvester(*args, **kwargs):
        msg: Message = args[0]
        inspect_message(msg)
        await WSChiaConnection.send_message(harvester_peer_farmer, msg)

    mocker.patch.object(farmer.server, 'send_to_all', side_effect=send_intercept_farmer)
    mocker.patch.object(farmer.server, 'call_api_of_specific', side_effect=intercept_farmer_call_api_of_specific)
    mocker.patch.object(full_node_peer_farmer, 'send_message', side_effect=send_intercept_full_node)

    # Start the message chain
    await harvester.server.send_to_all([msg], NodeType.FARMER)

    # Intercept harvester messages after the first RequestSignedValues message.
    # We're only interested in the block signatures, not the SP signatures.
    mocker.patch.object(harvester_peer_farmer, 'send_message', side_effect=send_intercept_harvester)

    # Wait for the all the messages to be exchanged between
    def did_finished_message_chain():
        return finished_message_chain
    await time_out_assert(15, did_finished_message_chain, True)

    # Ensure foliage block data is as expected
    assert request_signed_values_copy is not None
    assert request_signatures_copy is not None

    foliage_block_hash_index: uint8 = request_signatures_copy.foliage_block_data[0]
    foliage_block_data: FoliageBlockData = request_signatures_copy.foliage_block_data[1]
    assert foliage_block_hash_index == 0
    assert foliage_block_data.farmer_reward_puzzle_hash == farmer_reward_address
    assert foliage_block_data.get_hash() == request_signed_values_copy.foliage_block_data_hash
    assert foliage_block_data.get_hash() == request_signatures_copy.messages[foliage_block_hash_index]
