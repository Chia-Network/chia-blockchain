import asyncio
import logging
from secrets import token_bytes
from typing import Any, Callable, Optional

import pytest

from chia.consensus.block_rewards import calculate_base_farmer_reward, calculate_pool_reward
from chia.full_node.mempool_manager import MempoolManager
from chia.simulator.full_node_simulator import FullNodeSimulator
from chia.simulator.simulator_protocol import FarmNewBlockProtocol
from chia.simulator.time_out_assert import time_out_assert, time_out_assert_not_none
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.peer_info import PeerInfo
from chia.util.ints import uint16, uint32, uint64, uint128
from chia.wallet.cat_wallet.cat_wallet import CATWallet
from chia.wallet.did_wallet.did_wallet import DIDWallet
from chia.wallet.nft_wallet.nft_wallet import NFTWallet
from chia.wallet.outer_puzzles import create_asset_id, match_puzzle
from chia.wallet.puzzle_drivers import PuzzleInfo
from chia.wallet.trading.offer import Offer
from chia.wallet.trading.trade_status import TradeStatus
from chia.wallet.uncurried_puzzle import uncurry_puzzle
from chia.wallet.util.compute_memos import compute_memos

# from clvm_tools.binutils import disassemble
from tests.util.wallet_is_synced import wallets_are_synced


@pytest.mark.parametrize(
    "trusted",
    [True, False],
)
@pytest.mark.asyncio
# @pytest.mark.skip
async def test_notifications(two_wallet_nodes: Any, trusted: Any) -> None:
    full_nodes, wallets, _ = two_wallet_nodes
    full_node_api: FullNodeSimulator = full_nodes[0]
    full_node_server = full_node_api.server
    wallet_node_1, server_0 = wallets[0]
    wallet_node_2, server_1 = wallets[1]
    wsm_1 = wallet_node_1.wallet_state_manager
    wsm_2 = wallet_node_2.wallet_state_manager
    wallet_1 = wsm_1.main_wallet
    wallet_2 = wsm_2.main_wallet

    ph_1 = await wallet_1.get_new_puzzlehash()
    ph_2 = await wallet_2.get_new_puzzlehash()
    ph_token = bytes32(token_bytes())

    if trusted:
        wallet_node_1.config["trusted_peers"] = {
            full_node_api.full_node.server.node_id.hex(): full_node_api.full_node.server.node_id.hex()
        }
        wallet_node_2.config["trusted_peers"] = {
            full_node_api.full_node.server.node_id.hex(): full_node_api.full_node.server.node_id.hex()
        }
    else:
        wallet_node_1.config["trusted_peers"] = {}
        wallet_node_2.config["trusted_peers"] = {}

    await server_0.start_client(PeerInfo("localhost", uint16(full_node_server._port)), None)
    await server_1.start_client(PeerInfo("localhost", uint16(full_node_server._port)), None)

    for i in range(0, 1):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph_1))
    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph_token))
    await time_out_assert(30, wallets_are_synced, True, [wallet_node_1, wallet_node_2], full_node_api)

    funds_1 = sum([calculate_pool_reward(uint32(i)) + calculate_base_farmer_reward(uint32(i)) for i in range(1, 2)])

    await time_out_assert(30, wallet_1.get_unconfirmed_balance, funds_1)
    await time_out_assert(30, wallet_1.get_confirmed_balance, funds_1)

    notification_manager_1 = wsm_1.notification_manager
    notification_manager_2 = wsm_2.notification_manager

    AMOUNT = uint64(1750000000000)
    FEE = uint64(1)
    tx = await notification_manager_1.send_new_notification(ph_2, b"test", AMOUNT, fee=FEE)
    await wsm_1.add_pending_transaction(tx)
    await time_out_assert_not_none(5, full_node_api.full_node.mempool_manager.get_spendbundle, tx.spend_bundle.name())
    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph_token))

    funds_1 = funds_1 - AMOUNT - FEE
    funds_2 = AMOUNT

    await time_out_assert(30, wallet_1.get_unconfirmed_balance, funds_1)
    await time_out_assert(30, wallet_1.get_confirmed_balance, funds_1)
    await time_out_assert(30, wallet_2.get_unconfirmed_balance, funds_2)
    await time_out_assert(30, wallet_2.get_confirmed_balance, funds_2)

    notifications = await notification_manager_2.notification_store.get_all_notifications()
    assert len(notifications) == 1
    assert (
        await notification_manager_2.notification_store.get_notifications([n.coin_id for n in notifications])
        == notifications
    )

    await notification_manager_2.notification_store.delete_all_notifications()
    assert len(await notification_manager_2.notification_store.get_all_notifications()) == 0
    await notification_manager_2.notification_store.add_notification(notifications[0])
    await notification_manager_2.notification_store.delete_notifications([n.coin_id for n in notifications])
    assert len(await notification_manager_2.notification_store.get_all_notifications()) == 0
