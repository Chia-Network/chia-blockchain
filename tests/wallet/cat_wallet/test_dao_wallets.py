from __future__ import annotations

import asyncio
from typing import List

import pytest

from chia.consensus.block_rewards import calculate_base_farmer_reward, calculate_pool_reward
from chia.simulator.setup_nodes import SimulatorsAndWallets
from chia.simulator.simulator_protocol import FarmNewBlockProtocol
from chia.simulator.time_out_assert import time_out_assert, time_out_assert_not_none
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.peer_info import PeerInfo
from chia.util.ints import uint16, uint32, uint64
from chia.wallet.dao_wallet.dao_wallet import DAOWallet
from chia.wallet.transaction_record import TransactionRecord
from tests.util.wallet_is_synced import wallet_is_synced

puzzle_hash_0 = bytes32(32 * b"0")


@pytest.mark.parametrize(
    "trusted",
    [True, False],
)
@pytest.mark.asyncio
async def test_dao_creation(self_hostname: str, three_wallet_nodes: SimulatorsAndWallets, trusted: bool) -> None:
    num_blocks = 3
    full_nodes, wallets, _ = three_wallet_nodes
    full_node_api = full_nodes[0]
    full_node_server = full_node_api.server
    wallet_node_0, server_0 = wallets[0]
    wallet_node_1, server_1 = wallets[1]
    wallet = wallet_node_0.wallet_state_manager.main_wallet
    wallet_1 = wallet_node_1.wallet_state_manager.main_wallet
    ph = await wallet.get_new_puzzlehash()
    ph_1 = await wallet_1.get_new_puzzlehash()

    if trusted:
        wallet_node_0.config["trusted_peers"] = {
            full_node_api.full_node.server.node_id.hex(): full_node_api.full_node.server.node_id.hex()
        }
        wallet_node_1.config["trusted_peers"] = {
            full_node_api.full_node.server.node_id.hex(): full_node_api.full_node.server.node_id.hex()
        }
    else:
        wallet_node_0.config["trusted_peers"] = {}
        wallet_node_1.config["trusted_peers"] = {}

    await server_0.start_client(PeerInfo(self_hostname, uint16(full_node_server._port)), None)
    await server_1.start_client(PeerInfo(self_hostname, uint16(full_node_server._port)), None)

    for i in range(0, num_blocks):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph_1))
    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(puzzle_hash_0))

    funds = sum(
        [calculate_pool_reward(uint32(i)) + calculate_base_farmer_reward(uint32(i)) for i in range(1, num_blocks + 1)]
    )

    await time_out_assert(20, wallet.get_confirmed_balance, funds)
    await time_out_assert(20, wallet_is_synced, True, wallet_node_0, full_node_api)

    cat_amt = 2000

    async with wallet_node_0.wallet_state_manager.lock:
        dao_wallet_0 = await DAOWallet.create_new_dao_and_wallet(
            wallet_node_0.wallet_state_manager,
            wallet,
            uint64(cat_amt * 2),
        )
        assert dao_wallet_0 is not None

    # Get the full node sim to process the wallet creation spend
    tx_queue: List[TransactionRecord] = await wallet_node_0.wallet_state_manager.tx_store.get_not_sent()
    tx_record = tx_queue[0]
    await full_node_api.process_transaction_records(records=[tx_record])

    for i in range(1, num_blocks):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(puzzle_hash_0))

    # Check the spend was successful
    treasury_id = dao_wallet_0.dao_info.treasury_id
    await time_out_assert(
        60,
        dao_wallet_0.is_spend_retrievable,
        True,
        treasury_id,
    )

    # get the cat wallets
    cat_wallet_0 = dao_wallet_0.wallet_state_manager.wallets[dao_wallet_0.dao_info.cat_wallet_id]
    dao_cat_wallet_0 = dao_wallet_0.wallet_state_manager.wallets[dao_wallet_0.dao_info.dao_cat_wallet_id]

    # Create the other user's wallet from the treasury id
    async with wallet_node_0.wallet_state_manager.lock:
        dao_wallet_1 = await DAOWallet.create_new_dao_wallet_for_existing_dao(
            wallet_node_1.wallet_state_manager,
            wallet_1,
            treasury_id,
        )
    assert dao_wallet_1 is not None
    assert dao_wallet_0.dao_info.treasury_id == dao_wallet_1.dao_info.treasury_id

    # Get the cat wallets for wallet_1
    cat_wallet_1 = dao_wallet_1.wallet_state_manager.wallets[dao_wallet_1.dao_info.cat_wallet_id]
    dao_cat_wallet_1 = dao_wallet_1.wallet_state_manager.wallets[dao_wallet_1.dao_info.dao_cat_wallet_id]

    # Send some cats to the dao_cat lockup
    dao_cat_amt = 100
    async with wallet_node_0.wallet_state_manager.lock:
        txs = await dao_wallet_0.create_new_dao_cats(dao_cat_amt)
    sb = txs[0].spend_bundle
    await time_out_assert_not_none(5, full_node_api.full_node.mempool_manager.get_spendbundle, sb.name())
    await full_node_api.process_transaction_records(records=txs)

    # Give the full node a moment to catch up if there are no trusted peers
    if not trusted:
        await asyncio.sleep(1)
    for i in range(1, num_blocks):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(puzzle_hash_0))

    # Test that we can get spendable coins from both cat and dao_cat wallet
    fake_proposal_id = Program.to("proposal_id").get_tree_hash()
    spendable_coins = await dao_cat_wallet_0.wallet_state_manager.get_spendable_coins_for_wallet(
        dao_cat_wallet_0.id(), None
    )

    assert len(spendable_coins) > 0
    coins = await dao_cat_wallet_0.advanced_select_coins(1, fake_proposal_id)
    assert len(coins) > 0
    # check that we have selected the coin from dao_cat_wallet
    assert list(coins)[0].coin.amount == dao_cat_amt

    # send some cats from wallet_0 to wallet_1 so we can test voting
    cat_txs = await cat_wallet_0.generate_signed_transaction([cat_amt], [ph_1])
    await wallet.wallet_state_manager.add_pending_transaction(cat_txs[0])
    sb = cat_txs[0].spend_bundle
    await time_out_assert_not_none(5, full_node_api.full_node.mempool_manager.get_spendbundle, sb.name())
    await full_node_api.process_transaction_records(records=cat_txs)

    for i in range(1, num_blocks):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(puzzle_hash_0))

    cat_wallet_1_bal = await cat_wallet_1.get_confirmed_balance()
    assert cat_wallet_1_bal == cat_amt
