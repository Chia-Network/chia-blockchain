from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, AsyncIterator, ClassVar, Dict, List, Optional, Set, Type

import pytest
from blspy import G1Element
from chia_rs import Coin

from chia.server.ws_connection import WSChiaConnection
from chia.simulator.setup_nodes import SimulatorsAndWallets
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.ints import uint32, uint64, uint128
from chia.wallet.util.wallet_types import WalletType
from chia.wallet.wallet_coin_record import WalletCoinRecord
from chia.wallet.wallet_info import WalletInfo
from chia.wallet.wallet_state_manager import WalletStateManager
from tests.pools.test_wallet_pool_store import DummySpends
from tests.wallet.test_nft_store import DummyNFTs
from tests.wallet.test_wallet_coin_store import DummyWalletCoinRecords


@dataclass
class DummyWallet:
    wallet_type: ClassVar[WalletType]
    wallet_info: WalletInfo
    wallet_state_manager: WalletStateManager

    @classmethod
    def type(cls) -> WalletType:
        return cls.wallet_type

    def id(self) -> uint32:
        return self.wallet_info.id

    async def coin_added(self, coin: Coin, height: uint32, peer: WSChiaConnection) -> None:
        raise Exception("Not supported for DummyWallet")

    async def select_coins(
        self,
        amount: uint64,
        exclude: Optional[List[Coin]] = None,
        min_coin_amount: Optional[uint64] = None,
        max_coin_amount: Optional[uint64] = None,
        excluded_coin_amounts: Optional[List[uint64]] = None,
    ) -> Set[Coin]:
        raise Exception("Not supported for DummyWallet")

    async def get_confirmed_balance(self, record_list: Optional[Set[WalletCoinRecord]] = None) -> uint128:
        raise Exception("Not supported for DummyWallet")

    async def get_unconfirmed_balance(self, unspent_records: Optional[Set[WalletCoinRecord]] = None) -> uint128:
        raise Exception("Not supported for DummyWallet")

    async def get_spendable_balance(self, unspent_records: Optional[Set[WalletCoinRecord]] = None) -> uint128:
        raise Exception("Not supported for DummyWallet")

    async def get_pending_change_balance(self) -> uint64:
        raise Exception("Not supported for DummyWallet")

    async def get_max_send_amount(self, records: Optional[Set[WalletCoinRecord]] = None) -> uint128:
        raise Exception("Not supported for DummyWallet")

    def puzzle_hash_for_pk(self, pubkey: G1Element) -> bytes32:
        return bytes32(bytes(pubkey)[:32])

    def require_derivation_paths(self) -> bool:
        return self.wallet_type in {WalletType.STANDARD_WALLET, WalletType.CAT, WalletType.DECENTRALIZED_ID}

    def get_name(self) -> str:
        raise Exception("Not supported for DummyWallet")


@dataclass
class DummyPoolWallet(DummyWallet):
    wallet_type = WalletType.POOLING_WALLET


@dataclass
class DummyCATWallet(DummyWallet):
    wallet_type = WalletType.CAT


@dataclass
class DummyNFTWallet(DummyWallet):
    wallet_type = WalletType.NFT


async def generate_dummy_wallet(
    wallet_state_manager: WalletStateManager, wallet_id: int, wallet_class: Type[DummyWallet]
) -> DummyWallet:
    wallet_info = await wallet_state_manager.user_store.create_wallet(str(wallet_id), wallet_class.wallet_type, "")
    dummy_wallet = wallet_class(wallet_info, wallet_state_manager)
    await wallet_state_manager.add_new_wallet(dummy_wallet)

    dummy_coin_records = DummyWalletCoinRecords()
    dummy_coin_records.generate(wallet_id, 10)
    for wallet_id, coin_records in dummy_coin_records.records_per_wallet.items():
        for record in coin_records:
            await wallet_state_manager.coin_store.add_coin_record(record)

    if wallet_class == DummyPoolWallet:
        dummy_spends = DummySpends()
        dummy_spends.generate(dummy_wallet.id(), 10)
        for wallet_id, spends in dummy_spends.spends_per_wallet.items():
            for i, spend in enumerate(spends):
                await wallet_state_manager.pool_store.add_spend(wallet_id, spend, uint32(i))
    if wallet_class == DummyNFTWallet:
        dummy_nfts = DummyNFTs()
        dummy_nfts.generate(dummy_wallet.id(), 10)
        for wallet_id, nfts in dummy_nfts.nfts_per_wallet.items():
            for nft in nfts:
                await wallet_state_manager.nft_store.save_nft(wallet_id, None, nft)

    return dummy_wallet


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


