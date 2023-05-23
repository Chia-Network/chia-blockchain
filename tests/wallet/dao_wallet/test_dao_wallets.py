from __future__ import annotations

# mypy: ignore-errors
import asyncio
import time
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

import pytest

from chia.consensus.block_rewards import calculate_base_farmer_reward, calculate_pool_reward
from chia.rpc.wallet_rpc_api import WalletRpcApi
from chia.rpc.wallet_rpc_client import WalletRpcClient
from chia.simulator.setup_nodes import SimulatorsAndWallets, SimulatorsAndWalletsServices
from chia.simulator.simulator_protocol import FarmNewBlockProtocol
from chia.simulator.time_out_assert import adjusted_timeout, time_out_assert, time_out_assert_not_none
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.peer_info import PeerInfo
from chia.util.bech32m import encode_puzzle_hash
from chia.util.ints import uint16, uint32, uint64
from chia.wallet.dao_wallet.dao_info import DAORules
from chia.wallet.dao_wallet.dao_wallet import DAOWallet
from chia.wallet.transaction_record import TransactionRecord
from tests.util.rpc import validate_get_routes


async def get_proposal_state(wallet: DAOWallet, index: int) -> Tuple[bool, bool]:
    return wallet.dao_info.proposals_list[index].passed, wallet.dao_info.proposals_list[index].closed


