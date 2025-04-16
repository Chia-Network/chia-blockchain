from __future__ import annotations

import pytest
from chiabip158 import PyBIP158

from chia.wallet.util.tx_config import DEFAULT_TX_CONFIG


@pytest.mark.anyio
async def test_basic_filter_test(simulator_and_wallet):
    _full_nodes, wallets, bt = simulator_and_wallet
    wallet_node, _server_2 = wallets[0]
    wallet = wallet_node.wallet_state_manager.main_wallet

    num_blocks = 2
    async with wallet.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
        ph = await action_scope.get_puzzle_hash(wallet.wallet_state_manager)
    blocks = bt.get_consecutive_blocks(
        10,
        guarantee_transaction_block=True,
        farmer_reward_puzzle_hash=ph,
        pool_reward_puzzle_hash=ph,
    )
    for i in range(1, num_blocks):
        byte_array_tx: list[bytes] = []
        block = blocks[i]
        coins = block.get_included_reward_coins()
        coin_0 = bytearray(coins[0].puzzle_hash)
        coin_1 = bytearray(coins[1].puzzle_hash)
        byte_array_tx.append(coin_0)
        byte_array_tx.append(coin_1)

        pl = PyBIP158(byte_array_tx)
        present = pl.Match(coin_0)
        fee_present = pl.Match(coin_1)

        assert present
        assert fee_present