@pytest.mark.parametrize("remove_cache", [True, False])
@pytest.mark.parametrize("trigger_state_changed", [True, False])
@pytest.mark.asyncio
async def test_remove_wallet(
    simulator_and_wallet: SimulatorsAndWallets, remove_cache: bool, trigger_state_changed: bool
) -> None:
    _, [(wallet_node, _)], _ = simulator_and_wallet
    wallet_state_manager = wallet_node.wallet_state_manager

    dummy_wallets = [
        await generate_dummy_wallet(wallet_state_manager, 2, DummyCATWallet),
        await generate_dummy_wallet(wallet_state_manager, 3, DummyPoolWallet),
        await generate_dummy_wallet(wallet_state_manager, 4, DummyNFTWallet),
    ]

    for wallet in dummy_wallets:
        state_changed = False
        assert wallet.id() in wallet_state_manager.wallets

        if wallet.require_derivation_paths():
            last_derivation_record = await wallet_state_manager.puzzle_store.get_last_derivation_path_for_wallet(
                wallet.id()
            )
            assert last_derivation_record == wallet_state_manager.initial_num_public_keys - 1

        if type(wallet) == DummyPoolWallet:
            assert len(await wallet_state_manager.pool_store.get_spends_for_wallet(wallet.id())) > 0
        if type(wallet) == DummyNFTWallet:
            assert await wallet_state_manager.nft_store.count(wallet.id()) > 0

        def state_changed_callback(change: str, change_data: Optional[Dict[str, Any]]) -> None:
            nonlocal state_changed
            assert change == "wallet_removed"
            assert change_data == {
                "state": change,
                "wallet_id": wallet.id(),
            }
            state_changed = True

        wallet_state_manager.set_callback(state_changed_callback)
        await wallet_state_manager.remove_wallet(
            wallet.id(), remove_cache=remove_cache, trigger_state_changed=trigger_state_changed
        )
        assert state_changed == trigger_state_changed
        assert (wallet.id() in wallet_state_manager.wallets) == (not remove_cache)
        assert await wallet_state_manager.puzzle_store.get_last_derivation_path_for_wallet(wallet.id()) is None
        assert await wallet_state_manager.nft_store.count(wallet.id()) == 0
        assert await wallet_state_manager.pool_store.get_spends_for_wallet(wallet.id()) == []
        assert (await wallet_state_manager.coin_store.get_coin_records(wallet_id=wallet.id())).records == []


@pytest.mark.parametrize("remove_cache", [True, False])
@pytest.mark.parametrize("trigger_state_changed", [True, False])
@pytest.mark.asyncio
async def test_remove_wallet_invalid_wallet_id(
    simulator_and_wallet: SimulatorsAndWallets,
    caplog: pytest.LogCaptureFixture,
    remove_cache: bool,
    trigger_state_changed: bool,
) -> None:
    _, [(wallet_node, _)], _ = simulator_and_wallet
    wallet_state_manager = wallet_node.wallet_state_manager
    state_changed = False

    def state_changed_callback(_: str, __: Optional[Dict[str, Any]]) -> None:
        nonlocal state_changed
        state_changed = True

    wallet_state_manager.set_callback(state_changed_callback)

    with caplog.at_level(logging.WARNING):
        await wallet_state_manager.remove_wallet(
            uint32(10), remove_cache=remove_cache, trigger_state_changed=trigger_state_changed
        )

    assert ("Tried to remove non-existing wallet_id: 10" in caplog.text) == remove_cache
    assert state_changed == (not remove_cache and trigger_state_changed)
