import asyncio
from pathlib import Path
from typing import List, Tuple

import pytest

from chia.farmer.farmer import Farmer
from chia.server.start_service import Service
from chia.simulator.block_tools import BlockTools
from chia.simulator.time_out_assert import time_out_assert
from chia.util.ints import uint16
from chia.util.keychain import generate_mnemonic
from tests.setup_nodes import setup_harvesters


def farmer_is_started(farmer):
    return farmer.started


@pytest.mark.asyncio
async def test_start_with_empty_keychain(farmer_not_started: Tuple[Service, BlockTools]):
    farmer_service, bt = farmer_not_started
    farmer: Farmer = farmer_service._node
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
async def test_harvester_handshake(tmp_path: Path, farmer_not_started: Tuple[Service, BlockTools]):
    farmer_service, bt = farmer_not_started
    # harvester_service = harvesters[0]
    farmer = farmer_service._node

    def farmer_has_connections():
        return len(farmer.server.get_connections()) > 0

    def handshake_task_active():
        return farmer.harvester_handshake_task is not None

    # First remove all keys from the keychain
    assert bt.local_keychain is not None
    bt.local_keychain.delete_all_keys()
    # Handshake task and plot manager thread should not be running yet
    assert farmer.harvester_handshake_task is None
    # Start farmer
    await farmer_service.start()

    sh = setup_harvesters(bt, 1, tmp_path, bt.constants, uint16(farmer_service._server._port), start_services=False)

    harvester_services: List[Service] = await sh.__anext__()
    harvester_service = harvester_services[0]
    harvester = harvester_service._node

    # Start the harvester
    await harvester_service.start()

    async def handshake_done() -> bool:
        await asyncio.sleep(1)
        return harvester.plot_manager._refresh_thread is not None and len(harvester.plot_manager.farmer_public_keys) > 0

    assert harvester.plot_manager._refresh_thread is None
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

    with pytest.raises(StopAsyncIteration):
        await sh.__anext__()
