from __future__ import annotations

import asyncio
import dataclasses
from typing import Any, List

import pytest

from chia._tests.environments.wallet import WalletStateTransition, WalletTestFramework
from chia._tests.util.setup_nodes import OldSimulatorsAndWallets
from chia._tests.util.time_out_assert import time_out_assert
from chia.data_layer.data_layer_errors import LauncherCoinNotFoundError
from chia.data_layer.data_layer_wallet import DataLayerWallet, Mirror
from chia.simulator.full_node_simulator import FullNodeSimulator
from chia.simulator.simulator_protocol import FarmNewBlockProtocol, ReorgProtocol
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.peer_info import PeerInfo
from chia.util.ints import uint32, uint64
from chia.util.timing import adjusted_timeout
from chia.wallet.db_wallet.db_wallet_puzzles import create_mirror_puzzle
from chia.wallet.util.merkle_tree import MerkleTree
from chia.wallet.util.tx_config import DEFAULT_TX_CONFIG

pytestmark = pytest.mark.data_layer


async def is_singleton_confirmed(dl_wallet: DataLayerWallet, lid: bytes32) -> bool:
    rec = await dl_wallet.get_latest_singleton(lid)
    if rec is None:
        return False
    if rec.confirmed is True:
        assert rec.confirmed_at_height > 0
        assert rec.timestamp > 0
    return rec.confirmed


