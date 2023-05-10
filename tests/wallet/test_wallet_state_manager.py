from __future__ import annotations

from contextlib import asynccontextmanager
from secrets import token_bytes
from typing import AsyncIterator

import pytest

from chia.simulator.setup_nodes import SimulatorsAndWallets
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.ints import uint32, uint64
from chia.util.misc import VersionedBlob
from chia.wallet.puzzles.clawback.metadata import ClawbackMetadata, ClawbackVersion
from chia.wallet.util.wallet_types import CoinType
from chia.wallet.wallet_state_manager import WalletStateManager


@asynccontextmanager
async def assert_sync_mode(wallet_state_manager: WalletStateManager, target_height: uint32) -> AsyncIterator[None]:
    assert not wallet_state_manager.lock.locked()
    assert not wallet_state_manager.sync_mode
    assert wallet_state_manager.sync_target is None
    new_current_height = max(0, target_height - 1)
    await wallet_state_manager.blockchain.set_finished_sync_up_to(new_current_height)
    async with wallet_state_manager.set_sync_mode(target_height) as current_height:
        assert current_height == new_current_height
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


@pytest.mark.asyncio
async def test_deserialize_coin_metadata(simulator_and_wallet: SimulatorsAndWallets) -> None:
    _, [(wallet_node, _)], _ = simulator_and_wallet
    manager = wallet_node.wallet_state_manager
    clawback_data = ClawbackMetadata(uint64(500), bytes32(token_bytes()), bytes32(token_bytes()))
    valid_data = VersionedBlob(ClawbackVersion.V1.value, bytes(clawback_data))
    assert manager.deserialize_coin_metadata(None, CoinType.CLAWBACK) is None
    assert manager.deserialize_coin_metadata(valid_data, CoinType.CLAWBACK) == clawback_data.to_json_dict()
    assert manager.deserialize_coin_metadata(valid_data, CoinType.NORMAL) == bytes(clawback_data)
