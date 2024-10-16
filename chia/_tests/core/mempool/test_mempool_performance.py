from __future__ import annotations

from typing import List

import pytest

from chia._tests.util.misc import BenchmarkRunner, add_blocks_in_batches, wallet_height_at_least
from chia._tests.util.setup_nodes import OldSimulatorsAndWallets
from chia._tests.util.time_out_assert import time_out_assert
from chia.types.full_block import FullBlock
from chia.types.mempool_inclusion_status import MempoolInclusionStatus
from chia.types.peer_info import PeerInfo
from chia.util.ints import uint64, uint128
from chia.wallet.util.tx_config import DEFAULT_TX_CONFIG
from chia.wallet.wallet_node import WalletNode


async def wallet_balance_at_least(wallet_node: WalletNode, balance: uint128) -> bool:
    b = await wallet_node.wallet_state_manager.get_confirmed_balance_for_wallet(1)
    return b >= balance


@pytest.mark.limit_consensus_modes(reason="benchmark")
@pytest.mark.anyio
async def test_mempool_update_performance(
    wallet_nodes_mempool_perf: OldSimulatorsAndWallets,
    default_400_blocks: List[FullBlock],
    self_hostname: str,
    benchmark_runner: BenchmarkRunner,
) -> None:
    blocks = default_400_blocks
    [full_node_api], [wallet_setup], bt = wallet_nodes_mempool_perf
    full_node = full_node_api.full_node
    wallet_node, wallet_server = wallet_setup
    wallet = wallet_node.wallet_state_manager.main_wallet

    # We need an initialized mempool as we want to add a transaction, so we use
    # the first block to achieve that
    await full_node.add_block(blocks[0])
    await add_blocks_in_batches(blocks[1:], full_node)
    await wallet_server.start_client(PeerInfo(self_hostname, full_node.server.get_port()), None)
    await time_out_assert(30, wallet_height_at_least, True, wallet_node, 399)
    send_amount = uint64(40_000_000_000_000)
    fee_amount = uint64(2213)
    await time_out_assert(30, wallet_balance_at_least, True, wallet_node, send_amount + fee_amount)

    ph = await wallet.get_new_puzzlehash()
    async with wallet.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=False, sign=True) as action_scope:
        await wallet.generate_signed_transaction(send_amount, ph, action_scope, fee_amount)
    [big_transaction] = action_scope.side_effects.transactions
    assert big_transaction.spend_bundle is not None
    status, err = await full_node.add_transaction(
        big_transaction.spend_bundle, big_transaction.spend_bundle.name(), test=True
    )
    assert err is None
    assert status == MempoolInclusionStatus.SUCCESS

    cons = list(full_node.server.all_connections.values())
    for con in cons:
        await con.close()

    blocks = bt.get_consecutive_blocks(3, blocks)
    with benchmark_runner.assert_runtime(seconds=0.45):
        for block in blocks[-3:]:
            await full_node.add_block(block)