class TestDLWallet:
    @pytest.mark.parametrize(
        "trusted,reuse_puzhash",
        [
            (True, True),
            (True, False),
            (False, False),
        ],
    )
    @pytest.mark.anyio
    async def test_initial_creation(
        self, self_hostname: str, simulator_and_wallet: OldSimulatorsAndWallets, trusted: bool, reuse_puzhash: bool
    ) -> None:
        full_nodes, wallets, _ = simulator_and_wallet
        full_node_api = full_nodes[0]
        full_node_server = full_node_api.server
        wallet_node_0, server_0 = wallets[0]
        wallet_0 = wallet_node_0.wallet_state_manager.main_wallet

        if trusted:
            wallet_node_0.config["trusted_peers"] = {full_node_server.node_id.hex(): full_node_server.node_id.hex()}
        else:
            wallet_node_0.config["trusted_peers"] = {}

        await server_0.start_client(PeerInfo(self_hostname, full_node_server.get_port()), None)

        funds = await full_node_api.farm_blocks_to_wallet(count=2, wallet=wallet_0)

        await time_out_assert(10, wallet_0.get_unconfirmed_balance, funds)
        await time_out_assert(10, wallet_0.get_confirmed_balance, funds)

        async with wallet_node_0.wallet_state_manager.lock:
            dl_wallet = await DataLayerWallet.create_new_dl_wallet(wallet_node_0.wallet_state_manager)

        nodes = [Program.to("thing").get_tree_hash(), Program.to([8]).get_tree_hash()]
        current_tree = MerkleTree(nodes)
        current_root = current_tree.calculate_root()

        for i in range(0, 2):
            async with dl_wallet.wallet_state_manager.new_action_scope(
                DEFAULT_TX_CONFIG.override(reuse_puzhash=reuse_puzhash), push=True
            ) as action_scope:
                launcher_id = await dl_wallet.generate_new_reporter(
                    current_root,
                    action_scope,
                    fee=uint64(1999999999999),
                )

            assert await dl_wallet.get_latest_singleton(launcher_id) is not None
            await full_node_api.process_transaction_records(records=action_scope.side_effects.transactions)

            await time_out_assert(15, is_singleton_confirmed, True, dl_wallet, launcher_id)

        await time_out_assert(10, wallet_0.get_unconfirmed_balance, 0)
        await time_out_assert(10, wallet_0.get_confirmed_balance, 0)

        new_puz = await dl_wallet.get_new_puzzle()
        assert new_puz

    @pytest.mark.parametrize(
        "trusted",
        [True, False],
    )
    @pytest.mark.anyio
    async def test_get_owned_singletons(
        self, self_hostname: str, simulator_and_wallet: OldSimulatorsAndWallets, trusted: bool
    ) -> None:
        full_nodes, wallets, _ = simulator_and_wallet
        full_node_api = full_nodes[0]
        full_node_server = full_node_api.server
        wallet_node_0, server_0 = wallets[0]
        wallet_0 = wallet_node_0.wallet_state_manager.main_wallet

        if trusted:
            wallet_node_0.config["trusted_peers"] = {full_node_server.node_id.hex(): full_node_server.node_id.hex()}
        else:
            wallet_node_0.config["trusted_peers"] = {}

        await server_0.start_client(PeerInfo(self_hostname, full_node_server.get_port()), None)

        funds = await full_node_api.farm_blocks_to_wallet(count=2, wallet=wallet_0)

        await time_out_assert(10, wallet_0.get_unconfirmed_balance, funds)
        await time_out_assert(10, wallet_0.get_confirmed_balance, funds)

        async with wallet_node_0.wallet_state_manager.lock:
            dl_wallet = await DataLayerWallet.create_new_dl_wallet(wallet_node_0.wallet_state_manager)

        nodes = [Program.to("thing").get_tree_hash(), Program.to([8]).get_tree_hash()]
        current_tree = MerkleTree(nodes)
        current_root = current_tree.calculate_root()

        expected_launcher_ids = set()

        for i in range(0, 2):
            async with dl_wallet.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
                launcher_id = await dl_wallet.generate_new_reporter(
                    current_root, action_scope, fee=uint64(1999999999999)
                )
            expected_launcher_ids.add(launcher_id)

            assert await dl_wallet.get_latest_singleton(launcher_id) is not None

            await full_node_api.process_transaction_records(records=action_scope.side_effects.transactions)

            await time_out_assert(15, is_singleton_confirmed, True, dl_wallet, launcher_id)

        owned_singletons = await dl_wallet.get_owned_singletons()
        owned_launcher_ids = sorted(singleton.launcher_id for singleton in owned_singletons)
        assert owned_launcher_ids == sorted(expected_launcher_ids)

    @pytest.mark.parametrize("trusted", [True, False])
    @pytest.mark.anyio
    async def test_tracking_non_owned(
        self, self_hostname: str, two_wallet_nodes: OldSimulatorsAndWallets, trusted: bool
    ) -> None:
        full_nodes, wallets, _ = two_wallet_nodes
        full_node_api = full_nodes[0]
        full_node_server = full_node_api.server
        wallet_node_0, server_0 = wallets[0]
        wallet_node_1, server_1 = wallets[1]
        wallet_0 = wallet_node_0.wallet_state_manager.main_wallet

        if trusted:
            wallet_node_0.config["trusted_peers"] = {full_node_server.node_id.hex(): full_node_server.node_id.hex()}
            wallet_node_1.config["trusted_peers"] = {full_node_server.node_id.hex(): full_node_server.node_id.hex()}
        else:
            wallet_node_0.config["trusted_peers"] = {}
            wallet_node_1.config["trusted_peers"] = {}

        await server_0.start_client(PeerInfo(self_hostname, full_node_server.get_port()), None)
        await server_1.start_client(PeerInfo(self_hostname, full_node_server.get_port()), None)

        funds = await full_node_api.farm_blocks_to_wallet(count=2, wallet=wallet_0)

        await time_out_assert(10, wallet_0.get_unconfirmed_balance, funds)
        await time_out_assert(10, wallet_0.get_confirmed_balance, funds)

        async with wallet_node_0.wallet_state_manager.lock:
            dl_wallet_0 = await DataLayerWallet.create_new_dl_wallet(wallet_node_0.wallet_state_manager)

        async with wallet_node_1.wallet_state_manager.lock:
            dl_wallet_1 = await DataLayerWallet.create_new_dl_wallet(wallet_node_1.wallet_state_manager)

        peer = wallet_node_1.get_full_node_peer()

        # Test tracking a launcher id that does not exist
        with pytest.raises(LauncherCoinNotFoundError):
            await dl_wallet_0.track_new_launcher_id(bytes32([1] * 32), peer)

        nodes = [Program.to("thing").get_tree_hash(), Program.to([8]).get_tree_hash()]
        current_tree = MerkleTree(nodes)
        current_root = current_tree.calculate_root()

        async with dl_wallet_0.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
            launcher_id = await dl_wallet_0.generate_new_reporter(current_root, action_scope)

        assert await dl_wallet_0.get_latest_singleton(launcher_id) is not None
        await full_node_api.process_transaction_records(records=action_scope.side_effects.transactions)

        await time_out_assert(15, is_singleton_confirmed, True, dl_wallet_0, launcher_id)
        await asyncio.sleep(0.5)

        await dl_wallet_1.track_new_launcher_id(launcher_id, peer)
        await time_out_assert(15, is_singleton_confirmed, True, dl_wallet_1, launcher_id)
        await asyncio.sleep(0.5)

        for i in range(0, 5):
            new_root = MerkleTree([Program.to("root").get_tree_hash()]).calculate_root()
            async with dl_wallet_0.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
                await dl_wallet_0.create_update_state_spend(launcher_id, new_root, action_scope)

            await full_node_api.process_transaction_records(records=action_scope.side_effects.transactions)

            await time_out_assert(15, is_singleton_confirmed, True, dl_wallet_0, launcher_id)

        async def do_tips_match() -> bool:
            latest_singleton_0 = await dl_wallet_0.get_latest_singleton(launcher_id)
            latest_singleton_1 = await dl_wallet_1.get_latest_singleton(launcher_id)
            return latest_singleton_0 == latest_singleton_1

        await time_out_assert(15, do_tips_match, True)

        await dl_wallet_1.stop_tracking_singleton(launcher_id)
        assert await dl_wallet_1.get_latest_singleton(launcher_id) is None

        await dl_wallet_1.track_new_launcher_id(launcher_id, peer)
        await time_out_assert(15, do_tips_match, True)

    @pytest.mark.parametrize(
        "trusted",
        [True, False],
    )
    @pytest.mark.anyio
    async def test_lifecycle(
        self, self_hostname: str, simulator_and_wallet: OldSimulatorsAndWallets, trusted: bool
    ) -> None:
        full_nodes, wallets, _ = simulator_and_wallet
        full_node_api = full_nodes[0]
        full_node_server = full_node_api.server
        wallet_node_0, server_0 = wallets[0]
        wallet_0 = wallet_node_0.wallet_state_manager.main_wallet

        if trusted:
            wallet_node_0.config["trusted_peers"] = {full_node_server.node_id.hex(): full_node_server.node_id.hex()}
        else:
            wallet_node_0.config["trusted_peers"] = {}

        await server_0.start_client(PeerInfo(self_hostname, full_node_server.get_port()), None)

        funds = await full_node_api.farm_blocks_to_wallet(count=5, wallet=wallet_0)

        await time_out_assert(10, wallet_0.get_unconfirmed_balance, funds)
        await time_out_assert(10, wallet_0.get_confirmed_balance, funds)

        async with wallet_node_0.wallet_state_manager.lock:
            dl_wallet = await DataLayerWallet.create_new_dl_wallet(wallet_node_0.wallet_state_manager)

        nodes = [Program.to("thing").get_tree_hash(), Program.to([8]).get_tree_hash()]
        current_tree = MerkleTree(nodes)
        current_root = current_tree.calculate_root()

        async with dl_wallet.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=False) as action_scope:
            launcher_id = await dl_wallet.generate_new_reporter(current_root, action_scope)

        assert await dl_wallet.get_latest_singleton(launcher_id) is not None

        [std_record] = await wallet_node_0.wallet_state_manager.add_pending_transactions(
            action_scope.side_effects.transactions
        )
        await full_node_api.process_transaction_records(records=[std_record])

        await time_out_assert(15, is_singleton_confirmed, True, dl_wallet, launcher_id)

        previous_record = await dl_wallet.get_latest_singleton(launcher_id)
        assert previous_record is not None
        assert previous_record.lineage_proof.amount is not None

        new_root = MerkleTree([Program.to("root").get_tree_hash()]).calculate_root()

        async with dl_wallet.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=False) as action_scope:
            await dl_wallet.generate_signed_transaction(
                [previous_record.lineage_proof.amount],
                [previous_record.inner_puzzle_hash],
                action_scope,
                launcher_id=previous_record.launcher_id,
                new_root_hash=new_root,
                fee=uint64(1999999999999),
            )
        assert action_scope.side_effects.transactions[0].spend_bundle is not None
        with pytest.raises(ValueError, match="is currently pending"):
            async with dl_wallet.wallet_state_manager.new_action_scope(
                DEFAULT_TX_CONFIG, push=False
            ) as failed_action_scope:
                await dl_wallet.generate_signed_transaction(
                    [previous_record.lineage_proof.amount],
                    [previous_record.inner_puzzle_hash],
                    failed_action_scope,
                    coins={
                        next(
                            rem
                            for rem in action_scope.side_effects.transactions[0].spend_bundle.removals()
                            if rem.amount == 1
                        )
                    },
                    fee=uint64(1999999999999),
                )

        new_record = await dl_wallet.get_latest_singleton(launcher_id)
        assert new_record is not None
        assert new_record != previous_record
        assert not new_record.confirmed

        txs = await wallet_node_0.wallet_state_manager.add_pending_transactions(action_scope.side_effects.transactions)
        await full_node_api.process_transaction_records(records=txs)

        await time_out_assert(15, is_singleton_confirmed, True, dl_wallet, launcher_id)
        await time_out_assert(10, wallet_0.get_unconfirmed_balance, funds - 2000000000000)
        await time_out_assert(10, wallet_0.get_confirmed_balance, funds - 2000000000000)
        await asyncio.sleep(0.5)

        dl_coin_record = await dl_wallet.wallet_state_manager.coin_store.get_coin_record(new_record.coin_id)
        assert dl_coin_record is not None
        assert await dl_wallet.match_hinted_coin(dl_coin_record.coin, new_record.launcher_id)

        previous_record = await dl_wallet.get_latest_singleton(launcher_id)

        new_root = MerkleTree([Program.to("new root").get_tree_hash()]).calculate_root()
        async with dl_wallet.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=False) as action_scope:
            await dl_wallet.create_update_state_spend(launcher_id, new_root, action_scope)
        new_record = await dl_wallet.get_latest_singleton(launcher_id)
        assert new_record is not None
        assert new_record != previous_record
        assert not new_record.confirmed

        txs = await wallet_node_0.wallet_state_manager.add_pending_transactions(action_scope.side_effects.transactions)
        await full_node_api.process_transaction_records(records=txs)

        await time_out_assert(15, is_singleton_confirmed, True, dl_wallet, launcher_id)
        await asyncio.sleep(0.5)

    @pytest.mark.skip(reason="maybe no longer relevant, needs to be rewritten at least")
    @pytest.mark.parametrize(
        "trusted",
        [True, False],
    )
    @pytest.mark.anyio
    async def test_rebase(
        self,
        self_hostname: str,
        two_wallet_nodes: OldSimulatorsAndWallets,
        trusted: bool,
    ) -> None:  # pragma: no cover
        full_nodes, wallets, _ = two_wallet_nodes
        full_node_api = full_nodes[0]
        full_node_server = full_node_api.server
        wallet_node_0, server_0 = wallets[0]
        wallet_node_1, server_1 = wallets[1]
        wallet_0 = wallet_node_0.wallet_state_manager.main_wallet
        wallet_1 = wallet_node_1.wallet_state_manager.main_wallet

        if trusted:
            wallet_node_0.config["trusted_peers"] = {full_node_server.node_id.hex(): full_node_server.node_id.hex()}
            wallet_node_1.config["trusted_peers"] = {full_node_server.node_id.hex(): full_node_server.node_id.hex()}
        else:
            wallet_node_0.config["trusted_peers"] = {}
            wallet_node_1.config["trusted_peers"] = {}

        await server_0.start_client(PeerInfo(self_hostname, full_node_server.get_port()), None)
        await server_1.start_client(PeerInfo(self_hostname, full_node_server.get_port()), None)

        funds = await full_node_api.farm_blocks_to_wallet(count=5, wallet=wallet_0)
        await full_node_api.farm_blocks_to_wallet(count=5, wallet=wallet_1)

        await time_out_assert(10, wallet_0.get_unconfirmed_balance, funds)
        await time_out_assert(10, wallet_0.get_confirmed_balance, funds)
        await time_out_assert(10, wallet_1.get_unconfirmed_balance, funds)
        await time_out_assert(10, wallet_1.get_confirmed_balance, funds)

        async with wallet_node_0.wallet_state_manager.lock:
            dl_wallet_0 = await DataLayerWallet.create_new_dl_wallet(wallet_node_0.wallet_state_manager)

        async with wallet_node_1.wallet_state_manager.lock:
            dl_wallet_1 = await DataLayerWallet.create_new_dl_wallet(wallet_node_1.wallet_state_manager)

        nodes = [Program.to("thing").get_tree_hash(), Program.to([8]).get_tree_hash()]
        current_tree = MerkleTree(nodes)
        current_root = current_tree.calculate_root()

        async def is_singleton_confirmed(wallet: DataLayerWallet, lid: bytes32) -> bool:
            latest_singleton = await wallet.get_latest_singleton(lid)
            if latest_singleton is None:
                return False
            return latest_singleton.confirmed

        async with dl_wallet_0.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=False) as action_scope:
            launcher_id = await dl_wallet_0.generate_new_reporter(current_root, action_scope)

        initial_record = await dl_wallet_0.get_latest_singleton(launcher_id)
        assert initial_record is not None

        [std_record] = await wallet_node_0.wallet_state_manager.add_pending_transactions(
            action_scope.side_effects.transactions
        )
        await asyncio.wait_for(
            full_node_api.process_transaction_records(records=[std_record]),
            timeout=adjusted_timeout(timeout=15),
        )

        await time_out_assert(15, is_singleton_confirmed, True, dl_wallet_0, launcher_id)
        await asyncio.sleep(0.5)

        peer = wallet_node_1.get_full_node_peer()
        await dl_wallet_1.track_new_launcher_id(launcher_id, peer)
        await time_out_assert(15, is_singleton_confirmed, True, dl_wallet_1, launcher_id)
        current_record = await dl_wallet_1.get_latest_singleton(launcher_id)
        assert current_record is not None
        await asyncio.sleep(0.5)

        # Because these have the same fee, the one that gets pushed first will win
        async with dl_wallet_1.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
            await dl_wallet_1.create_update_state_spend(
                launcher_id, current_record.root, action_scope, fee=uint64(2000000000000)
            )
        report_txs = action_scope.side_effects.transactions
        record_1 = await dl_wallet_1.get_latest_singleton(launcher_id)
        assert record_1 is not None
        assert current_record != record_1
        async with dl_wallet_0.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
            await dl_wallet_0.create_update_state_spend(
                launcher_id, bytes32([0] * 32), action_scope, fee=uint64(2000000000000)
            )
        update_txs = action_scope.side_effects.transactions
        record_0 = await dl_wallet_0.get_latest_singleton(launcher_id)
        assert record_0 is not None
        assert initial_record != record_0
        assert record_0 != record_1

        report_txs = await wallet_node_1.wallet_state_manager.add_pending_transactions(report_txs)

        await asyncio.wait_for(
            full_node_api.wait_transaction_records_entered_mempool(records=report_txs),
            timeout=adjusted_timeout(timeout=15),
        )

        update_txs = await wallet_node_0.wallet_state_manager.add_pending_transactions(update_txs)

        await asyncio.wait_for(
            full_node_api.process_transaction_records(records=report_txs), timeout=adjusted_timeout(timeout=15)
        )

        funds -= 2000000000001

        async def is_singleton_generation(wallet: DataLayerWallet, launcher_id: bytes32, generation: int) -> bool:
            latest = await wallet.get_latest_singleton(launcher_id)
            if latest is not None and latest.generation == generation:
                return True
            return False

        next_generation = current_record.generation + 2
        await time_out_assert(15, is_singleton_generation, True, dl_wallet_0, launcher_id, next_generation)

        for i in range(0, 2):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(bytes32(32 * b"0")))
            await asyncio.sleep(0.5)

        await time_out_assert(15, is_singleton_confirmed, True, dl_wallet_0, launcher_id)
        await time_out_assert(15, is_singleton_generation, True, dl_wallet_1, launcher_id, next_generation)
        latest = await dl_wallet_0.get_latest_singleton(launcher_id)
        assert latest is not None
        assert latest == (await dl_wallet_1.get_latest_singleton(launcher_id))
        await time_out_assert(15, wallet_0.get_confirmed_balance, funds)
        await time_out_assert(15, wallet_0.get_unconfirmed_balance, funds)
        assert (
            len(
                await dl_wallet_0.get_history(
                    launcher_id, min_generation=uint32(next_generation - 1), max_generation=uint32(next_generation - 1)
                )
            )
            == 1
        )
        for tx in update_txs:
            assert await wallet_node_0.wallet_state_manager.tx_store.get_transaction_record(tx.name) is None
        assert await dl_wallet_0.get_singleton_record(record_0.coin_id) is None

        async with dl_wallet_0.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=False) as action_scope:
            await dl_wallet_0.create_update_state_spend(
                launcher_id, bytes32([1] * 32), action_scope, fee=uint64(2000000000000)
            )
        record_1 = await dl_wallet_0.get_latest_singleton(launcher_id)
        assert record_1 is not None
        update_txs_1 = await wallet_node_0.wallet_state_manager.add_pending_transactions(
            action_scope.side_effects.transactions
        )
        await full_node_api.wait_transaction_records_entered_mempool(update_txs_1)

        # Delete any trace of that update
        await wallet_node_0.wallet_state_manager.dl_store.delete_singleton_record(record_1.coin_id)
        for tx in update_txs_1:
            await wallet_node_0.wallet_state_manager.tx_store.delete_transaction_record(tx.name)

        async with dl_wallet_0.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=False) as action_scope:
            await dl_wallet_0.create_update_state_spend(launcher_id, bytes32([2] * 32), action_scope)
        record_0 = await dl_wallet_0.get_latest_singleton(launcher_id)
        assert record_0 is not None
        assert record_0 != record_1

        update_txs_0 = await wallet_node_0.wallet_state_manager.add_pending_transactions(
            action_scope.side_effects.transactions
        )

        await asyncio.wait_for(
            full_node_api.process_transaction_records(records=update_txs_1), timeout=adjusted_timeout(timeout=15)
        )

        async def does_singleton_have_root(wallet: DataLayerWallet, lid: bytes32, root: bytes32) -> bool:
            latest_singleton = await wallet.get_latest_singleton(lid)
            if latest_singleton is None:
                return False
            return latest_singleton.root == root

        funds -= 2000000000000

        next_generation += 1
        await time_out_assert(15, is_singleton_generation, True, dl_wallet_0, launcher_id, next_generation)
        await time_out_assert(15, does_singleton_have_root, True, dl_wallet_0, launcher_id, bytes32([1] * 32))
        await time_out_assert(15, wallet_0.get_confirmed_balance, funds)
        await time_out_assert(15, wallet_0.get_unconfirmed_balance, funds)
        assert (
            len(
                await dl_wallet_0.get_history(
                    launcher_id, min_generation=uint32(next_generation), max_generation=uint32(next_generation)
                )
            )
            == 1
        )
        for tx in update_txs_0:
            assert await wallet_node_0.wallet_state_manager.tx_store.get_transaction_record(tx.name) is None
        assert await dl_wallet_0.get_singleton_record(record_0.coin_id) is None


