import asyncio
from typing import Optional

import pytest

from chia.full_node.full_node_api import FullNodeAPI
from chia.protocols import full_node_protocol, wallet_protocol
from chia.server.outbound_message import Message
from chia.types.spend_bundle import SpendBundle
from tests.connection_utils import connect_and_get_peer
from tests.core.full_node.test_mempool import generate_test_spend_bundle
from tests.core.node_height import node_height_at_least
from tests.time_out_assert import time_out_assert


@pytest.fixture(scope="module")
def wallet_a(bt):
    return bt.get_pool_wallet_tool()


async def send_sb(node: FullNodeAPI, sb: SpendBundle) -> Optional[Message]:
    tx = wallet_protocol.SendTransaction(sb)
    return await node.send_transaction(tx, test=True)


async def gen_and_send_sb(node, peer, *args, **kwargs):
    sb = generate_test_spend_bundle(*args, **kwargs)
    assert sb is not None

    await send_sb(node, sb)
    return sb


def assert_sb_in_pool(node, sb):
    assert sb == node.full_node.mempool_manager.get_spendbundle(sb.name())


def assert_sb_not_in_pool(node, sb):
    assert node.full_node.mempool_manager.get_spendbundle(sb.name()) is None


def evict_from_pool(node, sb: SpendBundle):
    mempool_item = node.full_node.mempool_manager.mempool.spends[sb.name()]
    node.full_node.mempool_manager.mempool.remove_from_pool(mempool_item)


@pytest.mark.asyncio
async def test_wallet_tx_retry(bt, setup_two_nodes_and_wallet_fast_retry, wallet_a, self_hostname):
    reward_ph = wallet_a.get_new_puzzlehash()
    #full_node_1, full_node_2, server_1, server_2 = two_nodes_one_block
    #server_2.config["wallet"]["tx_resend_timeout_secs"] = 5
    #two_wallet_nodes
    nodes, wallets = setup_two_nodes_and_wallet_fast_retry
    server_1 = nodes[0].full_node.server
    server_2 = nodes[1].full_node.server

    full_node_1 = nodes[0]

    wallet_node_1 = wallets[0][0]
    wallet_node_1.config["tx_resend_timeout_secs"] = 5
    wallet_server_1 = wallets[0][1]
    wallet = wallet_node_1.wallet_state_manager.main_wallet

    blocks = await full_node_1.get_all_full_blocks()
    start_height = blocks[-1].height if len(blocks) > 0 else -1
    blocks = bt.get_consecutive_blocks(
        3,
        block_list_input=blocks,
        guarantee_transaction_block=True,
        farmer_reward_puzzle_hash=reward_ph,
        pool_reward_puzzle_hash=reward_ph,
    )
    peer = await connect_and_get_peer(server_1, server_2, self_hostname)

    for block in blocks:
        await full_node_1.full_node.respond_block(full_node_protocol.RespondBlock(block))
    await time_out_assert(60, node_height_at_least, True, full_node_1, start_height + 3)

    coins = iter(blocks[-1].get_included_reward_coins())
    coin1, coin2 = next(coins), next(coins)

    sb1 = await gen_and_send_sb(full_node_1, peer, wallet_a, coin1)

    # SpendBundle is accepted by peer
    assert_sb_in_pool(full_node_1, sb1)

    # Evict SpendBundle from peer
    evict_from_pool(full_node_1, sb1)
    assert_sb_not_in_pool(full_node_1, sb1)

    # We must advance the chain to cause the wallet to recheck unset SpendBundles
    blocks = bt.get_consecutive_blocks(
        6,
        block_list_input=blocks,
        guarantee_transaction_block=True,
        farmer_reward_puzzle_hash=reward_ph,
        pool_reward_puzzle_hash=reward_ph,
    )

    # Trigger tx_pending_changed via new_peak
    #await full_node_1.full_node.blockchain.get_peak()
    #await wallet_node_1.wallet_state_manager.new_peak()

    # Check that wallet resent unconfirmed SpendBundle
    await asyncio.sleep(10)
    assert_sb_in_pool(full_node_1, sb1)