async def rpc_state(
    timeout: float,
    async_function: Callable[[Dict[str, Any]], Awaitable[Dict]],
    params: List[Dict],
    condition_func: Callable[[Dict[str, Any]], bool],
    result: Optional[Any] = None,
) -> Dict:
    __tracebackhide__ = True

    timeout = adjusted_timeout(timeout=timeout)

    start = time.monotonic()

    while True:
        resp = await async_function(*params)
        assert isinstance(resp, dict)
        try:
            if result:
                if condition_func(resp) == result:
                    return True
            else:
                if condition_func(resp):
                    return resp
        except IndexError:
            continue

        now = time.monotonic()
        elapsed = now - start
        if elapsed >= timeout:
            raise asyncio.TimeoutError(
                f"timed out while waiting for {async_function.__name__}(): {elapsed} >= {timeout}",
            )

        await asyncio.sleep(0.3)


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
        mint_puzzle_hash=None,
        proposal_timelock=uint64(10),
        soft_close_length=uint64(5),
        current_cat_issuance=cat_amt,
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
    # async with wallet_node_0.wallet_state_manager.lock:
    #     await dao_wallet_0.generate_treasury_eve_spend()
    # tx_queue: List[TransactionRecord] = await wallet_node_0.wallet_state_manager.tx_store.get_not_sent()
    # tx_record = tx_queue[0]
    # await full_node_api.process_transaction_records(records=[tx_record])
    # await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(puzzle_hash_0))
    #
    # eve_coin = tx_record.removals[0]
    # await time_out_assert(
    #     60,
    #     dao_wallet_0.is_spend_retrievable,
    #     True,
    #     eve_coin.name(),
    # )

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

    await time_out_assert(10, cat_wallet_1.get_confirmed_balance, cat_amt)


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
        mint_puzzle_hash=None,
        proposal_timelock=uint64(10),
        soft_close_length=uint64(5),
        current_cat_issuance=cat_amt,
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
    # async with wallet_node_0.wallet_state_manager.lock:
    #     await dao_wallet_0.generate_treasury_eve_spend()
    # tx_queue: List[TransactionRecord] = await wallet_node_0.wallet_state_manager.tx_store.get_not_sent()
    # tx_record = tx_queue[0]
    # await full_node_api.process_transaction_records(records=[tx_record])
    # await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(puzzle_hash_0))

    # get the cat wallets
    cat_wallet_0 = dao_wallet_0.wallet_state_manager.wallets[dao_wallet_0.dao_info.cat_wallet_id]
    await time_out_assert(10, cat_wallet_0.get_confirmed_balance, cat_amt)

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
    await time_out_assert(10, dao_wallet_0.get_balance_by_asset_type, xch_funds)

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

    await time_out_assert(10, cat_wallet_0.get_confirmed_balance, cat_amt - cat_funds)

    # Check that the funding spend is found
    cat_id = bytes32.from_hexstr(cat_wallet_0.get_asset_id())
    await time_out_assert(10, dao_wallet_0.get_balance_by_asset_type, cat_funds, cat_id)

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

    await time_out_assert(10, dao_wallet_1.get_balance_by_asset_type, xch_funds)
    await time_out_assert(10, dao_wallet_1.get_balance_by_asset_type, cat_funds, cat_id)

    assert dao_wallet_0.dao_info.assets == [None, cat_id]
    assert dao_wallet_1.dao_info.assets == [None, cat_id]


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
    wallet_2 = wallet_node_2.wallet_state_manager.main_wallet
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
        mint_puzzle_hash=None,
        proposal_timelock=uint64(10),
        soft_close_length=uint64(5),
        current_cat_issuance=cat_amt,
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

    # Get the full node sim to process the wallet creation spend
    tx_queue: List[TransactionRecord] = await wallet_node_0.wallet_state_manager.tx_store.get_not_sent()
    tx_record = tx_queue[0]
    await full_node_api.process_transaction_records(records=[tx_record])
    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(puzzle_hash_0))

    # Farm enough blocks to pass the oracle_spend_delay and then complete the treasury eve spend
    for i in range(1, 11):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(puzzle_hash_0))

    # async with wallet_node_0.wallet_state_manager.lock:
    #     await dao_wallet_0.generate_treasury_eve_spend()
    # tx_queue: List[TransactionRecord] = await wallet_node_0.wallet_state_manager.tx_store.get_not_sent()
    # tx_record = tx_queue[0]
    # await full_node_api.process_transaction_records(records=[tx_record])
    # await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(puzzle_hash_0))

    # get the cat wallets
    cat_wallet_0 = dao_wallet_0.wallet_state_manager.wallets[dao_wallet_0.dao_info.cat_wallet_id]
    await time_out_assert(10, cat_wallet_0.get_confirmed_balance, cat_amt)

    # get the dao_cat wallet
    dao_cat_wallet_0 = dao_wallet_0.wallet_state_manager.wallets[dao_wallet_0.dao_info.dao_cat_wallet_id]

    treasury_id = dao_wallet_0.dao_info.treasury_id

    # Create the other user's wallet from the treasury id
    dao_wallet_1 = await DAOWallet.create_new_dao_wallet_for_existing_dao(
        wallet_node_1.wallet_state_manager,
        wallet_1,
        treasury_id,
    )
    assert dao_wallet_1 is not None
    assert dao_wallet_1.dao_info.treasury_id == treasury_id

    # Create funding spends for xch
    xch_funds = uint64(500000)
    funding_tx = await dao_wallet_0.create_add_money_to_treasury_spend(xch_funds)
    funding_sb = funding_tx.spend_bundle
    await time_out_assert_not_none(5, full_node_api.full_node.mempool_manager.get_spendbundle, funding_sb.name())
    await full_node_api.process_transaction_records(records=[funding_tx])

    if not trusted:
        await asyncio.sleep(1)
    for i in range(1, num_blocks):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(puzzle_hash_0))

    # Check that the funding spend is recognized by both dao wallets
    await time_out_assert(10, dao_wallet_0.get_balance_by_asset_type, xch_funds)

    # Send some dao_cats to wallet_1
    # Get the cat wallets for wallet_1
    cat_wallet_1 = dao_wallet_1.wallet_state_manager.wallets[dao_wallet_1.dao_info.cat_wallet_id]
    dao_cat_wallet_1 = dao_wallet_1.wallet_state_manager.wallets[dao_wallet_1.dao_info.dao_cat_wallet_id]
    assert cat_wallet_1
    assert dao_cat_wallet_1

    cat_tx = await cat_wallet_0.generate_signed_transactions([100000], [ph_1])
    cat_sb = cat_tx[0].spend_bundle
    await wallet.wallet_state_manager.add_pending_transaction(cat_tx[0])
    await time_out_assert_not_none(5, full_node_api.full_node.mempool_manager.get_spendbundle, cat_sb.name())
    await full_node_api.process_transaction_records(records=cat_tx)

    if not trusted:
        await asyncio.sleep(1)
    for i in range(1, num_blocks):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(puzzle_hash_0))

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
        [proposal_amount],
        [None],
    )
    proposal_sb = await dao_wallet_0.generate_new_proposal(xch_proposal_inner, dao_cat_0_bal, uint64(1000))
    await time_out_assert_not_none(5, full_node_api.full_node.mempool_manager.get_spendbundle, proposal_sb.name())
    await full_node_api.process_spend_bundles(bundles=[proposal_sb])

    # Give the wallet nodes a second
    await asyncio.sleep(1)
    for i in range(1, num_blocks):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(puzzle_hash_0))

    # Check the proposal is saved
    assert len(dao_wallet_0.dao_info.proposals_list) == 1
    assert dao_wallet_0.dao_info.proposals_list[0].amount_voted == dao_cat_0_bal
    assert dao_wallet_0.dao_info.proposals_list[0].timer_coin is not None

    # Check that wallet_1 also finds and saved the proposal
    assert len(dao_wallet_1.dao_info.proposals_list) == 1
    prop = dao_wallet_1.dao_info.proposals_list[0]

    # Create votable dao cats and add a new vote
    dao_cat_1_bal = await dao_cat_wallet_1.get_votable_balance()
    txs, new_dao_cats = await dao_cat_wallet_1.create_new_dao_cats(dao_cat_1_bal, True)
    dao_cat_sb = txs[0].spend_bundle
    await time_out_assert_not_none(5, full_node_api.full_node.mempool_manager.get_spendbundle, dao_cat_sb.name())
    await full_node_api.process_transaction_records(records=txs)

    if not trusted:
        await asyncio.sleep(1)
    for i in range(1, num_blocks):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(puzzle_hash_0))

    vote_sb = await dao_wallet_1.generate_proposal_vote_spend(prop.proposal_id, dao_cat_1_bal, True, push=True)
    await time_out_assert_not_none(5, full_node_api.full_node.mempool_manager.get_spendbundle, vote_sb.name())
    await full_node_api.process_spend_bundles(bundles=[vote_sb])

    # Give the wallet nodes a second
    await asyncio.sleep(1)
    for i in range(1, num_blocks):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(puzzle_hash_0))

    total_votes = dao_cat_0_bal + dao_cat_1_bal

    assert dao_wallet_0.dao_info.proposals_list[0].amount_voted == total_votes
    assert dao_wallet_0.dao_info.proposals_list[0].yes_votes == total_votes
    assert dao_wallet_1.dao_info.proposals_list[0].amount_voted == total_votes
    assert dao_wallet_1.dao_info.proposals_list[0].yes_votes == total_votes

    # Add a third wallet and check they can find proposal with accurate vote counts
    dao_wallet_2 = await DAOWallet.create_new_dao_wallet_for_existing_dao(
        wallet_node_2.wallet_state_manager,
        wallet_2,
        treasury_id,
    )
    assert dao_wallet_2 is not None
    assert dao_wallet_2.dao_info.treasury_id == treasury_id

    if not trusted:
        # give the wallet node a second to collect the proposal votes
        await asyncio.sleep(1)
    await time_out_assert(10, len, 1, dao_wallet_2.dao_info.proposals_list)
    await time_out_assert(10, int, total_votes, dao_wallet_2.dao_info.proposals_list[0].amount_voted)

    # Get the proposal from singleton store and check the singleton block height updates correctly
    proposal_state = await dao_wallet_0.get_proposal_state(prop.proposal_id)
    assert proposal_state["passed"]
    assert not proposal_state["closable"]
    assert proposal_state["blocks_needed"] == 2

    for i in range(1, 5):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(puzzle_hash_0))

    proposal_state = await dao_wallet_0.get_proposal_state(prop.proposal_id)
    assert proposal_state["passed"]
    assert proposal_state["closable"]

    # Create an update proposal
    new_dao_rules = DAORules(
        mint_puzzle_hash=None,
        proposal_timelock=uint64(5),
        soft_close_length=uint64(4),
        current_cat_issuance=cat_amt,
        attendance_required=uint64(200000),  # 100%
        pass_percentage=uint64(10000),  # 100%
        self_destruct_length=uint64(8),
        oracle_spend_delay=uint64(2),
    )
    update_inner = await dao_wallet_0.generate_update_proposal_innerpuz(new_dao_rules)
    dao_cat_0_bal = await dao_cat_wallet_0.get_votable_balance()
    proposal_sb = await dao_wallet_0.generate_new_proposal(update_inner, dao_cat_0_bal, uint64(1000))
    await time_out_assert_not_none(5, full_node_api.full_node.mempool_manager.get_spendbundle, proposal_sb.name())
    await full_node_api.process_spend_bundles(bundles=[proposal_sb])

    # Give the wallet nodes a second
    await asyncio.sleep(1)
    for i in range(1, num_blocks):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(puzzle_hash_0))

    # Check the proposal is saved
    assert len(dao_wallet_0.dao_info.proposals_list) == 2
    assert len(dao_wallet_1.dao_info.proposals_list) == 2
    assert len(dao_wallet_2.dao_info.proposals_list) == 2

    # Create a third proposal which will fail
    dao_cat_1_bal = await dao_cat_wallet_1.get_votable_balance()
    recipient_puzzle_hash = await wallet_2.get_new_puzzlehash()
    proposal_amount = 1000
    xch_proposal_inner = dao_wallet_1.generate_simple_proposal_innerpuz(
        [recipient_puzzle_hash], [proposal_amount], [None]
    )
    proposal_sb = await dao_wallet_1.generate_new_proposal(xch_proposal_inner, dao_cat_1_bal, uint64(1000))
    await time_out_assert_not_none(5, full_node_api.full_node.mempool_manager.get_spendbundle, proposal_sb.name())
    await full_node_api.process_spend_bundles(bundles=[proposal_sb])

    # Give the wallet nodes a second
    await asyncio.sleep(1)
    for i in range(1, num_blocks):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(puzzle_hash_0))

    # Check the proposal is saved
    assert len(dao_wallet_0.dao_info.proposals_list) == 3
    assert dao_wallet_0.dao_info.proposals_list[2].amount_voted == dao_cat_1_bal
    assert dao_wallet_0.dao_info.proposals_list[2].timer_coin is not None

    # The  third proposal should be in a "passed" state now, and this will change to "failed"
    # once the treasury update proposal has closed.
    async def check_prop_state(wallet, proposal_id, state):
        prop_state = wallet.get_proposal_state(proposal_id)
        return prop_state[state]

    prop = dao_wallet_0.dao_info.proposals_list[2]
    time_out_assert(20, check_prop_state, True, [dao_wallet_0, prop.proposal_id, "passed"])

    wallet_2_start_bal = await wallet_2.get_confirmed_balance()

    # check the proposal info
    assert not dao_wallet_0.dao_info.proposals_list[0].closed
    assert dao_wallet_0.dao_info.proposals_list[0].passed

    # Close the first proposal
    prop = dao_wallet_0.dao_info.proposals_list[0]
    close_sb = await dao_wallet_0.create_proposal_close_spend(prop.proposal_id, fee=uint64(100))

    await time_out_assert_not_none(5, full_node_api.full_node.mempool_manager.get_spendbundle, close_sb.name())
    await full_node_api.process_spend_bundles(bundles=[close_sb])
    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(puzzle_hash_0))

    # Give the wallet nodes a second and farm enough blocks so we can close the next proposal
    await asyncio.sleep(1)
    for i in range(1, num_blocks):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(puzzle_hash_0))

    time_out_assert(20, wallet_2.get_confirmed_balance, wallet_2_start_bal + proposal_amount)
    time_out_assert(20, dao_wallet_0.get_balance_by_asset_type, xch_funds - proposal_amount)

    time_out_assert(20, get_proposal_state, (True, True), [dao_wallet_0, 0])
    time_out_assert(20, get_proposal_state, (True, True), [dao_wallet_1, 0])
    time_out_assert(20, get_proposal_state, (True, True), [dao_wallet_2, 0])

    # close the update proposal
    prop = dao_wallet_0.dao_info.proposals_list[1]
    while True:
        prop_state = await dao_wallet_0.get_proposal_state(prop.proposal_id)
        if prop_state["closable"]:
            break
        else:
            for i in range(1, prop_state["blocks_needed"]):
                await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(puzzle_hash_0))

    time_out_assert(20, check_prop_state, True, [dao_wallet_0, prop.proposal_id, "passed"])
    time_out_assert(20, check_prop_state, True, [dao_wallet_0, prop.proposal_id, "closable"])

    close_sb = await dao_wallet_0.create_proposal_close_spend(prop.proposal_id)
    await time_out_assert_not_none(5, full_node_api.full_node.mempool_manager.get_spendbundle, close_sb.name())
    await full_node_api.process_spend_bundles(bundles=[close_sb])
    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(puzzle_hash_0))

    # Give the wallet nodes a second and farm enough blocks so we can close the next proposal
    await asyncio.sleep(1)
    for i in range(1, num_blocks):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(puzzle_hash_0))

    async def get_dao_rules(wallet):
        return wallet.dao_rules

    time_out_assert(20, get_dao_rules, new_dao_rules, dao_wallet_0)
    time_out_assert(20, get_dao_rules, new_dao_rules, dao_wallet_1)
    time_out_assert(20, get_dao_rules, new_dao_rules, dao_wallet_2)

    time_out_assert(20, get_proposal_state, (True, True), [dao_wallet_0, 1])
    time_out_assert(20, get_proposal_state, (True, True), [dao_wallet_1, 1])
    time_out_assert(20, get_proposal_state, (True, True), [dao_wallet_2, 1])

    # Have wallet_0 vote against the proposal
    prop = dao_wallet_0.dao_info.proposals_list[2]
    vote_sb = await dao_wallet_0.generate_proposal_vote_spend(prop.proposal_id, dao_cat_0_bal, False, push=True)
    await time_out_assert_not_none(5, full_node_api.full_node.mempool_manager.get_spendbundle, vote_sb.name())
    await full_node_api.process_spend_bundles(bundles=[vote_sb])
    await asyncio.sleep(1)
    # farm enough blocks to close the proposal
    for i in range(1, 12):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(puzzle_hash_0))

    time_out_assert(20, check_prop_state, True, [dao_wallet_0, prop.proposal_id, "closable"])
    time_out_assert(20, check_prop_state, False, [dao_wallet_0, prop.proposal_id, "passed"])
    await asyncio.sleep(1)
    try:
        close_sb = await dao_wallet_0.create_proposal_close_spend(prop.proposal_id, fee=uint64(100), push=True)
    except Exception as e:
        print(e)
    # await time_out_assert_not_none(10, full_node_api.full_node.mempool_manager.get_spendbundle, close_sb.name())
    # await full_node_api.process_spend_bundles(bundles=[close_sb])
    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(puzzle_hash_0))

    # Give the wallet nodes a second and farm enough blocks so we can close the next proposal
    await asyncio.sleep(2)
    for i in range(1, num_blocks):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(puzzle_hash_0))

    time_out_assert(20, get_proposal_state, (False, True), [dao_wallet_0, 2])
    time_out_assert(20, get_proposal_state, (False, True), [dao_wallet_1, 2])
    time_out_assert(20, get_proposal_state, (False, True), [dao_wallet_2, 2])

    # Finally create a broken proposal and force close
    dao_cat_0_bal = await dao_cat_wallet_0.get_votable_balance()
    recipient_puzzle_hash = await wallet_2.get_new_puzzlehash()
    proposal_amount = 5000
    xch_proposal_inner = Program.to(["x"])
    proposal_sb = await dao_wallet_0.generate_new_proposal(xch_proposal_inner, dao_cat_0_bal, uint64(1000))
    await time_out_assert_not_none(20, full_node_api.full_node.mempool_manager.get_spendbundle, proposal_sb.name())
    await full_node_api.process_spend_bundles(bundles=[proposal_sb])

    # Give the wallet nodes a second
    await asyncio.sleep(1)
    for i in range(1, 12):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(puzzle_hash_0))

    # Check the proposal is passed and closable
    prop = dao_wallet_0.dao_info.proposals_list[3]
    time_out_assert(20, get_proposal_state, (True, True), [dao_wallet_0, 2])

    with pytest.raises(Exception) as e_info:
        close_sb = await dao_wallet_0.create_proposal_close_spend(prop.proposal_id, fee=uint64(100), push=True)
    assert e_info.value.args[0] == "Unrecognised proposal type"

    close_sb = await dao_wallet_0.create_proposal_close_spend(
        prop.proposal_id, fee=uint64(100), push=True, self_destruct=True
    )
    await time_out_assert_not_none(20, full_node_api.full_node.mempool_manager.get_spendbundle, close_sb.name())
    await full_node_api.process_spend_bundles(bundles=[close_sb])
    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(puzzle_hash_0))

    # Give the wallet nodes a second and farm enough blocks so we can close the next proposal
    await asyncio.sleep(1)
    for i in range(1, num_blocks):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(puzzle_hash_0))

    time_out_assert(20, get_proposal_state, (True, True), [dao_wallet_0, 2])
    time_out_assert(20, get_proposal_state, (True, True), [dao_wallet_1, 2])
    time_out_assert(20, get_proposal_state, (True, True), [dao_wallet_2, 2])


