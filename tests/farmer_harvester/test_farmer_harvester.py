from __future__ import annotations

import asyncio
from typing import List, Tuple

import pytest
from blspy import G1Element

from chia.farmer.farmer import Farmer
from chia.farmer.farmer_api import FarmerAPI
from chia.harvester.harvester import Harvester
from chia.harvester.harvester_api import HarvesterAPI
from chia.protocols import farmer_protocol, harvester_protocol
from chia.protocols.protocol_message_types import ProtocolMessageTypes
from chia.server.outbound_message import NodeType, make_msg
from chia.server.start_service import Service
from chia.simulator.block_tools import BlockTools
from chia.simulator.time_out_assert import time_out_assert
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.peer_info import UnresolvedPeerInfo
from chia.util.ints import uint8, uint64
from chia.util.keychain import generate_mnemonic
from tests.conftest import HarvesterFarmerEnvironment
from tests.core.test_farmer_harvester_rpc import wait_for_plot_sync


def farmer_is_started(farmer: Farmer) -> bool:
    return farmer.started


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


@pytest.mark.parametrize("with_sp", [False, True])
@pytest.mark.asyncio
async def test_farmer_respond_signatures(
    caplog: pytest.LogCaptureFixture, harvester_farmer_environment: HarvesterFarmerEnvironment, with_sp: bool
) -> None:
    # This test ensures that the farmer correctly rejects invalid RespondSignatures
    # messages from the harvester.
    # In this test we're leveraging the fact that the farmer can handle RespondSignatures
    # messages even though it didn't request them, to cover two scenarios:
    # 1. One where the farmer knows about the sp_hash, so it passes the challange
    # hash check and covers the sp_hash to filter size check.
    # 2. One where the farmer doesn't know about the sp_hash, so it fails earlier
    # at the sp record check, and it doesn't get to check sp_hash to filter size.

    def log_is_ready() -> bool:
        return len(caplog.text) > 0

    farmer_service, _, harvester_service, _, _ = harvester_farmer_environment
    if with_sp:
        farmer_api = farmer_service._api
        harvester_id = harvester_service._server.node_id
        receiver = farmer_api.farmer.plot_sync_receivers[harvester_id]
        if receiver.initial_sync():
            await wait_for_plot_sync(receiver, receiver.last_sync().sync_id)
        # Issue a new signage point message so that we'd have an sp record for this sp_hash
        challenge_hash = bytes32.from_hexstr("0x73490e166d0b88347c37d921660b216c27316aae9a3450933d3ff3b854e5831a")
        sp_hash = bytes32.from_hexstr("0x7b3e23dbd438f9aceefa9827e2c5538898189987f49b06eceb7a43067e77b531")
        sp = farmer_protocol.NewSignagePoint(
            challenge_hash=challenge_hash,
            challenge_chain_sp=sp_hash,
            reward_chain_sp=bytes32(b"1" * 32),
            difficulty=uint64(1),
            sub_slot_iters=uint64(1000000),
            signage_point_index=uint8(2),
            filter_prefix_bits=uint8(8),
        )
        await farmer_api.new_signage_point(sp)
    else:
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
    if with_sp:
        # We pass the sp record check and proceed to the sp_hash to filter size
        # record check (where we fail)
        expected_error = f"Do not have filter size for sp hash {sp_hash}"
    else:
        # We fail the sps record check
        expected_error = f"Do not have challenge hash {challenge_hash}"
    assert expected_error in caplog.text
