from __future__ import annotations

# mypy: ignore-errors
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
from chia.wallet.dao_wallet.dao_info import DAORules
from chia.wallet.dao_wallet.dao_wallet import DAOWallet
from chia.wallet.transaction_record import TransactionRecord

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
    await time_out_assert(20, full_node_api.wallet_is_synced, True, wallet_node_0)

    cat_amt = 2000
    dao_rules = DAORules(
        proposal_timelock=uint64(10),
        soft_close_length=uint64(5),
        attendance_required=uint64(1000),  # 10%
        pass_percentage=uint64(5100),  # 51%
        self_destruct_length=uint64(20),
        oracle_spend_delay=uint64(10),
    )

    async with wallet_node_0.wallet_state_manager.lock:
        dao_wallet_0 = await DAOWallet.create_new_dao_and_wallet(
            wallet_node_0.wallet_state_manager,
            wallet,
            uint64(cat_amt * 2),
            dao_rules,
        )
        assert dao_wallet_0 is not None
        assert dao_wallet_0.new_peak_call_count == 0

    # Get the full node sim to process the wallet creation spend
    tx_queue: List[TransactionRecord] = await wallet_node_0.wallet_state_manager.tx_store.get_not_sent()
    tx_record = tx_queue[0]
    await full_node_api.process_transaction_records(records=[tx_record])
    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(puzzle_hash_0))

    # Check the spend was successful
    treasury_id = dao_wallet_0.dao_info.treasury_id
    await time_out_assert(
        60,
        dao_wallet_0.is_spend_retrievable,
        True,
        treasury_id,
    )
    # Farm enough blocks to pass the oracle_spend_delay and then complete the treasury eve spend
    for i in range(1, 11):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(puzzle_hash_0))
    async with wallet_node_0.wallet_state_manager.lock:
        await dao_wallet_0.generate_treasury_eve_spend()
    tx_queue: List[TransactionRecord] = await wallet_node_0.wallet_state_manager.tx_store.get_not_sent()
    tx_record = tx_queue[0]
    await full_node_api.process_transaction_records(records=[tx_record])
    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(puzzle_hash_0))

    eve_coin = tx_record.removals[0]
    await time_out_assert(
        60,
        dao_wallet_0.is_spend_retrievable,
        True,
        eve_coin.name(),
    )

    # get the cat wallets
    cat_wallet_0 = dao_wallet_0.wallet_state_manager.wallets[dao_wallet_0.dao_info.cat_wallet_id]
    dao_cat_wallet_0 = dao_wallet_0.wallet_state_manager.wallets[dao_wallet_0.dao_info.dao_cat_wallet_id]
    cat_wallet_0_bal = await cat_wallet_0.get_confirmed_balance()
    assert cat_wallet_0_bal == cat_amt * 2

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
    assert cat_wallet_1

    # Send some cats to the dao_cat lockup
    dao_cat_amt = uint64(100)
    async with wallet_node_0.wallet_state_manager.lock:
        txs, new_coins = await dao_wallet_0.create_new_dao_cats(dao_cat_amt, push=True)
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
    cat_txs = await cat_wallet_0.generate_signed_transactions([cat_amt], [ph_1])
    await wallet.wallet_state_manager.add_pending_transaction(cat_txs[0])
    sb = cat_txs[0].spend_bundle
    await time_out_assert_not_none(5, full_node_api.full_node.mempool_manager.get_spendbundle, sb.name())
    await full_node_api.process_transaction_records(records=cat_txs)

    for i in range(1, num_blocks):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(puzzle_hash_0))

    cat_wallet_1_bal = await cat_wallet_1.get_confirmed_balance()
    assert cat_wallet_1_bal == cat_amt


