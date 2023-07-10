from __future__ import annotations

import asyncio
from typing import List, Tuple

import pytest
from blspy import G1Element

from chia.farmer.farmer import Farmer
from chia.farmer.farmer_api import FarmerAPI
from chia.harvester.harvester import Harvester
from chia.harvester.harvester_api import HarvesterAPI
from chia.protocols import harvester_protocol
from chia.protocols.protocol_message_types import ProtocolMessageTypes
from chia.server.outbound_message import NodeType, make_msg
from chia.server.start_service import Service
from chia.simulator.block_tools import BlockTools
from chia.simulator.time_out_assert import time_out_assert
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.peer_info import UnresolvedPeerInfo
from chia.util.keychain import generate_mnemonic
from tests.conftest import HarvesterFarmerEnvironment


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