@pytest.mark.parametrize(
    "trusted",
    [True, False],
)
@pytest.mark.asyncio
async def test_dao_proposal_partial_vote(
    self_hostname: str, three_wallet_nodes: SimulatorsAndWallets, trusted: bool
) -> None:
    num_blocks = 3
    full_nodes, wallets, _ = three_wallet_nodes
    full_node_api = full_nodes[0]
    full_node_server = full_node_api.server
    wallet_node_0, server_0 = wallets[0]
    wallet_node_1, server_1 = wallets[1]
    wallet_node_2, server_2 = wallets[2]
    wallet = wallet_node_0.wallet_state_manager.main_wallet
    wallet_1 = wallet_node_1.wallet_state_manager.main_wallet
    wallet_2 = wallet_node_2.wallet_state_manager.main_wallet
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
        mint_puzzle_hash=None,
        proposal_timelock=uint64(10),
        soft_close_length=uint64(5),
        current_cat_issuance=cat_amt,
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

    # Get the full node sim to process the wallet creation spend
    tx_queue: List[TransactionRecord] = await wallet_node_0.wallet_state_manager.tx_store.get_not_sent()
    tx_record = tx_queue[0]
    await full_node_api.process_transaction_records(records=[tx_record])
    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(puzzle_hash_0))

    # Farm enough blocks to pass the oracle_spend_delay and then complete the treasury eve spend
    for i in range(1, 11):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(puzzle_hash_0))

    # async with wallet_node_0.wallet_state_manager.lock:
    #     await dao_wallet_0.generate_treasury_eve_spend()
    # tx_queue: List[TransactionRecord] = await wallet_node_0.wallet_state_manager.tx_store.get_not_sent()
    # tx_record = tx_queue[0]
    # await full_node_api.process_transaction_records(records=[tx_record])
    # await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(puzzle_hash_0))

    # get the cat wallets
    cat_wallet_0 = dao_wallet_0.wallet_state_manager.wallets[dao_wallet_0.dao_info.cat_wallet_id]
    await time_out_assert(10, cat_wallet_0.get_confirmed_balance, cat_amt)

    # get the dao_cat wallet
    dao_cat_wallet_0 = dao_wallet_0.wallet_state_manager.wallets[dao_wallet_0.dao_info.dao_cat_wallet_id]

    treasury_id = dao_wallet_0.dao_info.treasury_id

    # Create the other user's wallet from the treasury id
    dao_wallet_1 = await DAOWallet.create_new_dao_wallet_for_existing_dao(
        wallet_node_1.wallet_state_manager,
        wallet_1,
        treasury_id,
    )
    assert dao_wallet_1 is not None
    assert dao_wallet_1.dao_info.treasury_id == treasury_id

    # Create funding spends for xch
    xch_funds = uint64(500000)
    funding_tx = await dao_wallet_0.create_add_money_to_treasury_spend(xch_funds)
    funding_sb = funding_tx.spend_bundle
    await time_out_assert_not_none(5, full_node_api.full_node.mempool_manager.get_spendbundle, funding_sb.name())
    await full_node_api.process_transaction_records(records=[funding_tx])

    if not trusted:
        await asyncio.sleep(1)
    for i in range(1, num_blocks):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(puzzle_hash_0))

    # Check that the funding spend is recognized by both dao wallets
    await time_out_assert(10, dao_wallet_0.get_balance_by_asset_type, xch_funds)

    # Send some dao_cats to wallet_1
    # Get the cat wallets for wallet_1
    cat_wallet_1 = dao_wallet_1.wallet_state_manager.wallets[dao_wallet_1.dao_info.cat_wallet_id]
    dao_cat_wallet_1 = dao_wallet_1.wallet_state_manager.wallets[dao_wallet_1.dao_info.dao_cat_wallet_id]
    assert cat_wallet_1
    assert dao_cat_wallet_1

    cat_tx = await cat_wallet_0.generate_signed_transactions([100000], [ph_1])
    cat_sb = cat_tx[0].spend_bundle
    await wallet.wallet_state_manager.add_pending_transaction(cat_tx[0])
    await time_out_assert_not_none(5, full_node_api.full_node.mempool_manager.get_spendbundle, cat_sb.name())
    await full_node_api.process_transaction_records(records=cat_tx)

    if not trusted:
        await asyncio.sleep(1)
    for i in range(1, num_blocks):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(puzzle_hash_0))

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

    # Create a mint proposal
    recipient_puzzle_hash = await cat_wallet_1.get_new_inner_hash()
    new_mint_amount = 500
    mint_proposal_inner = await dao_wallet_0.generate_mint_proposal_innerpuz(
        new_mint_amount,
        recipient_puzzle_hash,
    )
    # (
    #     [recipient_puzzle_hash],
    #     [proposal_amount],
    #     [None],
    # )
    proposal_sb = await dao_wallet_0.generate_new_proposal(mint_proposal_inner, dao_cat_0_bal, uint64(1000))
    await time_out_assert_not_none(5, full_node_api.full_node.mempool_manager.get_spendbundle, proposal_sb.name())
    await full_node_api.process_spend_bundles(bundles=[proposal_sb])

    # Give the wallet nodes a second
    await asyncio.sleep(1)
    for i in range(1, num_blocks):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(puzzle_hash_0))

    # Check the proposal is saved
    assert len(dao_wallet_0.dao_info.proposals_list) == 1
    assert dao_wallet_0.dao_info.proposals_list[0].amount_voted == dao_cat_0_bal
    assert dao_wallet_0.dao_info.proposals_list[0].timer_coin is not None

    # Check that wallet_1 also finds and saved the proposal
    assert len(dao_wallet_1.dao_info.proposals_list) == 1
    prop = dao_wallet_1.dao_info.proposals_list[0]

    # Create votable dao cats and add a new vote
    dao_cat_1_bal = await dao_cat_wallet_1.get_votable_balance()
    txs, new_dao_cats = await dao_cat_wallet_1.create_new_dao_cats(dao_cat_1_bal, True)
    dao_cat_sb = txs[0].spend_bundle
    await time_out_assert_not_none(5, full_node_api.full_node.mempool_manager.get_spendbundle, dao_cat_sb.name())
    await full_node_api.process_transaction_records(records=txs)

    if not trusted:
        await asyncio.sleep(1)
    for i in range(1, num_blocks):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(puzzle_hash_0))

    vote_sb = await dao_wallet_1.generate_proposal_vote_spend(prop.proposal_id, dao_cat_1_bal // 2, True, push=True)
    await time_out_assert_not_none(5, full_node_api.full_node.mempool_manager.get_spendbundle, vote_sb.name())
    await full_node_api.process_spend_bundles(bundles=[vote_sb])

    # Give the wallet nodes a second
    await asyncio.sleep(1)
    for i in range(1, dao_rules.proposal_timelock + 1):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(puzzle_hash_0))

    total_votes = dao_cat_0_bal + dao_cat_1_bal // 2

    assert dao_wallet_0.dao_info.proposals_list[0].amount_voted == total_votes
    assert dao_wallet_0.dao_info.proposals_list[0].yes_votes == total_votes
    assert dao_wallet_1.dao_info.proposals_list[0].amount_voted == total_votes
    assert dao_wallet_1.dao_info.proposals_list[0].yes_votes == total_votes

    try:
        close_sb = await dao_wallet_0.create_proposal_close_spend(prop.proposal_id, fee=uint64(100), push=True)
    except Exception as e:
        print(e)
    # await time_out_assert_not_none(10, full_node_api.full_node.mempool_manager.get_spendbundle, close_sb.name())
    await full_node_api.process_spend_bundles(bundles=[close_sb])
    balance = await cat_wallet_1.get_spendable_balance()
    # breakpoint()
    assert close_sb is not None
    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(puzzle_hash_0))

    # Give the wallet nodes a second and farm enough blocks so we can close the next proposal
    await asyncio.sleep(2)
    for i in range(1, num_blocks):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(puzzle_hash_0))

    await time_out_assert(20, get_proposal_state, (True, True), dao_wallet_0, 0)
    await time_out_assert(20, get_proposal_state, (True, True), dao_wallet_1, 0)

    await time_out_assert(20, cat_wallet_1.get_spendable_balance, balance + new_mint_amount)
    # breakpoint()