async def is_singleton_confirmed_and_root(dl_wallet: DataLayerWallet, lid: bytes32, root: bytes32) -> bool:
    rec = await dl_wallet.get_latest_singleton(lid)
    if rec is None:
        return False
    if rec.confirmed is True:
        assert rec.confirmed_at_height > 0
        assert rec.timestamp > 0
    return rec.confirmed and rec.root == root


@pytest.mark.parametrize(
    "trusted",
    [True, False],
)
@pytest.mark.anyio
async def test_mirrors(wallets_prefarm: Any, trusted: bool) -> None:
    (
        [wallet_node_1, _],
        [wallet_node_2, _],
        full_node_api,
    ) = wallets_prefarm
    assert wallet_node_1.wallet_state_manager is not None
    assert wallet_node_2.wallet_state_manager is not None
    wsm_1 = wallet_node_1.wallet_state_manager
    wsm_2 = wallet_node_2.wallet_state_manager

    async with wsm_1.lock:
        dl_wallet_1 = await DataLayerWallet.create_new_dl_wallet(wsm_1)
    async with wsm_2.lock:
        dl_wallet_2 = await DataLayerWallet.create_new_dl_wallet(wsm_2)

    async with dl_wallet_1.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
        launcher_id_1 = await dl_wallet_1.generate_new_reporter(bytes32([0] * 32), action_scope)
    assert await dl_wallet_1.get_latest_singleton(launcher_id_1) is not None
    await full_node_api.process_transaction_records(records=action_scope.side_effects.transactions)
    await time_out_assert(15, is_singleton_confirmed_and_root, True, dl_wallet_1, launcher_id_1, bytes32([0] * 32))

    async with dl_wallet_2.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
        launcher_id_2 = await dl_wallet_2.generate_new_reporter(bytes32([0] * 32), action_scope)
    assert await dl_wallet_2.get_latest_singleton(launcher_id_2) is not None
    await full_node_api.process_transaction_records(records=action_scope.side_effects.transactions)
    await time_out_assert(15, is_singleton_confirmed_and_root, True, dl_wallet_2, launcher_id_2, bytes32([0] * 32))

    peer_1 = wallet_node_1.get_full_node_peer()
    await dl_wallet_1.track_new_launcher_id(launcher_id_2, peer_1)
    peer_2 = wallet_node_2.get_full_node_peer()
    await dl_wallet_2.track_new_launcher_id(launcher_id_1, peer_2)
    await time_out_assert(15, is_singleton_confirmed_and_root, True, dl_wallet_1, launcher_id_2, bytes32([0] * 32))
    await time_out_assert(15, is_singleton_confirmed_and_root, True, dl_wallet_2, launcher_id_1, bytes32([0] * 32))

    async with dl_wallet_1.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
        await dl_wallet_1.create_new_mirror(
            launcher_id_2, uint64(3), [b"foo", b"bar"], action_scope, fee=uint64(1_999_999_999_999)
        )
    additions: List[Coin] = []
    for tx in action_scope.side_effects.transactions:
        if tx.spend_bundle is not None:
            additions.extend(tx.spend_bundle.additions())
    await full_node_api.process_transaction_records(records=action_scope.side_effects.transactions)

    mirror_coin: Coin = [c for c in additions if c.puzzle_hash == create_mirror_puzzle().get_tree_hash()][0]
    mirror = Mirror(
        bytes32(mirror_coin.name()),
        bytes32(launcher_id_2),
        uint64(mirror_coin.amount),
        [b"foo", b"bar"],
        True,
        full_node_api.full_node.blockchain.get_peak_height(),
    )
    await time_out_assert(15, dl_wallet_1.get_mirrors_for_launcher, [mirror], launcher_id_2)
    await time_out_assert(
        15, dl_wallet_2.get_mirrors_for_launcher, [dataclasses.replace(mirror, ours=False)], launcher_id_2
    )

    async with dl_wallet_1.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
        await dl_wallet_1.delete_mirror(mirror.coin_id, peer_1, action_scope, fee=uint64(2_000_000_000_000))
    await full_node_api.process_transaction_records(records=action_scope.side_effects.transactions)

    await time_out_assert(15, dl_wallet_1.get_mirrors_for_launcher, [], launcher_id_2)
    await time_out_assert(15, dl_wallet_2.get_mirrors_for_launcher, [], launcher_id_2)