@pytest.mark.parametrize(
    "trusted",
    [True, False],
)
@pytest.mark.asyncio
async def test_dao_funding(self_hostname: str, three_wallet_nodes: SimulatorsAndWallets, trusted: bool) -> None:
    num_blocks = 3
    full_nodes, wallets, _ = three_wallet_nodes
    full_node_api = full_nodes[0]
    full_node_server = full_node_api.server
    wallet_node_0, server_0 = wallets[0]
    wallet_node_1, server_1 = wallets[1]
    wallet_node_2, server_2 = wallets[2]
    wallet = wallet_node_0.wallet_state_manager.main_wallet
    wallet_1 = wallet_node_1.wallet_state_manager.main_wallet
    wallet_2 = wallet_node_1.wallet_state_manager.main_wallet
    ph = await wallet.get_new_puzzlehash()
    ph_1 = await wallet_1.get_new_puzzlehash()
    ph_2 = await wallet_2.get_new_puzzlehash()

    if trusted:
        wallet_node_0.config["trusted_peers"] = {
            full_node_api.full_node.server.node_id.hex(): full_node_api.full_node.server.node_id.hex()
        }
        wallet_node_1.config["trusted_peers"] = {
            full_node_api.full_node.server.node_id.hex(): full_node_api.full_node.server.node_id.hex()
        }
        wallet_node_2.config["trusted_peers"] = {
            full_node_api.full_node.server.node_id.hex(): full_node_api.full_node.server.node_id.hex()
        }
    else:
        wallet_node_0.config["trusted_peers"] = {}
        wallet_node_1.config["trusted_peers"] = {}
        wallet_node_2.config["trusted_peers"] = {}

    await server_0.start_client(PeerInfo(self_hostname, uint16(full_node_server._port)), None)
    await server_1.start_client(PeerInfo(self_hostname, uint16(full_node_server._port)), None)
    await server_2.start_client(PeerInfo(self_hostname, uint16(full_node_server._port)), None)

    for i in range(0, num_blocks):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph_1))
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph_2))
    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(puzzle_hash_0))

    funds = sum(
        [calculate_pool_reward(uint32(i)) + calculate_base_farmer_reward(uint32(i)) for i in range(1, num_blocks + 1)]
    )

    await time_out_assert(20, wallet.get_confirmed_balance, funds)
    await time_out_assert(20, full_node_api.wallet_is_synced, True, wallet_node_0)

    cat_amt = 300000
    dao_rules = DAORules(
        proposal_timelock=uint64(10),
        soft_close_length=uint64(5),
        attendance_required=uint64(1000),  # 10%
        pass_percentage=uint64(5100),  # 51%
        self_destruct_length=uint64(20),
        oracle_spend_delay=uint64(10),
    )

    async with wallet_node_0.wallet_state_manager.lock:
        dao_wallet_0 = await DAOWallet.create_new_dao_and_wallet(
            wallet_node_0.wallet_state_manager,
            wallet,
            uint64(cat_amt),
            dao_rules,
        )
        assert dao_wallet_0 is not None

    treasury_id = dao_wallet_0.dao_info.treasury_id

    # Get the full node sim to process the wallet creation spend
    tx_queue: List[TransactionRecord] = await wallet_node_0.wallet_state_manager.tx_store.get_not_sent()
    tx_record = tx_queue[0]
    await full_node_api.process_transaction_records(records=[tx_record])
    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(puzzle_hash_0))

    # Farm enough blocks to pass the oracle_spend_delay and then complete the treasury eve spend
    for i in range(1, 11):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(puzzle_hash_0))
    async with wallet_node_0.wallet_state_manager.lock:
        await dao_wallet_0.generate_treasury_eve_spend()
    tx_queue: List[TransactionRecord] = await wallet_node_0.wallet_state_manager.tx_store.get_not_sent()
    tx_record = tx_queue[0]
    await full_node_api.process_transaction_records(records=[tx_record])
    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(puzzle_hash_0))

    # get the cat wallets
    cat_wallet_0 = dao_wallet_0.wallet_state_manager.wallets[dao_wallet_0.dao_info.cat_wallet_id]
    cat_wallet_0_bal = await cat_wallet_0.get_confirmed_balance()
    assert cat_wallet_0_bal == cat_amt

    # Create funding spends for xch and cat
    xch_funds = uint64(500000)
    cat_funds = uint64(100000)
    funding_tx = await dao_wallet_0.create_add_money_to_treasury_spend(xch_funds)
    funding_sb = funding_tx.spend_bundle
    await time_out_assert_not_none(5, full_node_api.full_node.mempool_manager.get_spendbundle, funding_sb.name())
    await full_node_api.process_transaction_records(records=[funding_tx])

    if not trusted:
        await asyncio.sleep(1)
    for i in range(1, num_blocks):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(puzzle_hash_0))

    # Check that the funding spend is recognized by both dao wallets
    xch_bal = await dao_wallet_0.get_balance_by_asset_type()
    assert xch_bal == xch_funds

    cat_funding_tx = await dao_wallet_0.create_add_money_to_treasury_spend(
        cat_funds, funding_wallet_id=cat_wallet_0.id()
    )
    cat_funding_sb = cat_funding_tx.spend_bundle
    await time_out_assert_not_none(5, full_node_api.full_node.mempool_manager.get_spendbundle, cat_funding_sb.name())
    await full_node_api.process_transaction_records(records=[cat_funding_tx])

    if not trusted:
        await asyncio.sleep(1)
    for i in range(1, num_blocks):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(puzzle_hash_0))

    cat_bal = await cat_wallet_0.get_confirmed_balance()
    assert cat_bal == cat_amt - cat_funds

    # Check that the funding spend is found
    cat_id = bytes32.from_hexstr(cat_wallet_0.get_asset_id())
    cat_bal = await dao_wallet_0.get_balance_by_asset_type(cat_id)
    assert cat_bal == cat_funds

    # Create the other user's wallet from the treasury id
    async with wallet_node_0.wallet_state_manager.lock:
        dao_wallet_1 = await DAOWallet.create_new_dao_wallet_for_existing_dao(
            wallet_node_1.wallet_state_manager,
            wallet_1,
            treasury_id,
        )
    assert dao_wallet_1 is not None
    assert dao_wallet_1.dao_info.treasury_id == dao_wallet_1.dao_info.treasury_id

    # Get the cat wallets for wallet_1
    cat_wallet_1 = dao_wallet_1.wallet_state_manager.wallets[dao_wallet_1.dao_info.cat_wallet_id]
    assert cat_wallet_1
    assert cat_wallet_1.cat_info.limitations_program_hash == cat_id

    xch_bal_1 = await dao_wallet_1.get_balance_by_asset_type()
    assert xch_bal_1 == xch_funds

    # Check that the funding spend is found
    cat_bal = await dao_wallet_1.get_balance_by_asset_type(cat_id)
    assert cat_bal == cat_funds