@pytest.mark.parametrize(
    "trusted",
    [True, False],
)
@pytest.mark.asyncio
async def test_dao_rpc_api(self_hostname: str, two_wallet_nodes: Any, trusted: Any) -> None:
    num_blocks = 3
    full_nodes, wallets, _ = two_wallet_nodes
    full_node_api = full_nodes[0]
    full_node_server = full_node_api.server
    wallet_node_0, server_0 = wallets[0]
    wallet_node_1, server_1 = wallets[1]
    wallet_0 = wallet_node_0.wallet_state_manager.main_wallet
    wallet_1 = wallet_node_1.wallet_state_manager.main_wallet

    ph_0 = await wallet_0.get_new_puzzlehash()
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

    for i in range(1, num_blocks):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph_0))
    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(puzzle_hash_0))

    funds = sum(
        [calculate_pool_reward(uint32(i)) + calculate_base_farmer_reward(uint32(i)) for i in range(1, num_blocks)]
    )

    await time_out_assert(30, wallet_0.get_unconfirmed_balance, funds)
    await time_out_assert(30, wallet_0.get_confirmed_balance, funds)
    await time_out_assert(30, wallet_node_0.wallet_state_manager.synced, True)
    api_0 = WalletRpcApi(wallet_node_0)
    api_1 = WalletRpcApi(wallet_node_1)
    await full_node_api.wait_for_wallet_synced(wallet_node=wallet_node_0, timeout=30)

    cat_amt = 300000
    fee = 10000
    dao_rules = DAORules(
        mint_puzzle_hash=None,
        proposal_timelock=uint64(10),
        soft_close_length=uint64(5),
        current_cat_issuance=cat_amt,
        attendance_required=uint64(1000),  # 10%
        pass_percentage=uint64(5100),  # 51%
        self_destruct_length=uint64(20),
        oracle_spend_delay=uint64(10),
    )

    dao_wallet_0 = await api_0.create_new_wallet(
        dict(
            wallet_type="dao_wallet",
            name="DAO WALLET 1",
            mode="new",
            dao_rules=dao_rules,
            amount_of_cats=cat_amt,
            filter_amount=1,
            fee=fee,
        )
    )
    assert isinstance(dao_wallet_0, dict)
    assert dao_wallet_0.get("success")
    dao_wallet_0_id = dao_wallet_0["wallet_id"]
    dao_cat_wallet_0_id = dao_wallet_0["cat_wallet_id"]
    treasury_id = bytes32(dao_wallet_0["treasury_id"])
    spend_bundle_list = await wallet_node_0.wallet_state_manager.tx_store.get_unconfirmed_for_wallet(dao_wallet_0_id)
    spend_bundle = spend_bundle_list[0].spend_bundle
    await time_out_assert_not_none(30, full_node_api.full_node.mempool_manager.get_spendbundle, spend_bundle.name())

    for _ in range(1, num_blocks):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(puzzle_hash_0))

    await time_out_assert(30, wallet_0.get_pending_change_balance, 0)
    expected_xch = funds - 1 - cat_amt - fee
    await time_out_assert(30, wallet_0.get_confirmed_balance, expected_xch)

    dao_wallet_1 = await api_1.create_new_wallet(
        dict(
            wallet_type="dao_wallet",
            name="DAO WALLET 2",
            mode="existing",
            treasury_id=treasury_id.hex(),
            filter_amount=1,
        )
    )
    assert isinstance(dao_wallet_1, dict)
    assert dao_wallet_1.get("success")
    dao_wallet_1_id = dao_wallet_1["wallet_id"]
    # Create a cat wallet and add funds to treasury
    new_cat_amt = 1000000000000
    cat_wallet_0 = await api_0.create_new_wallet(
        dict(
            wallet_type="cat_wallet",
            name="CAT WALLET 1",
            mode="new",
            amount=new_cat_amt,
        )
    )
    tx_queue: List[TransactionRecord] = await wallet_node_0.wallet_state_manager.tx_store.get_not_sent()
    await full_node_api.process_transaction_records(records=[tx for tx in tx_queue])
    for _ in range(1, num_blocks):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(puzzle_hash_0))

    cat_wallet_0_id = cat_wallet_0["wallet_id"]
    cat_id = bytes32.from_hexstr(cat_wallet_0["asset_id"])

    await rpc_state(
        20,
        api_0.get_wallet_balance,
        [{"wallet_id": cat_wallet_0_id}],
        lambda x: x["wallet_balance"]["confirmed_wallet_balance"],
        new_cat_amt,
    )

    cat_funding_amt = 500000
    await api_0.dao_add_funds_to_treasury(
        dict(
            wallet_id=dao_wallet_0_id,
            amount=cat_funding_amt,
            funding_wallet_id=cat_wallet_0_id,
        )
    )

    xch_funding_amt = 200000
    await api_0.dao_add_funds_to_treasury(
        dict(
            wallet_id=dao_wallet_0_id,
            amount=xch_funding_amt,
            funding_wallet_id=1,
        )
    )
    tx_queue: List[TransactionRecord] = await wallet_node_0.wallet_state_manager.tx_store.get_not_sent()
    await full_node_api.process_transaction_records(records=[tx for tx in tx_queue])
    for _ in range(1, num_blocks):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(puzzle_hash_0))

    expected_xch -= xch_funding_amt + new_cat_amt
    await time_out_assert(30, wallet_0.get_confirmed_balance, expected_xch)

    await rpc_state(
        20,
        api_0.get_wallet_balance,
        [{"wallet_id": cat_wallet_0_id}],
        lambda x: x["wallet_balance"]["confirmed_wallet_balance"],
        new_cat_amt - cat_funding_amt,
    )

    balances = await api_1.dao_get_treasury_balance({"wallet_id": dao_wallet_1_id})
    assert balances["balances"][None] == xch_funding_amt
    assert balances["balances"][cat_id] == cat_funding_amt

    # Send some cats to wallet_1
    await api_0.cat_spend(
        {
            "wallet_id": dao_cat_wallet_0_id,
            "amount": cat_amt // 2,
            "inner_address": encode_puzzle_hash(ph_1, "xch"),
            "fee": fee,
        }
    )
    tx_queue: List[TransactionRecord] = await wallet_node_0.wallet_state_manager.tx_store.get_not_sent()
    await full_node_api.process_transaction_records(records=[tx for tx in tx_queue])
    for _ in range(1, num_blocks):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(puzzle_hash_0))

    await rpc_state(
        20,
        api_0.get_wallet_balance,
        [{"wallet_id": dao_cat_wallet_0_id}],
        lambda x: x["wallet_balance"]["confirmed_wallet_balance"],
        cat_amt // 2,
    )

    # send cats to lockup
    await api_0.dao_send_to_lockup({"wallet_id": dao_wallet_0_id, "amount": cat_amt // 2})
    tx_queue: List[TransactionRecord] = await wallet_node_0.wallet_state_manager.tx_store.get_not_sent()
    await full_node_api.process_transaction_records(records=[tx for tx in tx_queue])
    await api_1.dao_send_to_lockup({"wallet_id": dao_wallet_1_id, "amount": cat_amt // 2})
    tx_queue: List[TransactionRecord] = await wallet_node_1.wallet_state_manager.tx_store.get_not_sent()
    await full_node_api.process_transaction_records(records=[tx for tx in tx_queue])
    for _ in range(1, num_blocks):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(puzzle_hash_0))

    # create the first proposal
    additions = [
        {"puzzle_hash": ph_1.hex(), "amount": 1000},
        # {"puzzle_hash": ph_1.hex(), "amount": 2000, "asset_id": cat_id.hex()},
    ]
    create_proposal = await api_0.dao_create_proposal(
        {
            "wallet_id": dao_wallet_0_id,
            "proposal_type": "spend",
            "additions": additions,
            # "amount": 100,
            # "inner_address": encode_puzzle_hash(ph_1, "xch"),
            "vote_amount": cat_amt // 2,
            "fee": fee,
        }
    )
    assert create_proposal["success"]
    tx_queue: List[TransactionRecord] = await wallet_node_0.wallet_state_manager.tx_store.get_not_sent()
    await full_node_api.process_transaction_records(records=[tx for tx in tx_queue])
    for _ in range(1, num_blocks):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(puzzle_hash_0))

    await rpc_state(20, api_0.dao_get_proposals, [{"wallet_id": dao_wallet_0_id}], lambda x: len(x["proposals"]), 1)

    await rpc_state(20, api_1.dao_get_proposals, [{"wallet_id": dao_wallet_1_id}], lambda x: len(x["proposals"]), 1)

    props_0 = await api_0.dao_get_proposals({"wallet_id": dao_wallet_0_id})
    prop = props_0["proposals"][0]
    assert prop.amount_voted == cat_amt // 2
    assert prop.yes_votes == cat_amt // 2

    state = await api_0.dao_get_proposal_state({"wallet_id": dao_wallet_0_id, "proposal_id": prop.proposal_id.hex()})
    assert state["state"]["passed"]
    assert not state["state"]["closable"]

    # Add votes
    await api_1.dao_vote_on_proposal(
        {
            "wallet_id": dao_wallet_1_id,
            "vote_amount": cat_amt // 2,
            "proposal_id": prop.proposal_id.hex(),
            "is_yes_vote": True,
        }
    )
    tx_queue: List[TransactionRecord] = await wallet_node_1.wallet_state_manager.tx_store.get_not_sent()
    await full_node_api.process_transaction_records(records=[tx for tx in tx_queue])
    for _ in range(1, num_blocks):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(puzzle_hash_0))

    await rpc_state(
        20, api_0.dao_get_proposals, [{"wallet_id": dao_wallet_0_id}], lambda x: x["proposals"][0].amount_voted, cat_amt
    )

    # farm blocks until we can close proposal
    for _ in range(1, state["state"]["blocks_needed"]):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(puzzle_hash_0))

    await rpc_state(
        20,
        api_0.dao_get_proposal_state,
        [{"wallet_id": dao_wallet_0_id, "proposal_id": prop.proposal_id.hex()}],
        lambda x: x["state"]["closable"],
        True,
    )

    await api_0.dao_close_proposal({"wallet_id": dao_wallet_0_id, "proposal_id": prop.proposal_id.hex()})
    tx_queue: List[TransactionRecord] = await wallet_node_0.wallet_state_manager.tx_store.get_not_sent()
    await full_node_api.process_transaction_records(records=[tx for tx in tx_queue])
    for _ in range(1, num_blocks):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(puzzle_hash_0))

    await rpc_state(
        20, api_0.dao_get_proposals, [{"wallet_id": dao_wallet_0_id}], lambda x: x["proposals"][0].closed, True
    )


