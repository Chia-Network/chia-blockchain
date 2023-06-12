from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

import pytest

from chia.simulator.setup_nodes import SimulatorsAndWallets
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.ints import uint32
from chia.wallet.derivation_record import DerivationRecord
from chia.wallet.derive_keys import master_sk_to_wallet_sk, master_sk_to_wallet_sk_unhardened
from chia.wallet.util.wallet_types import WalletType
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


@pytest.mark.parametrize("hardened", [True, False])
@pytest.mark.asyncio
async def test_get_private_key(simulator_and_wallet: SimulatorsAndWallets, hardened: bool) -> None:
    _, [(wallet_node, _)], _ = simulator_and_wallet
    wallet_state_manager: WalletStateManager = wallet_node.wallet_state_manager
    derivation_index = uint32(10000)
    conversion_method = master_sk_to_wallet_sk if hardened else master_sk_to_wallet_sk_unhardened
    expected_private_key = conversion_method(wallet_state_manager.private_key, derivation_index)
    record = DerivationRecord(
        derivation_index,
        bytes32(b"0" * 32),
        expected_private_key.get_g1(),
        WalletType.STANDARD_WALLET,
        uint32(1),
        hardened,
    )
    await wallet_state_manager.puzzle_store.add_derivation_paths([record])
    assert await wallet_state_manager.get_private_key(record.puzzle_hash) == expected_private_key


@pytest.mark.asyncio
async def test_get_private_key_failure(simulator_and_wallet: SimulatorsAndWallets) -> None:
    _, [(wallet_node, _)], _ = simulator_and_wallet
    wallet_state_manager: WalletStateManager = wallet_node.wallet_state_manager
    invalid_puzzle_hash = bytes32(b"1" * 32)
    with pytest.raises(ValueError, match=f"No key for puzzle hash: {invalid_puzzle_hash.hex()}"):
        await wallet_state_manager.get_private_key(bytes32(b"1" * 32))
