from __future__ import annotations

from typing import List

import pytest

from chia.protocols import full_node_protocol
from chia.simulator.setup_nodes import SimulatorsAndWallets
from chia.simulator.time_out_assert import time_out_assert
from chia.types.full_block import FullBlock
from chia.types.peer_info import PeerInfo
from chia.util.ints import uint32, uint64, uint128
from chia.wallet.util.tx_config import DEFAULT_TX_CONFIG
from chia.wallet.wallet_node import WalletNode
from tests.connection_utils import connect_and_get_peer
from tests.util.misc import BenchmarkRunner


async def wallet_height_at_least(wallet_node: WalletNode, h: uint32) -> bool:
    height = await wallet_node.wallet_state_manager.blockchain.get_finished_sync_up_to()
    return height == h


async def wallet_balance_at_least(wallet_node: WalletNode, balance: uint128) -> bool:
    b = await wallet_node.wallet_state_manager.get_confirmed_balance_for_wallet(1)
    return b >= balance


@pytest.mark.limit_consensus_modes(reason="benchmark")
@pytest.mark.asyncio
async def test_mempool_update_performance(
    wallet_nodes_mempool_perf: SimulatorsAndWallets,
    default_400_blocks: List[FullBlock],
    self_hostname: str,
    benchmark_runner: BenchmarkRunner,
) -> None:
    blocks = default_400_blocks
    full_nodes, wallets, bt = wallet_nodes_mempool_perf
    wallet_node = wallets[0][0]
    wallet_server = wallets[0][1]
    full_node_api_1 = full_nodes[0]
    full_node_api_2 = full_nodes[1]
    server_1 = full_node_api_1.full_node.server
    server_2 = full_node_api_2.full_node.server
    wallet = wallet_node.wallet_state_manager.main_wallet
    ph = await wallet.get_new_puzzlehash()

    peer = await connect_and_get_peer(server_1, server_2, self_hostname)
    await full_node_api_1.full_node.add_block_batch(blocks, peer.get_peer_logging(), None)

    await wallet_server.start_client(PeerInfo(self_hostname, server_1.get_port()), None)
    await time_out_assert(60, wallet_height_at_least, True, wallet_node, 399)
    send_amount = uint64(40000000000000)
    fee_amount = uint64(2213)
    await time_out_assert(60, wallet_balance_at_least, True, wallet_node, send_amount + fee_amount)

    [big_transaction] = await wallet.generate_signed_transaction(send_amount, ph, DEFAULT_TX_CONFIG, fee_amount)

    assert big_transaction.spend_bundle is not None
    await full_node_api_1.respond_transaction(
        full_node_protocol.RespondTransaction(big_transaction.spend_bundle), peer, test=True
    )
    cons = list(server_1.all_connections.values())[:]
    for con in cons:
        await con.close()

    blocks = bt.get_consecutive_blocks(3, blocks)

    with benchmark_runner.assert_runtime(seconds=0.45):
        for block in blocks[-3:]:
            await full_node_api_1.full_node.add_block(block)
