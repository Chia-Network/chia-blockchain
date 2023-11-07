from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, List, Optional, cast
from unittest.mock import MagicMock

import pytest
from chia_rs import G1Element

from benchmarks.utils import rand_g1, rand_hash
from chia.pools.pool_wallet import PoolWallet
from chia.types.blockchain_format.sized_bytes import bytes32


@dataclass
class MockStandardWallet:
    canned_puzzlehash: bytes32

    async def get_new_puzzlehash(self) -> bytes32:
        return self.canned_puzzlehash


@dataclass
class MockWalletStateManager:
    root_path: Optional[Path] = None


@dataclass
class MockPoolWalletConfig:
    launcher_id: bytes32
    pool_url: str
    payout_instructions: str
    target_puzzle_hash: bytes32
    p2_singleton_puzzle_hash: bytes32
    owner_public_key: G1Element


@dataclass
class MockPoolState:
    pool_url: Optional[str]
    target_puzzle_hash: bytes32
    owner_pubkey: G1Element


@dataclass
class MockPoolWalletInfo:
    launcher_id: bytes32
    p2_singleton_puzzle_hash: bytes32
    current: MockPoolState


@pytest.mark.anyio
async def test_update_pool_config_new_config(monkeypatch: Any) -> None:
    """
    Test that PoolWallet can create a new pool config
    """

    updated_configs: List[MockPoolWalletConfig] = []
    payout_instructions_ph = rand_hash()
    launcher_id: bytes32 = rand_hash()
    p2_singleton_puzzle_hash: bytes32 = rand_hash()
    pool_url: str = ""
    target_puzzle_hash: bytes32 = rand_hash()
    owner_pubkey: G1Element = rand_g1()
    current: MockPoolState = MockPoolState(
        pool_url=pool_url,
        target_puzzle_hash=target_puzzle_hash,
        owner_pubkey=owner_pubkey,
    )
    current_state: MockPoolWalletInfo = MockPoolWalletInfo(
        launcher_id=launcher_id,
        p2_singleton_puzzle_hash=p2_singleton_puzzle_hash,
        current=current,
    )

    # No config data
    def mock_load_pool_config(root_path: Path) -> List[MockPoolWalletConfig]:
        return []

    monkeypatch.setattr("chia.pools.pool_wallet.load_pool_config", mock_load_pool_config)

    # Mock pool_config.update_pool_config to capture the updated configs
    async def mock_pool_config_update_pool_config(
        root_path: Path, pool_config_list: List[MockPoolWalletConfig]
    ) -> None:
        nonlocal updated_configs
        updated_configs = pool_config_list

    monkeypatch.setattr("chia.pools.pool_wallet.update_pool_config", mock_pool_config_update_pool_config)

    # Mock PoolWallet.get_current_state to return our canned state
    async def mock_get_current_state(self: Any) -> Any:
        return current_state

    monkeypatch.setattr(PoolWallet, "get_current_state", mock_get_current_state)

    # Create an empty PoolWallet and populate only the required fields
    wallet = PoolWallet(
        wallet_state_manager=MockWalletStateManager(),  # type: ignore[arg-type]
        standard_wallet=cast(Any, MockStandardWallet(canned_puzzlehash=payout_instructions_ph)),
        log=MagicMock(),
        wallet_info=MagicMock(),
        wallet_id=MagicMock(),
    )

    await wallet.update_pool_config()

    assert len(updated_configs) == 1
    assert updated_configs[0].launcher_id == launcher_id
    assert updated_configs[0].pool_url == pool_url
    assert updated_configs[0].payout_instructions == payout_instructions_ph.hex()
    assert updated_configs[0].target_puzzle_hash == target_puzzle_hash
    assert updated_configs[0].p2_singleton_puzzle_hash == p2_singleton_puzzle_hash
    assert updated_configs[0].owner_public_key == owner_pubkey


@pytest.mark.anyio
async def test_update_pool_config_existing_payout_instructions(monkeypatch: Any) -> None:
    """
    Test that PoolWallet will retain existing payout_instructions when updating the pool config.
    """

    updated_configs: List[MockPoolWalletConfig] = []
    payout_instructions_ph = rand_hash()
    launcher_id: bytes32 = rand_hash()
    p2_singleton_puzzle_hash: bytes32 = rand_hash()
    pool_url: str = "https://fake.pool.url"
    target_puzzle_hash: bytes32 = rand_hash()
    owner_pubkey: G1Element = rand_g1()
    current: MockPoolState = MockPoolState(
        pool_url=pool_url,
        target_puzzle_hash=target_puzzle_hash,
        owner_pubkey=owner_pubkey,
    )
    current_state: MockPoolWalletInfo = MockPoolWalletInfo(
        launcher_id=launcher_id,
        p2_singleton_puzzle_hash=p2_singleton_puzzle_hash,
        current=current,
    )

    # Existing config data with different values
    # payout_instructions should _NOT_ be updated after calling update_pool_config
    existing_launcher_id: bytes32 = launcher_id
    existing_pool_url: str = ""
    existing_payout_instructions_ph: bytes32 = rand_hash()
    existing_target_puzzle_hash: bytes32 = rand_hash()
    existing_p2_singleton_puzzle_hash: bytes32 = rand_hash()
    existing_owner_pubkey: G1Element = rand_g1()
    existing_config: MockPoolWalletConfig = MockPoolWalletConfig(
        launcher_id=existing_launcher_id,
        pool_url=existing_pool_url,
        payout_instructions=existing_payout_instructions_ph.hex(),
        target_puzzle_hash=existing_target_puzzle_hash,
        p2_singleton_puzzle_hash=existing_p2_singleton_puzzle_hash,
        owner_public_key=existing_owner_pubkey,
    )

    # No config data
    def mock_load_pool_config(root_path: Path) -> List[MockPoolWalletConfig]:
        nonlocal existing_config
        return [existing_config]

    monkeypatch.setattr("chia.pools.pool_wallet.load_pool_config", mock_load_pool_config)

    # Mock pool_config.update_pool_config to capture the updated configs
    async def mock_pool_config_update_pool_config(
        root_path: Path, pool_config_list: List[MockPoolWalletConfig]
    ) -> None:
        nonlocal updated_configs
        updated_configs = pool_config_list

    monkeypatch.setattr("chia.pools.pool_wallet.update_pool_config", mock_pool_config_update_pool_config)

    # Mock PoolWallet.get_current_state to return our canned state
    async def mock_get_current_state(self: Any) -> Any:
        return current_state

    monkeypatch.setattr(PoolWallet, "get_current_state", mock_get_current_state)

    # Create an empty PoolWallet and populate only the required fields
    wallet = PoolWallet(
        wallet_state_manager=MockWalletStateManager(),  # type: ignore[arg-type]
        standard_wallet=cast(Any, MockStandardWallet(canned_puzzlehash=payout_instructions_ph)),
        log=MagicMock(),
        wallet_info=MagicMock(),
        wallet_id=MagicMock(),
    )

    await wallet.update_pool_config()

    assert len(updated_configs) == 1
    assert updated_configs[0].launcher_id == launcher_id
    assert updated_configs[0].pool_url == pool_url

    # payout_instructions should still point to existing_payout_instructions_ph
    assert updated_configs[0].payout_instructions == existing_payout_instructions_ph.hex()

    assert updated_configs[0].target_puzzle_hash == target_puzzle_hash
    assert updated_configs[0].p2_singleton_puzzle_hash == p2_singleton_puzzle_hash
    assert updated_configs[0].owner_public_key == owner_pubkey
