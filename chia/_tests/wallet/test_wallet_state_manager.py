from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator, List

import pytest
from chia_rs import G2Element

from chia._tests.environments.wallet import WalletStateTransition, WalletTestFramework
from chia._tests.util.setup_nodes import OldSimulatorsAndWallets
from chia.protocols.wallet_protocol import CoinState
from chia.server.outbound_message import NodeType
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_spend import make_spend
from chia.types.peer_info import PeerInfo
from chia.util.ints import uint32, uint64
from chia.wallet.derivation_record import DerivationRecord
from chia.wallet.derive_keys import master_sk_to_wallet_sk, master_sk_to_wallet_sk_unhardened
from chia.wallet.transaction_record import TransactionRecord
from chia.wallet.util.transaction_type import TransactionType
from chia.wallet.util.wallet_types import WalletType
from chia.wallet.wallet_spend_bundle import WalletSpendBundle
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


@pytest.mark.anyio
async def test_set_sync_mode(simulator_and_wallet: OldSimulatorsAndWallets) -> None:
    _, [(wallet_node, _)], _ = simulator_and_wallet
    async with assert_sync_mode(wallet_node.wallet_state_manager, uint32(1)):
        pass
    async with assert_sync_mode(wallet_node.wallet_state_manager, uint32(22)):
        pass
    async with assert_sync_mode(wallet_node.wallet_state_manager, uint32(333)):
        pass


@pytest.mark.anyio
async def test_set_sync_mode_exception(simulator_and_wallet: OldSimulatorsAndWallets) -> None:
    _, [(wallet_node, _)], _ = simulator_and_wallet
    async with assert_sync_mode(wallet_node.wallet_state_manager, uint32(1)):
        raise Exception


@pytest.mark.parametrize("hardened", [True, False])
@pytest.mark.anyio
async def test_get_private_key(simulator_and_wallet: OldSimulatorsAndWallets, hardened: bool) -> None:
    _, [(wallet_node, _)], _ = simulator_and_wallet
    wallet_state_manager: WalletStateManager = wallet_node.wallet_state_manager
    derivation_index = uint32(10000)
    conversion_method = master_sk_to_wallet_sk if hardened else master_sk_to_wallet_sk_unhardened
    expected_private_key = conversion_method(wallet_state_manager.get_master_private_key(), derivation_index)
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


@pytest.mark.anyio
async def test_get_private_key_failure(simulator_and_wallet: OldSimulatorsAndWallets) -> None:
    _, [(wallet_node, _)], _ = simulator_and_wallet
    wallet_state_manager: WalletStateManager = wallet_node.wallet_state_manager
    invalid_puzzle_hash = bytes32(b"1" * 32)
    with pytest.raises(ValueError, match=f"No key for puzzle hash: {invalid_puzzle_hash.hex()}"):
        await wallet_state_manager.get_private_key(bytes32(b"1" * 32))


@pytest.mark.anyio
async def test_determine_coin_type(simulator_and_wallet: OldSimulatorsAndWallets, self_hostname: str) -> None:
    full_nodes, wallets, _ = simulator_and_wallet
    full_node_api = full_nodes[0]
    full_node_server = full_node_api.full_node.server
    wallet_node, wallet_server = wallets[0]
    await wallet_server.start_client(PeerInfo(self_hostname, full_node_server.get_port()), None)
    wallet_state_manager: WalletStateManager = wallet_node.wallet_state_manager
    peer = wallet_node.server.get_connections(NodeType.FULL_NODE)[0]
    assert (None, None) == await wallet_state_manager.determine_coin_type(
        peer, CoinState(Coin(bytes32(b"1" * 32), bytes32(b"1" * 32), uint64(0)), uint32(0), uint32(0)), None
    )


