from __future__ import annotations

import asyncio
from typing import Any, List, Optional, Tuple

import pytest

from chia.full_node.full_node_api import FullNodeAPI
from chia.full_node.mempool import MempoolRemoveReason
from chia.simulator.block_tools import BlockTools
from chia.simulator.full_node_simulator import FullNodeSimulator
from chia.simulator.simulator_protocol import FarmNewBlockProtocol
from chia.simulator.time_out_assert import time_out_assert, time_out_assert_custom_interval
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.peer_info import PeerInfo
from chia.types.spend_bundle import SpendBundle
from chia.util.ints import uint16, uint64
from chia.wallet.transaction_record import TransactionRecord
from chia.wallet.wallet_node import WalletNode


async def farm_blocks(full_node_api: FullNodeSimulator, ph: bytes32, num_blocks: int) -> int:
    # TODO: replace uses with helpers on FullNodeSimulator
    for i in range(num_blocks):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))
    return num_blocks


def assert_sb_in_pool(node: FullNodeAPI, sb: SpendBundle) -> None:
    assert sb == node.full_node.mempool_manager.get_spendbundle(sb.name())


def assert_sb_not_in_pool(node: FullNodeAPI, sb: SpendBundle) -> None:
    assert node.full_node.mempool_manager.get_spendbundle(sb.name()) is None
    assert not node.full_node.mempool_manager.seen(sb.name())


def evict_from_pool(node: FullNodeAPI, sb: SpendBundle) -> None:
    mempool_item = node.full_node.mempool_manager.mempool.get_item_by_id(sb.name())
    assert mempool_item is not None
    node.full_node.mempool_manager.mempool.remove_from_pool([mempool_item.name], MempoolRemoveReason.CONFLICT)
    node.full_node.mempool_manager.remove_seen(sb.name())


@pytest.mark.asyncio
async def test_wallet_tx_retry(
    setup_two_nodes_and_wallet_fast_retry: Tuple[List[FullNodeSimulator], List[Tuple[Any, Any]], BlockTools],
    self_hostname: str,
) -> None:
    wait_secs = 20
    nodes, wallets, bt = setup_two_nodes_and_wallet_fast_retry
    server_1 = nodes[0].full_node.server
    full_node_1: FullNodeSimulator = nodes[0]
    wallet_node_1: WalletNode = wallets[0][0]
    wallet_node_1.config["tx_resend_timeout_secs"] = 5
    wallet_server_1 = wallets[0][1]
    wallet_1 = wallet_node_1.wallet_state_manager.main_wallet
    reward_ph = await wallet_1.get_new_puzzlehash()

    await wallet_server_1.start_client(PeerInfo(self_hostname, uint16(server_1._port)), None)

    await farm_blocks(full_node_1, reward_ph, 2)
    await full_node_1.wait_for_wallet_synced(wallet_node=wallet_node_1, timeout=wait_secs)

    transaction: TransactionRecord = await wallet_1.generate_signed_transaction(uint64(100), reward_ph)
    sb1: Optional[SpendBundle] = transaction.spend_bundle
    assert sb1 is not None
    await wallet_1.push_transaction(transaction)

    async def sb_in_mempool() -> bool:
        return full_node_1.full_node.mempool_manager.get_spendbundle(transaction.name) == transaction.spend_bundle

    # SpendBundle is accepted by peer
    await time_out_assert(wait_secs, sb_in_mempool)

    # Evict SpendBundle from peer
    evict_from_pool(full_node_1, sb1)
    assert_sb_not_in_pool(full_node_1, sb1)

    # Wait some time so wallet will retry
    await asyncio.sleep(2)

    our_ph = await wallet_1.get_new_puzzlehash()
    await farm_blocks(full_node_1, our_ph, 2)

    # Wait for wallet to catch up
    await full_node_1.wait_for_wallet_synced(wallet_node=wallet_node_1, timeout=wait_secs)

    async def check_transaction_in_mempool_or_confirmed(transaction: TransactionRecord) -> bool:
        txn = await wallet_node_1.wallet_state_manager.get_transaction(transaction.name)
        assert txn is not None
        sb = txn.spend_bundle
        assert sb is not None
        full_node_sb = full_node_1.full_node.mempool_manager.get_spendbundle(sb.name())
        if full_node_sb is None:
            return False
        in_mempool: bool = full_node_sb.name() == sb.name()
        return txn.confirmed or in_mempool

    # Check that wallet resent the unconfirmed SpendBundle
    await time_out_assert_custom_interval(wait_secs, 1, check_transaction_in_mempool_or_confirmed, True, transaction)
