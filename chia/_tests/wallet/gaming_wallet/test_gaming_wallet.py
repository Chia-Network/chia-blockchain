from __future__ import annotations

import pytest
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint64, uint32

from chia._tests.environments.wallet import WalletTestFramework
from chia._tests.util.time_out_assert import time_out_assert
from chia.simulator.full_node_simulator import FullNodeSimulator
from chia.wallet.gaming_wallet.gaming_wallet import GamingWallet
from chia.wallet.util.wallet_types import WalletType
from chia.wallet.wallet import Wallet
from chia.wallet.wallet_node import WalletNode
from chia.wallet.wallet_request_types import RegisterGameCoin

async def has_gaming_coin_record(wallet_node: WalletNode, coin_id: bytes32, gaming_wallet_id: uint32) -> bool:
        record = await wallet_node.wallet_state_manager.coin_store.get_coin_record(coin_id)
        if record is None:
            return False
        return record.wallet_type == WalletType.GAMING and record.wallet_id == int(gaming_wallet_id)


@pytest.mark.parametrize(
    "wallet_environments",
    [{"num_environments": 1, "blocks_needed": [2], "reuse_puzhash": True, "trusted": True}],
    indirect=True,
)
@pytest.mark.limit_consensus_modes(reason="irrelevant")
@pytest.mark.anyio
async def test_gaming_wallet_register_game_coin_persists_coin_record(wallet_environments: WalletTestFramework) -> None:
    env = wallet_environments.environments[0]
    wallet: Wallet = env.xch_wallet
    wallet_node: WalletNode = env.node
    full_node: FullNodeSimulator = wallet_environments.full_node

    # Create a coin that no Wallet owns by sending to a puzzle hash we don't own.
    target_ph = bytes32.secret()
    async with wallet.wallet_state_manager.new_action_scope(wallet_environments.tx_config, push=True) as action_scope:
        await wallet.generate_signed_transaction(
            amounts=[uint64(1)],
            puzzle_hashes=[target_ph],
            action_scope=action_scope,
        )
    [tx] = action_scope.side_effects.transactions

    await full_node.wait_transaction_records_entered_mempool(records=[tx])
    await full_node.farm_blocks_to_puzzlehash(count=1, guarantee_transaction_blocks=True)
    await full_node.wait_for_wallet_synced(wallet_node=wallet_node, timeout=20)
    await full_node.check_transactions_confirmed(wallet_node.wallet_state_manager, [tx])

    created_coin = next(coin for coin in tx.additions if coin.puzzle_hash == target_ph and coin.amount == uint64(1))
    coin_id = created_coin.name()

    # Create a gaming wallet and register the coin id.
    async with wallet_node.wallet_state_manager.lock:
        gaming_wallet = await GamingWallet.create_new_gaming_wallet(
            wallet_node.wallet_state_manager, wallet, name="Gaming Wallet #1"
        )

    # check for CoinRecord before we register interest in the coin
    await time_out_assert(20, has_gaming_coin_record, False, wallet_node, coin_id, gaming_wallet.id())

    await env.rpc_client.fetch(
        "register_game_coin", RegisterGameCoin(wallet_id=gaming_wallet.id(), coin_id=coin_id).to_json_dict()
    )

    # Trigger/allow subscription processing and coin updates.
    await full_node.farm_blocks_to_puzzlehash(count=1, guarantee_transaction_blocks=True)
    await full_node.wait_for_wallet_synced(wallet_node=wallet_node, timeout=20)

    await time_out_assert(20, has_gaming_coin_record, True, wallet_node, coin_id, gaming_wallet.id())


@pytest.mark.parametrize(
    "wallet_environments",
    [{"num_environments": 1, "blocks_needed": [2], "reuse_puzhash": True, "trusted": True}],
    indirect=True,
)
@pytest.mark.limit_consensus_modes(reason="irrelevant")
@pytest.mark.anyio
async def test_interested_coin_not_persisted_without_gaming_wallet(wallet_environments: WalletTestFramework) -> None:
    env = wallet_environments.environments[0]
    wallet: Wallet = env.xch_wallet
    wallet_node: WalletNode = env.node
    full_node: FullNodeSimulator = wallet_environments.full_node

    # Create an "external" coin by sending to a puzzle hash we don't own.
    target_ph = bytes32.secret()
    async with wallet.wallet_state_manager.new_action_scope(wallet_environments.tx_config, push=True) as action_scope:
        await wallet.generate_signed_transaction(
            amounts=[uint64(1)],
            puzzle_hashes=[target_ph],
            action_scope=action_scope,
        )
    [tx] = action_scope.side_effects.transactions

    await full_node.wait_transaction_records_entered_mempool(records=[tx])
    await full_node.farm_blocks_to_puzzlehash(count=1, guarantee_transaction_blocks=True)
    await full_node.wait_for_wallet_synced(wallet_node=wallet_node, timeout=20)
    await full_node.check_transactions_confirmed(wallet_node.wallet_state_manager, [tx])

    created_coin = next(coin for coin in tx.additions if coin.puzzle_hash == target_ph and coin.amount == uint64(1))
    coin_id = created_coin.name()

    # Register interest without associating it to any GamingWallet id.
    await wallet_node.wallet_state_manager.add_interested_coin_ids([coin_id])

    await full_node.farm_blocks_to_puzzlehash(count=1, guarantee_transaction_blocks=True)
    await full_node.wait_for_wallet_synced(wallet_node=wallet_node, timeout=20)

    # Give the wallet node a moment to process subscription/updates, then assert nothing was stored.
    record = await wallet_node.wallet_state_manager.coin_store.get_coin_record(coin_id)
    assert record is None