@pytest.mark.parametrize(
    "wallet_environments",
    [{"num_environments": 1, "blocks_needed": [1], "trusted": True, "reuse_puzhash": True}],
    indirect=True,
)
@pytest.mark.limit_consensus_modes(reason="irrelevant")
@pytest.mark.anyio
async def test_commit_transactions_to_db(wallet_environments: WalletTestFramework) -> None:
    env = wallet_environments.environments[0]
    wsm = env.wallet_state_manager

    async with wsm.new_action_scope(
        wallet_environments.tx_config,
        push=False,
        merge_spends=False,
        sign=False,
        extra_spends=[],
    ) as action_scope:
        coins = list(await wsm.main_wallet.select_coins(uint64(2_000_000_000_000), action_scope))
        await wsm.main_wallet.generate_signed_transaction(
            uint64(0),
            bytes32([0] * 32),
            action_scope,
            coins={coins[0]},
        )
        await wsm.main_wallet.generate_signed_transaction(
            uint64(0),
            bytes32([0] * 32),
            action_scope,
            coins={coins[1]},
        )

    created_txs = action_scope.side_effects.transactions

    def flatten_spend_bundles(txs: List[TransactionRecord]) -> List[WalletSpendBundle]:
        return [tx.spend_bundle for tx in txs if tx.spend_bundle is not None]

    assert (
        len(await wsm.tx_store.get_all_transactions_for_wallet(wsm.main_wallet.id(), type=TransactionType.OUTGOING_TX))
        == 0
    )

    bundles = flatten_spend_bundles(created_txs)
    assert len(bundles) == 2
    for bundle in bundles:
        assert bundle.aggregated_signature == G2Element()
    assert (
        len(await wsm.tx_store.get_all_transactions_for_wallet(wsm.main_wallet.id(), type=TransactionType.OUTGOING_TX))
        == 0
    )

    extra_coin_spend = make_spend(
        Coin(bytes32(b"1" * 32), bytes32(b"1" * 32), uint64(0)), Program.to(1), Program.to([])
    )
    extra_spend = WalletSpendBundle([extra_coin_spend], G2Element())

    new_txs = await wsm.add_pending_transactions(
        created_txs,
        push=False,
        merge_spends=False,
        sign=False,
        extra_spends=[extra_spend],
    )
    bundles = flatten_spend_bundles(new_txs)
    assert len(bundles) == 2
    for bundle in bundles:
        assert bundle.aggregated_signature == G2Element()
    assert (
        len(await wsm.tx_store.get_all_transactions_for_wallet(wsm.main_wallet.id(), type=TransactionType.OUTGOING_TX))
        == 0
    )
    assert extra_coin_spend in [spend for bundle in bundles for spend in bundle.coin_spends]

    new_txs = await wsm.add_pending_transactions(
        created_txs,
        push=False,
        merge_spends=True,
        sign=False,
        extra_spends=[extra_spend],
    )
    bundles = flatten_spend_bundles(new_txs)
    assert len(bundles) == 1
    for bundle in bundles:
        assert bundle.aggregated_signature == G2Element()
    assert (
        len(await wsm.tx_store.get_all_transactions_for_wallet(wsm.main_wallet.id(), type=TransactionType.OUTGOING_TX))
        == 0
    )
    assert extra_coin_spend in [spend for bundle in bundles for spend in bundle.coin_spends]

    new_txs = await wsm.add_pending_transactions(created_txs, push=True, merge_spends=True, sign=True)
    bundles = flatten_spend_bundles(new_txs)
    assert len(bundles) == 1
    assert (
        len(await wsm.tx_store.get_all_transactions_for_wallet(wsm.main_wallet.id(), type=TransactionType.OUTGOING_TX))
        == 2
    )

    await wallet_environments.full_node.wait_transaction_records_entered_mempool(new_txs)


@pytest.mark.parametrize(
    "wallet_environments",
    [{"num_environments": 2, "blocks_needed": [1, 1], "trusted": True, "reuse_puzhash": True}],
    indirect=True,
)
@pytest.mark.limit_consensus_modes(reason="irrelevant")
@pytest.mark.anyio
async def test_confirming_txs_not_ours(wallet_environments: WalletTestFramework) -> None:
    env_1 = wallet_environments.environments[0]
    env_2 = wallet_environments.environments[1]

    # Some transaction, doesn't matter what
    async with env_1.wallet_state_manager.new_action_scope(wallet_environments.tx_config, push=False) as action_scope:
        await env_1.xch_wallet.generate_signed_transaction(
            uint64(1),
            await env_1.xch_wallet.get_puzzle_hash(new=False),
            action_scope,
        )

    await env_2.rpc_client.push_transactions(action_scope.side_effects.transactions)

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={},
                post_block_balance_updates={
                    1: {
                        "unspent_coin_count": 1,  # We just split a coin so no other balance changes
                    }
                },
            ),
            WalletStateTransition(
                pre_block_balance_updates={
                    1: {
                        "pending_coin_removal_count": 1,  # not sure if this is desirable
                    }
                },
                post_block_balance_updates={
                    1: {
                        "pending_coin_removal_count": -1,
                    }
                },
            ),
        ]
    )