@pytest.mark.parametrize(
    "wallet_environments",
    [
        {
            "num_environments": 1,
            "blocks_needed": [1],
            "reuse_puzhash": True,
        }
    ],
    indirect=True,
)
@pytest.mark.limit_consensus_modes(reason="irrelevant")
@pytest.mark.anyio
async def test_datalayer_reorgs(wallet_environments: WalletTestFramework) -> None:
    # Setup
    full_node_api: FullNodeSimulator = wallet_environments.full_node
    env = wallet_environments.environments[0]
    wallet_node = wallet_environments.environments[0].node

    # Define wallet aliases
    env.wallet_aliases = {
        "xch": 1,
        "dl": 2,
    }

    async with env.wallet_state_manager.lock:
        dl_wallet = await DataLayerWallet.create_new_dl_wallet(env.wallet_state_manager)

    async with dl_wallet.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
        launcher_id = await dl_wallet.generate_new_reporter(bytes32([0] * 32), action_scope)

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {
                        "unconfirmed_wallet_balance": -1,
                        "<=#spendable_balance": -1,  # any amount decrease
                        "<=#max_send_amount": -1,  # any amount decrease
                        ">=#pending_change": 1,  # any amount increase
                        "pending_coin_removal_count": 1,
                    },
                    "dl": {"init": True},
                },
                post_block_balance_updates={
                    "xch": {
                        "confirmed_wallet_balance": -1,
                        ">=#spendable_balance": 1,  # any amount increase
                        ">=#max_send_amount": 1,  # any amount increase
                        "<=#pending_change": -1,  # any amount decrease
                        "pending_coin_removal_count": -1,
                    },
                    "dl": {"unspent_coin_count": 1},
                },
            )
        ]
    )
    await time_out_assert(15, is_singleton_confirmed_and_root, True, dl_wallet, launcher_id, bytes32([0] * 32))

    height = full_node_api.full_node.blockchain.get_peak_height()
    assert height is not None
    await full_node_api.reorg_from_index_to_new_index(
        ReorgProtocol(uint32(height - 1), uint32(height + 1), bytes32([0] * 32), None)
    )
    await full_node_api.wait_for_wallet_synced(wallet_node=wallet_node, timeout=5)

    await time_out_assert(15, is_singleton_confirmed_and_root, False, dl_wallet, launcher_id, bytes32([0] * 32))

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {
                        "confirmed_wallet_balance": 1,  # confirmed balance comes back
                        "<=#spendable_balance": -1,  # any amount decrease
                        "<=#max_send_amount": -1,  # any amount decrease
                        ">=#pending_change": 1,  # any amount increase
                        "pending_coin_removal_count": 1,
                    },
                    "dl": {"unspent_coin_count": -1},
                },
                post_block_balance_updates={
                    "xch": {
                        "confirmed_wallet_balance": -1,
                        ">=#spendable_balance": 1,  # any amount increase
                        ">=#max_send_amount": 1,  # any amount increase
                        "<=#pending_change": -1,  # any amount decrease
                        "pending_coin_removal_count": -1,
                    },
                    "dl": {"unspent_coin_count": 1},
                },
            )
        ]
    )
    await time_out_assert(15, is_singleton_confirmed_and_root, True, dl_wallet, launcher_id, bytes32([0] * 32))

    async with dl_wallet.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
        await dl_wallet.create_update_state_spend(launcher_id, bytes32([2] * 32), action_scope)

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {},
                    "dl": {"pending_coin_removal_count": 1},
                },
                post_block_balance_updates={
                    "xch": {},
                    "dl": {"pending_coin_removal_count": -1},
                },
            )
        ]
    )
    await time_out_assert(15, is_singleton_confirmed_and_root, True, dl_wallet, launcher_id, bytes32([2] * 32))

    height = full_node_api.full_node.blockchain.get_peak_height()
    assert height is not None
    await full_node_api.reorg_from_index_to_new_index(
        ReorgProtocol(uint32(height - 1), uint32(height + 1), bytes32([0] * 32), None)
    )
    await full_node_api.wait_for_wallet_synced(wallet_node=wallet_node, timeout=5)

    await time_out_assert(15, is_singleton_confirmed_and_root, False, dl_wallet, launcher_id, bytes32([0] * 32))

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {},
                    "dl": {"pending_coin_removal_count": 1},
                },
                post_block_balance_updates={
                    "xch": {},
                    "dl": {"pending_coin_removal_count": -1},
                },
            )
        ]
    )
    await time_out_assert(15, is_singleton_confirmed_and_root, True, dl_wallet, launcher_id, bytes32([2] * 32))

    async with dl_wallet.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
        await dl_wallet.create_new_mirror(launcher_id, uint64(0), [b"foo", b"bar"], action_scope)
    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {
                        "<=#spendable_balance": -1,  # any amount decrease
                        "<=#max_send_amount": -1,  # any amount decrease
                        ">=#pending_change": 1,  # any amount increase
                        "pending_coin_removal_count": 1,
                    },
                    "dl": {},
                },
                post_block_balance_updates={
                    "xch": {
                        ">=#spendable_balance": 1,  # any amount increase
                        ">=#max_send_amount": 1,  # any amount increase
                        "<=#pending_change": -1,  # any amount decrease
                        "pending_coin_removal_count": -1,
                    },
                    "dl": {"unspent_coin_count": 1},
                },
            )
        ]
    )
    assert len(await dl_wallet.get_mirrors_for_launcher(launcher_id)) == 1

    height = full_node_api.full_node.blockchain.get_peak_height()
    assert height is not None
    await full_node_api.reorg_from_index_to_new_index(
        ReorgProtocol(uint32(height - 1), uint32(height + 1), bytes32([0] * 32), None)
    )
    await full_node_api.wait_for_wallet_synced(wallet_node=wallet_node, timeout=5)

    assert len(await dl_wallet.get_mirrors_for_launcher(launcher_id)) == 0

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {
                        "<=#spendable_balance": -1,  # any amount decrease
                        "<=#max_send_amount": -1,  # any amount decrease
                        ">=#pending_change": 1,  # any amount increase
                        "pending_coin_removal_count": 1,
                    },
                    "dl": {"unspent_coin_count": -1},
                },
                post_block_balance_updates={
                    "xch": {
                        ">=#spendable_balance": 1,  # any amount increase
                        ">=#max_send_amount": 1,  # any amount increase
                        "<=#pending_change": -1,  # any amount decrease
                        "pending_coin_removal_count": -1,
                    },
                    "dl": {"unspent_coin_count": 1},
                },
            )
        ]
    )
    assert len(await dl_wallet.get_mirrors_for_launcher(launcher_id)) == 1