@pytest.mark.parametrize(
    "trusted",
    [True, False],
)
@pytest.mark.asyncio
async def test_dao_rpc_client(
    two_wallet_nodes_services: SimulatorsAndWalletsServices, trusted: bool, self_hostname: str
) -> None:
    num_blocks = 3
    [full_node_service], wallet_services, bt = two_wallet_nodes_services
    full_node_api = full_node_service._api
    full_node_server = full_node_api.full_node.server
    wallet_node_0 = wallet_services[0]._node
    server_0 = wallet_node_0.server
    wallet_node_1 = wallet_services[1]._node
    server_1 = wallet_node_1.server
    wallet_0 = wallet_node_0.wallet_state_manager.main_wallet
    wallet_1 = wallet_node_1.wallet_state_manager.main_wallet
    ph_0 = await wallet_0.get_new_puzzlehash()
    ph_1 = await wallet_1.get_new_puzzlehash()

    if trusted:
        wallet_node_0.config["trusted_peers"] = {full_node_server.node_id.hex(): full_node_server.node_id.hex()}
        wallet_node_1.config["trusted_peers"] = {full_node_server.node_id.hex(): full_node_server.node_id.hex()}
    else:
        wallet_node_0.config["trusted_peers"] = {}
        wallet_node_1.config["trusted_peers"] = {}

    await server_0.start_client(PeerInfo(self_hostname, uint16(full_node_server._port)), None)
    await server_1.start_client(PeerInfo(self_hostname, uint16(full_node_server._port)), None)

    for i in range(1, num_blocks):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph_0))
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph_1))
    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(puzzle_hash_0))

    initial_funds = sum(
        [calculate_pool_reward(uint32(i)) + calculate_base_farmer_reward(uint32(i)) for i in range(1, num_blocks)]
    )

    await time_out_assert(15, wallet_0.get_confirmed_balance, initial_funds)
    await time_out_assert(15, wallet_0.get_unconfirmed_balance, initial_funds)

    assert wallet_services[0].rpc_server is not None
    assert wallet_services[1].rpc_server is not None

    client_0 = await WalletRpcClient.create(
        self_hostname,
        wallet_services[0].rpc_server.listen_port,
        wallet_services[0].root_path,
        wallet_services[0].config,
    )
    await validate_get_routes(client_0, wallet_services[0].rpc_server.rpc_api)
    client_1 = await WalletRpcClient.create(
        self_hostname,
        wallet_services[1].rpc_server.listen_port,
        wallet_services[1].root_path,
        wallet_services[1].config,
    )
    await validate_get_routes(client_1, wallet_services[1].rpc_server.rpc_api)

    try:
        cat_amt = 150000
        amount_of_cats = cat_amt * 2
        dao_rules = DAORules(
            mint_puzzle_hash=None,
            proposal_timelock=uint64(8),
            soft_close_length=uint64(4),
            current_cat_issuance=cat_amt,
            attendance_required=uint64(1000),  # 10%
            pass_percentage=uint64(5100),  # 51%
            self_destruct_length=uint64(20),
            oracle_spend_delay=uint64(10),
        )
        filter_amount = 1
        fee = 10000

        # create new dao
        dao_wallet_dict_0 = await client_0.create_new_dao_wallet(
            mode="new",
            dao_rules=dao_rules.to_json_dict(),
            amount_of_cats=amount_of_cats,
            filter_amount=filter_amount,
            name="DAO WALLET 0",
        )
        assert dao_wallet_dict_0["success"]
        dao_id_0 = dao_wallet_dict_0["wallet_id"]
        treasury_id_hex = dao_wallet_dict_0["treasury_id"]
        cat_wallet_0 = wallet_node_0.wallet_state_manager.wallets[dao_wallet_dict_0["cat_wallet_id"]]

        for i in range(1, num_blocks):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(puzzle_hash_0))
            await asyncio.sleep(0.5)  # add sleep after block per client testing in other wallets

        await time_out_assert(20, cat_wallet_0.get_confirmed_balance, amount_of_cats)

        # join dao
        dao_wallet_dict_1 = await client_1.create_new_dao_wallet(
            mode="existing", treasury_id=treasury_id_hex, filter_amount=filter_amount, name="DAO WALLET 1"
        )
        assert dao_wallet_dict_1["success"]
        dao_id_1 = dao_wallet_dict_1["wallet_id"]
        cat_wallet_1 = wallet_node_1.wallet_state_manager.wallets[dao_wallet_dict_1["cat_wallet_id"]]

        # fund treasury
        xch_funds = 10000000000
        funding_tx = await client_0.dao_add_funds_to_treasury(dao_id_0, 1, xch_funds)
        assert funding_tx["success"]
        for i in range(1, num_blocks):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(puzzle_hash_0))
            await asyncio.sleep(0.5)

        await rpc_state(20, client_0.dao_get_treasury_balance, [dao_id_0], lambda x: x["balances"]["null"], xch_funds)

        # send cats to wallet 1
        await client_0.cat_spend(
            wallet_id=dao_wallet_dict_0["cat_wallet_id"],
            amount=cat_amt,
            inner_address=encode_puzzle_hash(ph_1, "xch"),
            fee=fee,
        )

        for i in range(1, num_blocks):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(puzzle_hash_0))
            await asyncio.sleep(0.5)

        await time_out_assert(20, cat_wallet_0.get_confirmed_balance, cat_amt)
        await time_out_assert(20, cat_wallet_1.get_confirmed_balance, cat_amt)

        # send cats to lockup
        lockup_0 = await client_0.dao_send_to_lockup(dao_id_0, cat_amt)
        lockup_1 = await client_1.dao_send_to_lockup(dao_id_1, cat_amt)
        assert lockup_0["success"]
        assert lockup_1["success"]

        for i in range(1, num_blocks):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(puzzle_hash_0))
            await asyncio.sleep(0.5)

        # create a spend proposal
        # TODO: Fix handling of comples spends
        additions = [
            {"puzzle_hash": ph_1.hex(), "amount": 1000},
        ]
        proposal = await client_0.dao_create_proposal(
            wallet_id=dao_id_0,
            proposal_type="spend",
            additions=additions,
            vote_amount=cat_amt,
            # inner_address=encode_puzzle_hash(ph_1, "xch"),
            fee=fee,
        )
        assert proposal["success"]
        for i in range(1, num_blocks):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(puzzle_hash_0))
            await asyncio.sleep(0.5)

        # check proposal is found by wallet 1
        await rpc_state(20, client_1.dao_get_proposals, [dao_id_1], lambda x: x["proposals"][0]["yes_votes"], cat_amt)
        props = await client_1.dao_get_proposals(dao_id_1)
        proposal_id_hex = props["proposals"][0]["proposal_id"]

        # vote spend
        vote = await client_1.dao_vote_on_proposal(
            wallet_id=dao_id_1, proposal_id=proposal_id_hex, vote_amount=cat_amt, is_yes_vote=True, fee=fee
        )
        assert vote["success"]
        for i in range(1, num_blocks):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(puzzle_hash_0))
            await asyncio.sleep(0.5)

        # check updated proposal is found by wallet 0
        await rpc_state(
            20, client_0.dao_get_proposals, [dao_id_0], lambda x: x["proposals"][0]["yes_votes"], cat_amt * 2
        )

        # check proposal state and farm enough blocks to pass
        state = await client_0.dao_get_proposal_state(wallet_id=dao_id_0, proposal_id=proposal_id_hex)
        assert state["success"]
        assert state["state"]["passed"]

        for _ in range(0, state["state"]["blocks_needed"]):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(puzzle_hash_0))
            await asyncio.sleep(0.5)

        state = await client_0.dao_get_proposal_state(wallet_id=dao_id_0, proposal_id=proposal_id_hex)
        assert state["success"]
        assert state["state"]["closable"]

        # close the proposal
        close = await client_0.dao_close_proposal(wallet_id=dao_id_0, proposal_id=proposal_id_hex, fee=fee)
        assert close["success"]

        for i in range(1, num_blocks):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(puzzle_hash_0))
            await asyncio.sleep(0.5)

        # check proposal is closed
        await rpc_state(20, client_1.dao_get_proposals, [dao_id_1], lambda x: x["proposals"][0]["closed"], True)
        await rpc_state(20, client_0.dao_get_proposals, [dao_id_0], lambda x: x["proposals"][0]["closed"], True)

        # free locked cats from finished proposal
        res = await client_0.dao_free_coins_from_finished_proposals(wallet_id=dao_id_0)
        assert res["success"]
        sb_name = bytes32.from_hexstr(res["spend_name"])
        await time_out_assert_not_none(5, full_node_api.full_node.mempool_manager.get_spendbundle, sb_name)

        for i in range(1, num_blocks):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(puzzle_hash_0))
            await asyncio.sleep(0.5)

        bal = await client_0.get_wallet_balance(dao_wallet_dict_0["dao_cat_wallet_id"])
        assert bal["confirmed_wallet_balance"] == cat_amt

        exit = await client_0.dao_exit_lockup(dao_id_0)
        assert exit["success"]
        for i in range(1, num_blocks):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(puzzle_hash_0))
            await asyncio.sleep(0.5)

    finally:
        client_0.close()
        client_1.close()
        await client_0.await_closed()
        await client_1.await_closed()