@pytest.mark.parametrize(
    "trusted",
    [True, False],
)
@pytest.mark.asyncio
async def test_dao_proposals(self_hostname: str, three_wallet_nodes: SimulatorsAndWallets, trusted: bool) -> None:
    num_blocks = 3
    full_nodes, wallets, _ = three_wallet_nodes
    full_node_api = full_nodes[0]
    full_node_server = full_node_api.server
    wallet_node_0, server_0 = wallets[0]
    wallet_node_1, server_1 = wallets[1]
    wallet_node_2, server_2 = wallets[2]
    wallet = wallet_node_0.wallet_state_manager.main_wallet
    wallet_1 = wallet_node_1.wallet_state_manager.main_wallet
    wallet_2 = wallet_node_1.wallet_state_manager.main_wallet
    ph = await wallet.get_new_puzzlehash()
    ph_1 = await wallet_1.get_new_puzzlehash()
    ph_2 = await wallet_2.get_new_puzzlehash()

    if trusted:
        wallet_node_0.config["trusted_peers"] = {
            full_node_api.full_node.server.node_id.hex(): full_node_api.full_node.server.node_id.hex()
        }
        wallet_node_1.config["trusted_peers"] = {
            full_node_api.full_node.server.node_id.hex(): full_node_api.full_node.server.node_id.hex()
        }
        wallet_node_2.config["trusted_peers"] = {
            full_node_api.full_node.server.node_id.hex(): full_node_api.full_node.server.node_id.hex()
        }
    else:
        wallet_node_0.config["trusted_peers"] = {}
        wallet_node_1.config["trusted_peers"] = {}
        wallet_node_2.config["trusted_peers"] = {}

    await server_0.start_client(PeerInfo(self_hostname, uint16(full_node_server._port)), None)
    await server_1.start_client(PeerInfo(self_hostname, uint16(full_node_server._port)), None)
    await server_2.start_client(PeerInfo(self_hostname, uint16(full_node_server._port)), None)

    for i in range(0, num_blocks):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph_1))
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph_2))
    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(puzzle_hash_0))

    funds = sum(
        [calculate_pool_reward(uint32(i)) + calculate_base_farmer_reward(uint32(i)) for i in range(1, num_blocks + 1)]
    )

    await time_out_assert(20, wallet.get_confirmed_balance, funds)
    await time_out_assert(20, full_node_api.wallet_is_synced, True, wallet_node_0)

    cat_amt = 300000
    dao_rules = DAORules(
        proposal_timelock=uint64(10),
        soft_close_length=uint64(5),
        attendance_required=uint64(1000),  # 10%
        pass_percentage=uint64(5100),  # 51%
        self_destruct_length=uint64(20),
        oracle_spend_delay=uint64(10),
    )

    async with wallet_node_0.wallet_state_manager.lock:
        dao_wallet_0 = await DAOWallet.create_new_dao_and_wallet(
            wallet_node_0.wallet_state_manager,
            wallet,
            uint64(cat_amt),
            dao_rules,
        )
        assert dao_wallet_0 is not None

    treasury_id = dao_wallet_0.dao_info.treasury_id

    # Get the full node sim to process the wallet creation spend
    tx_queue: List[TransactionRecord] = await wallet_node_0.wallet_state_manager.tx_store.get_not_sent()
    tx_record = tx_queue[0]
    await full_node_api.process_transaction_records(records=[tx_record])
    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(puzzle_hash_0))

    # Farm enough blocks to pass the oracle_spend_delay and then complete the treasury eve spend
    for i in range(1, 11):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(puzzle_hash_0))
    async with wallet_node_0.wallet_state_manager.lock:
        await dao_wallet_0.generate_treasury_eve_spend()
    tx_queue: List[TransactionRecord] = await wallet_node_0.wallet_state_manager.tx_store.get_not_sent()
    tx_record = tx_queue[0]
    await full_node_api.process_transaction_records(records=[tx_record])
    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(puzzle_hash_0))

    # get the cat wallets
    cat_wallet_0 = dao_wallet_0.wallet_state_manager.wallets[dao_wallet_0.dao_info.cat_wallet_id]
    cat_wallet_0_bal = await cat_wallet_0.get_confirmed_balance()
    assert cat_wallet_0_bal == cat_amt

    # get the dao_cat wallet
    dao_cat_wallet_0 = dao_wallet_0.wallet_state_manager.wallets[dao_wallet_0.dao_info.dao_cat_wallet_id]
    
    # Create funding spends for xch and cat
    xch_funds = uint64(500000)
    cat_funds = uint64(100000)
    funding_tx = await dao_wallet_0.create_add_money_to_treasury_spend(xch_funds)
    funding_sb = funding_tx.spend_bundle
    await time_out_assert_not_none(5, full_node_api.full_node.mempool_manager.get_spendbundle, funding_sb.name())
    await full_node_api.process_transaction_records(records=[funding_tx])

    if not trusted:
        await asyncio.sleep(1)
    for i in range(1, num_blocks):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(puzzle_hash_0))

    # Check that the funding spend is recognized by both dao wallets
    xch_bal = await dao_wallet_0.get_balance_by_asset_type()
    assert xch_bal == xch_funds

    cat_funding_tx = await dao_wallet_0.create_add_money_to_treasury_spend(
        cat_funds, funding_wallet_id=cat_wallet_0.id()
    )
    cat_funding_sb = cat_funding_tx.spend_bundle
    await time_out_assert_not_none(5, full_node_api.full_node.mempool_manager.get_spendbundle, cat_funding_sb.name())
    await full_node_api.process_transaction_records(records=[cat_funding_tx])

    if not trusted:
        await asyncio.sleep(1)
    for i in range(1, num_blocks):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(puzzle_hash_0))

    cat_bal = await cat_wallet_0.get_confirmed_balance()
    assert cat_bal == cat_amt - cat_funds

    # Create dao cats for voting
    dao_cat_0_bal = await dao_cat_wallet_0.get_votable_balance()
    txs, new_dao_cats = await dao_cat_wallet_0.create_new_dao_cats(dao_cat_0_bal, True)
    dao_cat_sb = txs[0].spend_bundle
    await time_out_assert_not_none(5, full_node_api.full_node.mempool_manager.get_spendbundle, dao_cat_sb.name())
    await full_node_api.process_transaction_records(records=txs)
    if not trusted:
        await asyncio.sleep(1)
    for i in range(1, num_blocks):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(puzzle_hash_0))
    

    # Create a proposal for xch spend
    recipient_puzzle_hash = await wallet_2.get_new_puzzlehash()
    proposal_amount = 10000
    xch_proposal_inner = dao_wallet_0.generate_simple_proposal_innerpuz(
        [recipient_puzzle_hash],
        [proposal_amount]
    )
    proposal_sb = await dao_wallet_0.generate_new_proposal(xch_proposal_inner, dao_cat_0_bal)
    # await time_out_assert_not_none(5, full_node_api.full_node.mempool_manager.get_spendbundle, proposal_sb.name())
    # await full_node_api.process_transaction_records(records=[proposal_txs])

    # if not trusted:
    #     await asyncio.sleep(1)
    # for i in range(1, num_blocks):
    #     await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(puzzle_hash_0))

    # breakpoint()
