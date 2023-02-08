from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator, Tuple
from chia.simulator.setup_nodes import SimulatorsAndWallets

import pytest

from chia.server.start_service import Service
from chia.simulator.block_tools import BlockTools
from chia.util.ints import uint32
from chia.wallet.wallet_node import WalletNode
from chia.wallet.wallet_state_manager import WalletStateManager


@asynccontextmanager
async def assert_sync_mode(wallet_state_manager: WalletStateManager, target_height: uint32) -> AsyncIterator[None]:
    assert not wallet_state_manager.lock.locked()
    assert not wallet_state_manager.sync_mode
    assert wallet_state_manager.sync_target is None
    async with wallet_state_manager.set_sync_mode(target_height):
        assert wallet_state_manager.sync_mode
        assert wallet_state_manager.lock.locked()
        assert wallet_state_manager.sync_target == target_height
        yield
    assert not wallet_state_manager.lock.locked()
    assert not wallet_state_manager.sync_mode
    assert wallet_state_manager.sync_target is None


@pytest.mark.asyncio
async def test_set_sync_mode(simulator_and_wallet: SimulatorsAndWallets) -> None:
    _, [(wallet_node, _)], _ = simulator_and_wallet
    async with assert_sync_mode(wallet_node.wallet_state_manager, uint32(1)):
        pass
    async with assert_sync_mode(wallet_node.wallet_state_manager, uint32(22)):
        pass
    async with assert_sync_mode(wallet_node.wallet_state_manager, uint32(333)):
        pass


@pytest.mark.asyncio
async def test_set_sync_mode_exception(simulator_and_wallet: SimulatorsAndWallets) -> None:
    _, [(wallet_node, _)], _ = simulator_and_wallet
    async with assert_sync_mode(wallet_node.wallet_state_manager, uint32(1)):
        raise Exception
