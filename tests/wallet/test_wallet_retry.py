import time
from typing import Any, List, Tuple

import pytest

from chia.full_node.full_node_api import FullNodeAPI
from chia.protocols import full_node_protocol
from chia.simulator.full_node_simulator import FullNodeSimulator
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.peer_info import PeerInfo
from chia.types.spend_bundle import SpendBundle
from chia.util.ints import uint16, uint32, uint64
from chia.wallet.transaction_record import TransactionRecord
from chia.wallet.util.transaction_type import TransactionType
from chia.wallet.wallet_node import WalletNode
from tests.block_tools import BlockTools
from tests.core.full_node.test_mempool import generate_test_spend_bundle
from tests.core.node_height import node_height_at_least
from tests.pools.test_pool_rpc import farm_blocks, wallet_is_synced
from tests.time_out_assert import time_out_assert, time_out_assert_custom_interval
from tests.wallet_tools import WalletTool


@pytest.fixture(scope="module")
def wallet_a(bt: BlockTools) -> WalletTool:
    return bt.get_pool_wallet_tool()


def assert_sb_in_pool(node: FullNodeAPI, sb: SpendBundle) -> None:
    assert sb == node.full_node.mempool_manager.get_spendbundle(sb.name())


def assert_sb_not_in_pool(node: FullNodeAPI, sb: SpendBundle) -> None:
    assert node.full_node.mempool_manager.get_spendbundle(sb.name()) is None
    assert not node.full_node.mempool_manager.seen(sb.name())


def evict_from_pool(node: FullNodeAPI, sb: SpendBundle) -> None:
    mempool_item = node.full_node.mempool_manager.mempool.spends[sb.name()]
    node.full_node.mempool_manager.mempool.remove_from_pool(mempool_item)
    node.full_node.mempool_manager.remove_seen(sb.name())


@pytest.mark.asyncio
async def test_wallet_tx_retry(
    bt: BlockTools,
    setup_two_nodes_and_wallet_fast_retry: Tuple[List[FullNodeSimulator], List[Tuple[Any, Any]]],
    wallet_a: WalletTool,
    self_hostname: str,
) -> None:
    wait_secs = 1000
    reward_ph = wallet_a.get_new_puzzlehash()
    nodes, wallets = setup_two_nodes_and_wallet_fast_retry
    server_1 = nodes[0].full_node.server

    full_node_1: FullNodeSimulator = nodes[0]

    wallet_node_1: WalletNode = wallets[0][0]
    wallet_node_1.config["tx_resend_timeout_secs"] = 5
    wallet_server_1 = wallets[0][1]
    assert wallet_node_1.wallet_state_manager is not None
    wallet_1 = wallet_node_1.wallet_state_manager.main_wallet

    await wallet_server_1.start_client(PeerInfo(self_hostname, uint16(server_1._port)), None)

    blocks = await full_node_1.get_all_full_blocks()
    start_height = blocks[-1].height if len(blocks) > 0 else -1
    blocks = bt.get_consecutive_blocks(
        3,
        block_list_input=blocks,
        guarantee_transaction_block=True,
        farmer_reward_puzzle_hash=reward_ph,
        pool_reward_puzzle_hash=reward_ph,
    )

    for block in blocks:
        await full_node_1.full_node.respond_block(full_node_protocol.RespondBlock(block))
    await time_out_assert(60, node_height_at_least, True, full_node_1, start_height + 3)
    current_height = 3

    coins = iter(blocks[-1].get_included_reward_coins())
    coin1 = next(coins)

    sb1 = generate_test_spend_bundle(wallet_a, coin1, new_puzzle_hash=bytes32(b"A" * 32))
    amount_out = sum(_.amount for _ in sb1.additions())
    tx = TransactionRecord(
        confirmed_at_height=uint32(0),
        created_at_time=uint64(int(time.time())),
        to_puzzle_hash=bytes32(b"A" * 32),
        amount=uint64(amount_out),
        fee_amount=uint64(sb1.fees()),
        confirmed=False,
        sent=uint32(0),
        spend_bundle=sb1,
        additions=sb1.additions(),
        removals=sb1.removals(),
        wallet_id=wallet_node_1.wallet_state_manager.main_wallet.id(),
        sent_to=[],
        memos=[],
        trade_id=None,
        type=uint32(TransactionType.OUTGOING_TX.value),
        name=sb1.name(),
    )

    await wallet_node_1.wallet_state_manager.add_pending_transaction(tx)

    async def sb_in_mempool() -> bool:
        return full_node_1.full_node.mempool_manager.get_spendbundle(sb1.name()) == sb1

    # SpendBundle is accepted by peer
    await time_out_assert(wait_secs, sb_in_mempool)

    async def wallet_synced() -> bool:
        return await wallet_is_synced(wallet_node_1, full_node_1)

    # Wait for wallet to catch up
    await time_out_assert(wait_secs, wallet_synced)

    # Evict SpendBundle from peer
    evict_from_pool(full_node_1, sb1)
    assert_sb_not_in_pool(full_node_1, sb1)

    print(f"mempool spends: {full_node_1.full_node.mempool_manager.mempool.spends}")

    our_ph = await wallet_1.get_new_puzzlehash()
    current_height += await farm_blocks(full_node_1, our_ph, 3)
    await time_out_assert(wait_secs, wallet_synced)

    async def check_transaction_in_mempool_or_confirmed(transaction: TransactionRecord) -> bool:
        assert wallet_node_1.wallet_state_manager is not None
        txn = await wallet_node_1.wallet_state_manager.get_transaction(transaction.name)
        assert txn is not None
        sb = txn.spend_bundle
        assert sb is not None
        full_node_sb = full_node_1.full_node.mempool_manager.get_spendbundle(sb.name())
        in_mempool: bool = full_node_sb == sb
        return txn.confirmed or in_mempool

    # Check that wallet resent the unconfirmed SpendBundle
    await time_out_assert_custom_interval(wait_secs, 1, check_transaction_in_mempool_or_confirmed, True, tx)