@pytest.mark.parametrize(
    "trusted",
    [True, False],
)
@pytest.mark.asyncio
async def test_dao_cat_exits(
    two_wallet_nodes_services: SimulatorsAndWalletsServices, trusted: bool, self_hostname: str
) -> None:
    num_blocks = 3
    [full_node_service], wallet_services, bt = two_wallet_nodes_services
    full_node_api = full_node_service._api
    full_node_server = full_node_api.full_node.server
    wallet_node_0 = wallet_services[0]._node
    server_0 = wallet_node_0.server
    wallet_node_1 = wallet_services[1]._node
    server_1 = wallet_node_1.server
    wallet_0 = wallet_node_0.wallet_state_manager.main_wallet
    wallet_1 = wallet_node_1.wallet_state_manager.main_wallet
    ph_0 = await wallet_0.get_new_puzzlehash()
    ph_1 = await wallet_1.get_new_puzzlehash()

    if trusted:
        wallet_node_0.config["trusted_peers"] = {full_node_server.node_id.hex(): full_node_server.node_id.hex()}
        wallet_node_1.config["trusted_peers"] = {full_node_server.node_id.hex(): full_node_server.node_id.hex()}
    else:
        wallet_node_0.config["trusted_peers"] = {}
        wallet_node_1.config["trusted_peers"] = {}

    await server_0.start_client(PeerInfo(self_hostname, uint16(full_node_server._port)), None)
    await server_1.start_client(PeerInfo(self_hostname, uint16(full_node_server._port)), None)

    for i in range(1, num_blocks):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph_0))
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph_1))
    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(puzzle_hash_0))

    initial_funds = sum(
        [calculate_pool_reward(uint32(i)) + calculate_base_farmer_reward(uint32(i)) for i in range(1, num_blocks)]
    )

    await time_out_assert(15, wallet_0.get_confirmed_balance, initial_funds)
    await time_out_assert(15, wallet_0.get_unconfirmed_balance, initial_funds)

    assert wallet_services[0].rpc_server is not None
    assert wallet_services[1].rpc_server is not None

    client_0 = await WalletRpcClient.create(
        self_hostname,
        wallet_services[0].rpc_server.listen_port,
        wallet_services[0].root_path,
        wallet_services[0].config,
    )
    await validate_get_routes(client_0, wallet_services[0].rpc_server.rpc_api)
    client_1 = await WalletRpcClient.create(
        self_hostname,
        wallet_services[1].rpc_server.listen_port,
        wallet_services[1].root_path,
        wallet_services[1].config,
    )
    await validate_get_routes(client_1, wallet_services[1].rpc_server.rpc_api)

    try:
        cat_amt = 150000
        amount_of_cats = cat_amt
        dao_rules = DAORules(
            mint_puzzle_hash=None,
            proposal_timelock=uint64(8),
            soft_close_length=uint64(4),
            current_cat_issuance=cat_amt,
            attendance_required=uint64(1000),  # 10%
            pass_percentage=uint64(5100),  # 51%
            self_destruct_length=uint64(20),
            oracle_spend_delay=uint64(10),
        )
        filter_amount = 1
        fee = 10000

        # create new dao
        dao_wallet_dict_0 = await client_0.create_new_dao_wallet(
            mode="new",
            dao_rules=dao_rules.to_json_dict(),
            amount_of_cats=amount_of_cats,
            filter_amount=filter_amount,
            name="DAO WALLET 0",
        )
        assert dao_wallet_dict_0["success"]
        dao_id_0 = dao_wallet_dict_0["wallet_id"]
        # treasury_id_hex = dao_wallet_dict_0["treasury_id"]
        cat_wallet_0 = wallet_node_0.wallet_state_manager.wallets[dao_wallet_dict_0["cat_wallet_id"]]
        dao_cat_wallet_0 = wallet_node_0.wallet_state_manager.wallets[dao_wallet_dict_0["dao_cat_wallet_id"]]

        for i in range(1, num_blocks):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(puzzle_hash_0))
            await asyncio.sleep(0.5)  # add sleep after block per client testing in other wallets

        await time_out_assert(20, cat_wallet_0.get_confirmed_balance, amount_of_cats)

        # fund treasury
        xch_funds = 10000000000
        funding_tx = await client_0.dao_add_funds_to_treasury(dao_id_0, 1, xch_funds)
        assert funding_tx["success"]
        for i in range(1, num_blocks):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(puzzle_hash_0))
            await asyncio.sleep(0.5)

        await rpc_state(20, client_0.dao_get_treasury_balance, [dao_id_0], lambda x: x["balances"]["null"], xch_funds)

        # send cats to lockup
        lockup_0 = await client_0.dao_send_to_lockup(dao_id_0, cat_amt)
        # lockup_1 = await client_1.dao_send_to_lockup(dao_id_1, cat_amt)
        assert lockup_0["success"]
        # assert lockup_1["success"]

        for i in range(1, num_blocks):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(puzzle_hash_0))
            await asyncio.sleep(0.5)

        # create a spend proposal
        # TODO: Fix handling of comples spends
        additions = [
            {"puzzle_hash": ph_1.hex(), "amount": 1000},
        ]
        proposal = await client_0.dao_create_proposal(
            wallet_id=dao_id_0,
            proposal_type="spend",
            additions=additions,
            vote_amount=cat_amt,
            # inner_address=encode_puzzle_hash(ph_1, "xch"),
            fee=fee,
        )
        assert proposal["success"]
        for i in range(1, num_blocks):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(puzzle_hash_0))
            await asyncio.sleep(0.5)

        props = await client_0.dao_get_proposals(dao_id_0)
        proposal_id_hex = props["proposals"][0]["proposal_id"]

        # check proposal state and farm enough blocks to pass
        state = await client_0.dao_get_proposal_state(wallet_id=dao_id_0, proposal_id=proposal_id_hex)
        assert state["success"]
        assert state["state"]["passed"]

        for _ in range(0, state["state"]["blocks_needed"]):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(puzzle_hash_0))
            await asyncio.sleep(0.5)

        state = await client_0.dao_get_proposal_state(wallet_id=dao_id_0, proposal_id=proposal_id_hex)
        assert state["success"]
        assert state["state"]["closable"]

        # close the proposal
        close = await client_0.dao_close_proposal(wallet_id=dao_id_0, proposal_id=proposal_id_hex, fee=fee)
        assert close["success"]

        for i in range(1, num_blocks):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(puzzle_hash_0))
            await asyncio.sleep(0.5)

        # check proposal is closed
        await rpc_state(20, client_0.dao_get_proposals, [dao_id_0], lambda x: x["proposals"][0]["closed"], True)

        # free locked cats from finished proposal
        res = await client_0.dao_free_coins_from_finished_proposals(wallet_id=dao_id_0)
        assert res["success"]
        sb_name = bytes32.from_hexstr(res["spend_name"])
        await time_out_assert_not_none(5, full_node_api.full_node.mempool_manager.get_spendbundle, sb_name)

        for i in range(1, num_blocks):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(puzzle_hash_0))
            await asyncio.sleep(0.5)

        assert dao_cat_wallet_0.dao_cat_info.locked_coins[0].active_votes == []

        exit = await client_0.dao_exit_lockup(dao_id_0)
        assert exit["success"]
        for i in range(1, num_blocks):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(puzzle_hash_0))
            await asyncio.sleep(0.5)

        time_out_assert(20, dao_cat_wallet_0.get_confirmed_balance, 0)
        time_out_assert(20, cat_wallet_0.get_confirmed_balance, cat_amt)

    finally:
        client_0.close()
        client_1.close()
        await client_0.await_closed()
        await client_1.await_closed()
