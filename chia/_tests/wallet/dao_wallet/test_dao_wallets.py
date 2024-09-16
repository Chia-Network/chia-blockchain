from __future__ import annotations

import asyncio
import time
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

import pytest

from chia._tests.util.rpc import validate_get_routes
from chia._tests.util.setup_nodes import OldSimulatorsAndWallets, SimulatorsAndWalletsServices
from chia._tests.util.time_out_assert import time_out_assert, time_out_assert_not_none
from chia.consensus.block_rewards import calculate_base_farmer_reward, calculate_pool_reward
from chia.rpc.wallet_rpc_api import WalletRpcApi
from chia.rpc.wallet_rpc_client import WalletRpcClient
from chia.simulator.simulator_protocol import FarmNewBlockProtocol, ReorgProtocol
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.peer_info import PeerInfo
from chia.util.bech32m import encode_puzzle_hash
from chia.util.ints import uint32, uint64, uint128
from chia.util.timing import adjusted_timeout
from chia.wallet.cat_wallet.cat_wallet import CATWallet
from chia.wallet.cat_wallet.dao_cat_wallet import DAOCATWallet
from chia.wallet.dao_wallet.dao_info import DAORules
from chia.wallet.dao_wallet.dao_utils import (
    generate_mint_proposal_innerpuz,
    generate_simple_proposal_innerpuz,
    generate_update_proposal_innerpuz,
)
from chia.wallet.dao_wallet.dao_wallet import DAOWallet
from chia.wallet.transaction_record import TransactionRecord
from chia.wallet.util.tx_config import DEFAULT_TX_CONFIG


async def get_proposal_state(wallet: DAOWallet, index: int) -> Tuple[Optional[bool], Optional[bool]]:
    return wallet.dao_info.proposals_list[index].passed, wallet.dao_info.proposals_list[index].closed


async def rpc_state(
    timeout: float,
    async_function: Callable[[Any], Any],
    params: List[Union[int, Dict[str, Any]]],
    condition_func: Callable[[Dict[str, Any]], Any],
    result: Optional[Any] = None,
) -> Union[bool, Dict[str, Any]]:  # pragma: no cover
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


@pytest.mark.limit_consensus_modes(reason="does not depend on consensus rules")
@pytest.mark.parametrize(
    "trusted",
    [True, False],
)
@pytest.mark.anyio
async def test_dao_creation(self_hostname: str, two_wallet_nodes: OldSimulatorsAndWallets, trusted: bool) -> None:
    full_nodes, wallets, _ = two_wallet_nodes
    full_node_api = full_nodes[0]
    full_node_server = full_node_api.server
    wallet_node_0, server_0 = wallets[0]
    wallet_node_1, server_1 = wallets[1]
    wallet_0 = wallet_node_0.wallet_state_manager.main_wallet
    wallet_1 = wallet_node_1.wallet_state_manager.main_wallet
    ph = await wallet_0.get_new_puzzlehash()
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

    await server_0.start_client(PeerInfo(self_hostname, full_node_server.get_port()), None)
    await server_1.start_client(PeerInfo(self_hostname, full_node_server.get_port()), None)

    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))
    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph_1))

    funds = calculate_pool_reward(uint32(1)) + calculate_base_farmer_reward(uint32(1))

    await time_out_assert(20, wallet_0.get_confirmed_balance, funds)
    await time_out_assert(20, full_node_api.wallet_is_synced, True, wallet_node_0)

    cat_amt = 2000
    dao_rules = DAORules(
        proposal_timelock=uint64(10),
        soft_close_length=uint64(5),
        attendance_required=uint64(1000),  # 10%
        pass_percentage=uint64(5100),  # 51%
        self_destruct_length=uint64(20),
        oracle_spend_delay=uint64(10),
        proposal_minimum_amount=uint64(1),
    )

    fee = uint64(10)
    fee_for_cat = uint64(20)

    # Try to create a DAO with more CATs than xch balance
    with pytest.raises(ValueError) as e_info:
        async with wallet_0.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=False) as action_scope:
            await DAOWallet.create_new_dao_and_wallet(
                wallet_node_0.wallet_state_manager,
                wallet_0,
                uint64(funds + 1),
                dao_rules,
                action_scope,
                fee=fee,
                fee_for_cat=fee_for_cat,
            )
    assert e_info.value.args[0] == f"Your balance of {funds} mojos is not enough to create {funds + 1} CATs"

    async with wallet_0.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
        dao_wallet_0 = await DAOWallet.create_new_dao_and_wallet(
            wallet_node_0.wallet_state_manager,
            wallet_0,
            uint64(cat_amt * 2),
            dao_rules,
            action_scope,
            fee=fee,
            fee_for_cat=fee_for_cat,
        )

    await full_node_api.wait_transaction_records_entered_mempool(
        records=action_scope.side_effects.transactions, timeout=60
    )
    await full_node_api.process_all_wallet_transactions(wallet_0, timeout=60)
    await full_node_api.wait_for_wallets_synced(wallet_nodes=[wallet_node_0, wallet_node_1], timeout=30)

    # Check the spend was successful
    treasury_id = dao_wallet_0.dao_info.treasury_id

    # check the dao wallet balances
    await time_out_assert(20, dao_wallet_0.get_confirmed_balance, uint128(1))
    await time_out_assert(20, dao_wallet_0.get_unconfirmed_balance, uint128(1))
    await time_out_assert(20, dao_wallet_0.get_pending_change_balance, uint64(0))

    # check select coins
    async with wallet_0.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=False) as action_scope:
        no_coins = await dao_wallet_0.select_coins(uint64(2), action_scope)
        assert no_coins == set()
        selected_coins = await dao_wallet_0.select_coins(uint64(1), action_scope)
        assert len(selected_coins) == 1

    # get the cat wallets
    cat_wallet_0 = dao_wallet_0.wallet_state_manager.wallets[dao_wallet_0.dao_info.cat_wallet_id]
    dao_cat_wallet_0 = dao_wallet_0.wallet_state_manager.wallets[dao_wallet_0.dao_info.dao_cat_wallet_id]
    # Some dao_cat_wallet checks for coverage
    assert dao_cat_wallet_0.get_name() == f"CAT {cat_wallet_0.cat_info.limitations_program_hash.hex()[:16]}..."
    async with wallet_0.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=False) as action_scope:
        assert (await dao_cat_wallet_0.select_coins(uint64(1), action_scope)) == set()
    dao_cat_puzhash = await dao_cat_wallet_0.get_new_puzzlehash()
    assert dao_cat_puzhash == bytes32.from_hexstr("09f905ba3e9db3644ac4537495565bf268c6f030266aa412863c5efced6b1800")
    await dao_cat_wallet_0.get_new_inner_puzzle(DEFAULT_TX_CONFIG)
    dao_cat_inner_hash = await dao_cat_wallet_0.get_new_inner_hash(DEFAULT_TX_CONFIG)
    assert dao_cat_inner_hash == bytes32.from_hexstr("8a66292fde9ef08198d996eae0ea21677eb478afeabed8030b1bf42c728f7dcc")

    cat_wallet_0_bal = await cat_wallet_0.get_confirmed_balance()
    assert cat_wallet_0_bal == cat_amt * 2

    # Create the other user's wallet from the treasury id
    dao_wallet_1 = await DAOWallet.create_new_dao_wallet_for_existing_dao(
        wallet_node_1.wallet_state_manager, wallet_1, treasury_id
    )
    assert dao_wallet_0.dao_info.treasury_id == dao_wallet_1.dao_info.treasury_id

    # Get the cat wallets for wallet_1
    cat_wallet_1 = dao_wallet_1.wallet_state_manager.wallets[dao_wallet_1.dao_info.cat_wallet_id]
    assert cat_wallet_1

    # Send some cats to the dao_cat lockup
    dao_cat_amt = uint64(100)
    async with dao_wallet_0.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
        await dao_wallet_0.enter_dao_cat_voting_mode(dao_cat_amt, action_scope)

    await full_node_api.wait_transaction_records_entered_mempool(
        records=action_scope.side_effects.transactions, timeout=60
    )
    await full_node_api.process_all_wallet_transactions(wallet_0, timeout=60)
    await full_node_api.wait_for_wallet_synced(wallet_node=wallet_node_0, timeout=30)

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
    async with cat_wallet_0.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
        await cat_wallet_0.generate_signed_transaction([cat_amt], [ph_1], action_scope)

    await full_node_api.wait_transaction_records_entered_mempool(
        records=action_scope.side_effects.transactions, timeout=60
    )
    await full_node_api.process_all_wallet_transactions(wallet_0, timeout=60)
    await full_node_api.wait_for_wallet_synced(wallet_node=wallet_node_0, timeout=30)

    await time_out_assert(10, cat_wallet_1.get_confirmed_balance, cat_amt)

    # Smaller tests of dao_wallet funcs for coverage
    await dao_wallet_0.adjust_filter_level(uint64(10))
    assert dao_wallet_0.dao_info.filter_below_vote_amount == uint64(10)

    await dao_wallet_0.set_name("Renamed Wallet")
    assert dao_wallet_0.get_name() == "Renamed Wallet"

    new_inner_puzhash = await dao_wallet_0.get_new_p2_inner_hash()
    assert isinstance(new_inner_puzhash, bytes32)

    # run DAOCATwallet.create for coverage
    create_dao_cat_from_info = await DAOCATWallet.create(
        wallet_0.wallet_state_manager, wallet_0, dao_cat_wallet_0.wallet_info
    )
    assert create_dao_cat_from_info
    create_dao_wallet_from_info = await DAOWallet.create(
        wallet_0.wallet_state_manager, wallet_0, dao_wallet_0.wallet_info
    )
    assert create_dao_wallet_from_info


@pytest.mark.limit_consensus_modes(reason="does not depend on consensus rules")
@pytest.mark.parametrize(
    "trusted",
    [True, False],
)
@pytest.mark.anyio
async def test_dao_funding(self_hostname: str, three_wallet_nodes: OldSimulatorsAndWallets, trusted: bool) -> None:
    full_nodes, wallets, _ = three_wallet_nodes
    full_node_api = full_nodes[0]
    full_node_server = full_node_api.server
    wallet_node_0, server_0 = wallets[0]
    wallet_node_1, server_1 = wallets[1]
    wallet_node_2, server_2 = wallets[2]
    wallet_0 = wallet_node_0.wallet_state_manager.main_wallet
    wallet_1 = wallet_node_1.wallet_state_manager.main_wallet
    wallet_2 = wallet_node_1.wallet_state_manager.main_wallet
    ph = await wallet_0.get_new_puzzlehash()
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

    await server_0.start_client(PeerInfo(self_hostname, full_node_server.get_port()), None)
    await server_1.start_client(PeerInfo(self_hostname, full_node_server.get_port()), None)
    await server_2.start_client(PeerInfo(self_hostname, full_node_server.get_port()), None)

    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))
    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph_1))
    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph_2))
    await full_node_api.wait_for_wallet_synced(wallet_node=wallet_node_0, timeout=30)

    funds = calculate_pool_reward(uint32(1)) + calculate_base_farmer_reward(uint32(1))

    await time_out_assert(20, wallet_0.get_confirmed_balance, funds)
    await time_out_assert(20, full_node_api.wallet_is_synced, True, wallet_node_0)

    cat_amt = 300000
    dao_rules = DAORules(
        proposal_timelock=uint64(5),
        soft_close_length=uint64(5),
        attendance_required=uint64(1000),  # 10%
        pass_percentage=uint64(5100),  # 51%
        self_destruct_length=uint64(20),
        oracle_spend_delay=uint64(10),
        proposal_minimum_amount=uint64(1),
    )

    async with wallet_0.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
        dao_wallet_0 = await DAOWallet.create_new_dao_and_wallet(
            wallet_node_0.wallet_state_manager, wallet_0, uint64(cat_amt), dao_rules, action_scope
        )

    treasury_id = dao_wallet_0.dao_info.treasury_id

    # Get the full node sim to process the wallet creation spend
    await full_node_api.wait_transaction_records_entered_mempool(
        records=action_scope.side_effects.transactions, timeout=60
    )
    await full_node_api.process_all_wallet_transactions(wallet_0, timeout=60)
    await full_node_api.wait_for_wallets_synced(wallet_nodes=[wallet_node_0, wallet_node_1], timeout=30)

    # get the cat wallets
    cat_wallet_0 = dao_wallet_0.wallet_state_manager.wallets[dao_wallet_0.dao_info.cat_wallet_id]
    await time_out_assert(20, cat_wallet_0.get_confirmed_balance, cat_amt)

    # Create funding spends for xch and cat
    xch_funds = uint64(500000)
    cat_funds = uint64(100000)
    async with dao_wallet_0.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
        await dao_wallet_0.create_add_funds_to_treasury_spend(xch_funds, action_scope)
    await full_node_api.wait_transaction_records_entered_mempool(
        records=action_scope.side_effects.transactions, timeout=60
    )
    await full_node_api.process_all_wallet_transactions(wallet_0, timeout=60)
    await full_node_api.wait_for_wallet_synced(wallet_node=wallet_node_0, timeout=30)

    # Check that the funding spend is found
    await time_out_assert(20, dao_wallet_0.get_balance_by_asset_type, xch_funds)

    async with dao_wallet_0.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
        await dao_wallet_0.create_add_funds_to_treasury_spend(
            cat_funds, action_scope, funding_wallet_id=cat_wallet_0.id()
        )
    await full_node_api.wait_transaction_records_entered_mempool(
        records=action_scope.side_effects.transactions, timeout=60
    )
    await full_node_api.process_all_wallet_transactions(wallet_0, timeout=60)
    await full_node_api.wait_for_wallet_synced(wallet_node=wallet_node_0, timeout=30)

    await time_out_assert(20, cat_wallet_0.get_confirmed_balance, cat_amt - cat_funds)

    # Check that the funding spend is found
    cat_id = bytes32.from_hexstr(cat_wallet_0.get_asset_id())
    await time_out_assert(20, dao_wallet_0.get_balance_by_asset_type, cat_funds, cat_id)

    # Create and close a proposal
    cat_wallet_0 = dao_wallet_0.wallet_state_manager.wallets[dao_wallet_0.dao_info.cat_wallet_id]
    dao_cat_wallet_0 = dao_wallet_0.wallet_state_manager.wallets[dao_wallet_0.dao_info.dao_cat_wallet_id]
    dao_cat_0_bal = await dao_cat_wallet_0.get_votable_balance()
    async with dao_cat_wallet_0.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
        await dao_cat_wallet_0.enter_dao_cat_voting_mode(dao_cat_0_bal, action_scope)
    await full_node_api.wait_transaction_records_entered_mempool(
        records=action_scope.side_effects.transactions, timeout=60
    )
    await full_node_api.process_all_wallet_transactions(wallet_0, timeout=60)
    await full_node_api.wait_for_wallets_synced(wallet_nodes=[wallet_node_0, wallet_node_1, wallet_node_2], timeout=30)

    recipient_puzzle_hash = await wallet_2.get_new_puzzlehash()
    proposal_amount_1 = uint64(10000)
    xch_proposal_inner = generate_simple_proposal_innerpuz(
        treasury_id,
        [recipient_puzzle_hash],
        [proposal_amount_1],
        [None],
    )
    async with dao_wallet_0.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
        await dao_wallet_0.generate_new_proposal(xch_proposal_inner, action_scope, dao_cat_0_bal)
    await full_node_api.wait_transaction_records_entered_mempool(
        records=action_scope.side_effects.transactions, timeout=60
    )
    await full_node_api.process_all_wallet_transactions(wallet_0, timeout=60)
    await full_node_api.wait_for_wallets_synced(wallet_nodes=[wallet_node_0, wallet_node_1], timeout=30)

    # farm blocks to pass proposal
    for _ in range(5):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(puzzle_hash_0))

    prop_0 = dao_wallet_0.dao_info.proposals_list[0]
    async with dao_wallet_0.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
        await dao_wallet_0.create_proposal_close_spend(prop_0.proposal_id, action_scope)
    await full_node_api.wait_transaction_records_entered_mempool(
        records=action_scope.side_effects.transactions, timeout=60
    )
    await full_node_api.process_all_wallet_transactions(wallet_0, timeout=60)
    await full_node_api.wait_for_wallets_synced(wallet_nodes=[wallet_node_0, wallet_node_1], timeout=30)

    # Create the other user's wallet from the treasury id
    dao_wallet_1 = await DAOWallet.create_new_dao_wallet_for_existing_dao(
        wallet_node_1.wallet_state_manager, wallet_1, treasury_id
    )
    assert dao_wallet_1.dao_info.treasury_id == dao_wallet_1.dao_info.treasury_id

    # Get the cat wallets for wallet_1
    cat_wallet_1 = dao_wallet_1.wallet_state_manager.wallets[dao_wallet_1.dao_info.cat_wallet_id]
    assert cat_wallet_1
    assert cat_wallet_1.cat_info.limitations_program_hash == cat_id

    await time_out_assert(30, dao_wallet_0.get_balance_by_asset_type, xch_funds - 10000)
    await time_out_assert(30, dao_wallet_0.get_balance_by_asset_type, cat_funds, cat_id)
    await time_out_assert(30, dao_wallet_1.get_balance_by_asset_type, xch_funds - 10000)
    await time_out_assert(30, dao_wallet_1.get_balance_by_asset_type, cat_funds, cat_id)


@pytest.mark.limit_consensus_modes(reason="does not depend on consensus rules")
@pytest.mark.parametrize(
    "trusted",
    [True, False],
)
@pytest.mark.anyio
async def test_dao_proposals(self_hostname: str, three_wallet_nodes: OldSimulatorsAndWallets, trusted: bool) -> None:
    """
    Test a set of proposals covering:
    - the spend, update, and mint types.
    - passing and failing
    - force closing broken proposals

    total cats issued: 300k
    each wallet holds: 100k

    The proposal types and amounts voted are:
    P0 Spend => Pass
    P1 Mint => Pass
    P2 Update => Pass
    P3 Spend => Fail
    P4 Bad Spend => Force Close

    """
    full_nodes, wallets, _ = three_wallet_nodes
    full_node_api = full_nodes[0]
    full_node_server = full_node_api.server
    wallet_node_0, server_0 = wallets[0]
    wallet_node_1, server_1 = wallets[1]
    wallet_node_2, server_2 = wallets[2]
    wallet_0 = wallet_node_0.wallet_state_manager.main_wallet
    wallet_1 = wallet_node_1.wallet_state_manager.main_wallet
    wallet_2 = wallet_node_2.wallet_state_manager.main_wallet
    ph_0 = await wallet_0.get_new_puzzlehash()
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

    await server_0.start_client(PeerInfo(self_hostname, full_node_server.get_port()), None)
    await server_1.start_client(PeerInfo(self_hostname, full_node_server.get_port()), None)
    await server_2.start_client(PeerInfo(self_hostname, full_node_server.get_port()), None)

    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph_0))
    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph_1))
    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph_2))

    funds = calculate_pool_reward(uint32(1)) + calculate_base_farmer_reward(uint32(1))

    await time_out_assert(20, wallet_0.get_confirmed_balance, funds)
    await time_out_assert(20, full_node_api.wallet_is_synced, True, wallet_node_0)

    # set a standard fee amount to use in all txns
    base_fee = uint64(100)

    # set the cat issuance and DAO rules
    cat_issuance = 300000
    proposal_min_amt = uint64(101)
    dao_rules = DAORules(
        proposal_timelock=uint64(10),
        soft_close_length=uint64(5),
        attendance_required=uint64(190000),
        pass_percentage=uint64(5100),  # 51%
        self_destruct_length=uint64(20),
        oracle_spend_delay=uint64(10),
        proposal_minimum_amount=proposal_min_amt,
    )

    # Create the DAO.
    # This takes two steps: create the treasury singleton, wait for oracle_spend_delay and
    # then complete the eve spend
    async with wallet_0.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
        dao_wallet_0 = await DAOWallet.create_new_dao_and_wallet(
            wallet_node_0.wallet_state_manager,
            wallet_0,
            uint64(cat_issuance),
            dao_rules,
            action_scope,
        )

    await full_node_api.wait_transaction_records_entered_mempool(
        records=action_scope.side_effects.transactions, timeout=60
    )
    await full_node_api.process_all_wallet_transactions(wallet_0, timeout=60)
    await full_node_api.wait_for_wallets_synced(wallet_nodes=[wallet_node_0, wallet_node_1], timeout=30)

    cat_wallet_0 = dao_wallet_0.wallet_state_manager.wallets[dao_wallet_0.dao_info.cat_wallet_id]
    dao_cat_wallet_0 = dao_wallet_0.wallet_state_manager.wallets[dao_wallet_0.dao_info.dao_cat_wallet_id]
    await time_out_assert(10, cat_wallet_0.get_confirmed_balance, cat_issuance)
    assert dao_cat_wallet_0

    treasury_id = dao_wallet_0.dao_info.treasury_id

    # Create dao_wallet_1 from the treasury id
    dao_wallet_1 = await DAOWallet.create_new_dao_wallet_for_existing_dao(
        wallet_node_1.wallet_state_manager, wallet_1, treasury_id
    )
    assert dao_wallet_1.dao_info.treasury_id == treasury_id
    cat_wallet_1 = dao_wallet_1.wallet_state_manager.wallets[dao_wallet_1.dao_info.cat_wallet_id]
    dao_cat_wallet_1 = dao_wallet_1.wallet_state_manager.wallets[dao_wallet_1.dao_info.dao_cat_wallet_id]
    assert cat_wallet_1
    assert dao_cat_wallet_1

    # Create dao_wallet_2 from the treasury id
    dao_wallet_2 = await DAOWallet.create_new_dao_wallet_for_existing_dao(
        wallet_node_2.wallet_state_manager, wallet_2, treasury_id
    )
    assert dao_wallet_2.dao_info.treasury_id == treasury_id
    cat_wallet_2 = dao_wallet_2.wallet_state_manager.wallets[dao_wallet_2.dao_info.cat_wallet_id]
    dao_cat_wallet_2 = dao_wallet_2.wallet_state_manager.wallets[dao_wallet_2.dao_info.dao_cat_wallet_id]
    assert cat_wallet_2
    assert dao_cat_wallet_2

    # Send 100k cats to wallet_1 and wallet_2
    cat_amt = uint64(100000)
    async with cat_wallet_0.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
        await cat_wallet_0.generate_signed_transaction([cat_amt, cat_amt], [ph_1, ph_2], action_scope, fee=base_fee)
    await full_node_api.wait_transaction_records_entered_mempool(
        records=action_scope.side_effects.transactions, timeout=60
    )
    await full_node_api.process_all_wallet_transactions(wallet_0, timeout=60)
    await full_node_api.wait_for_wallet_synced(wallet_node=wallet_node_0, timeout=30)

    # Lockup voting cats for all wallets
    dao_cat_0_bal = await dao_cat_wallet_0.get_votable_balance()
    async with dao_cat_wallet_0.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
        await dao_cat_wallet_0.enter_dao_cat_voting_mode(dao_cat_0_bal, action_scope, fee=base_fee)
    await full_node_api.wait_transaction_records_entered_mempool(
        records=action_scope.side_effects.transactions, timeout=60
    )
    await full_node_api.process_all_wallet_transactions(wallet_0, timeout=60)
    await full_node_api.wait_for_wallet_synced(wallet_node=wallet_node_0, timeout=30)

    dao_cat_1_bal = await dao_cat_wallet_1.get_votable_balance()
    async with dao_cat_wallet_1.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
        await dao_cat_wallet_1.enter_dao_cat_voting_mode(dao_cat_1_bal, action_scope)
    await full_node_api.wait_transaction_records_entered_mempool(
        records=action_scope.side_effects.transactions, timeout=60
    )
    await full_node_api.process_all_wallet_transactions(wallet_1, timeout=60)
    await full_node_api.wait_for_wallets_synced(wallet_nodes=[wallet_node_0, wallet_node_1, wallet_node_2], timeout=30)

    dao_cat_2_bal = await dao_cat_wallet_2.get_votable_balance()
    async with dao_cat_wallet_2.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
        await dao_cat_wallet_2.enter_dao_cat_voting_mode(dao_cat_2_bal, action_scope)
    await full_node_api.wait_transaction_records_entered_mempool(
        records=action_scope.side_effects.transactions, timeout=60
    )
    await full_node_api.process_all_wallet_transactions(wallet_2, timeout=60)
    await full_node_api.wait_for_wallets_synced(wallet_nodes=[wallet_node_0, wallet_node_1, wallet_node_2], timeout=30)

    await time_out_assert(10, dao_cat_wallet_0.get_confirmed_balance, cat_amt)
    await time_out_assert(10, dao_cat_wallet_1.get_confirmed_balance, cat_amt)
    await time_out_assert(10, dao_cat_wallet_2.get_confirmed_balance, cat_amt)

    # Create funding spend so the treasury holds some XCH
    xch_funds = uint64(500000)
    async with dao_wallet_0.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
        await dao_wallet_0.create_add_funds_to_treasury_spend(xch_funds, action_scope)
    await full_node_api.wait_transaction_records_entered_mempool(
        records=action_scope.side_effects.transactions, timeout=60
    )
    await full_node_api.process_all_wallet_transactions(wallet_1, timeout=60)
    await full_node_api.wait_for_wallets_synced(wallet_nodes=[wallet_node_0, wallet_node_1, wallet_node_2], timeout=30)

    # Check that the funding spend is recognized by all wallets
    await time_out_assert(10, dao_wallet_0.get_balance_by_asset_type, xch_funds)
    await time_out_assert(10, dao_wallet_1.get_balance_by_asset_type, xch_funds)
    await time_out_assert(10, dao_wallet_2.get_balance_by_asset_type, xch_funds)

    # Create Proposals

    # Proposal 0: Spend xch to wallet_2.
    recipient_puzzle_hash = await wallet_2.get_new_puzzlehash()
    proposal_amount_1 = uint64(9998)
    xch_proposal_inner = generate_simple_proposal_innerpuz(
        treasury_id,
        [recipient_puzzle_hash],
        [proposal_amount_1],
        [None],
    )
    async with dao_wallet_0.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
        await dao_wallet_0.generate_new_proposal(xch_proposal_inner, action_scope, dao_cat_0_bal, fee=base_fee)
    await full_node_api.wait_transaction_records_entered_mempool(
        records=action_scope.side_effects.transactions, timeout=60
    )
    await full_node_api.process_all_wallet_transactions(wallet_0, timeout=60)
    await full_node_api.wait_for_wallets_synced(wallet_nodes=[wallet_node_0, wallet_node_1, wallet_node_2], timeout=30)

    assert len(dao_wallet_0.dao_info.proposals_list) == 1
    assert dao_wallet_0.dao_info.proposals_list[0].amount_voted == dao_cat_0_bal
    assert dao_wallet_0.dao_info.proposals_list[0].timer_coin is not None
    prop_0 = dao_wallet_0.dao_info.proposals_list[0]

    # Proposal 1: Mint new CATs
    new_mint_amount = uint64(1000)
    mint_proposal_inner = await generate_mint_proposal_innerpuz(
        treasury_id,
        cat_wallet_0.cat_info.limitations_program_hash,
        new_mint_amount,
        recipient_puzzle_hash,
    )

    async with dao_wallet_0.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
        await dao_wallet_0.generate_new_proposal(
            mint_proposal_inner, action_scope, vote_amount=dao_cat_0_bal, fee=base_fee
        )
    await full_node_api.wait_transaction_records_entered_mempool(
        records=action_scope.side_effects.transactions, timeout=60
    )
    await full_node_api.process_all_wallet_transactions(wallet_0, timeout=60)
    await full_node_api.wait_for_wallets_synced(wallet_nodes=[wallet_node_0, wallet_node_1, wallet_node_2], timeout=30)

    assert len(dao_wallet_0.dao_info.proposals_list) == 2
    prop_1 = dao_wallet_0.dao_info.proposals_list[1]

    # Proposal 2: Update DAO Rules.
    new_dao_rules = DAORules(
        proposal_timelock=uint64(8),
        soft_close_length=uint64(4),
        attendance_required=uint64(150000),
        pass_percentage=uint64(7500),
        self_destruct_length=uint64(12),
        oracle_spend_delay=uint64(5),
        proposal_minimum_amount=uint64(1),
    )
    current_innerpuz = dao_wallet_0.dao_info.current_treasury_innerpuz
    assert current_innerpuz is not None
    update_inner = await generate_update_proposal_innerpuz(current_innerpuz, new_dao_rules)
    async with dao_wallet_0.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
        await dao_wallet_0.generate_new_proposal(update_inner, action_scope, dao_cat_0_bal, fee=base_fee)
    await full_node_api.wait_transaction_records_entered_mempool(
        records=action_scope.side_effects.transactions, timeout=60
    )
    await full_node_api.process_all_wallet_transactions(wallet_0, timeout=60)
    await full_node_api.wait_for_wallets_synced(wallet_nodes=[wallet_node_0, wallet_node_1, wallet_node_2], timeout=30)

    assert len(dao_wallet_0.dao_info.proposals_list) == 3
    prop_2 = dao_wallet_0.dao_info.proposals_list[2]

    # Proposal 3: Spend xch to wallet_2 (this prop will close as failed)
    proposal_amount_2 = uint64(500)
    xch_proposal_inner = generate_simple_proposal_innerpuz(
        treasury_id, [recipient_puzzle_hash], [proposal_amount_2], [None]
    )
    async with dao_wallet_0.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
        await dao_wallet_0.generate_new_proposal(xch_proposal_inner, action_scope, dao_cat_0_bal, fee=base_fee)
    await full_node_api.wait_transaction_records_entered_mempool(
        records=action_scope.side_effects.transactions, timeout=60
    )
    await full_node_api.process_all_wallet_transactions(wallet_0, timeout=60)
    await full_node_api.wait_for_wallets_synced(wallet_nodes=[wallet_node_0, wallet_node_1, wallet_node_2], timeout=30)

    assert len(dao_wallet_0.dao_info.proposals_list) == 4
    prop_3 = dao_wallet_0.dao_info.proposals_list[3]

    # Proposal 4: Create a 'bad' proposal (can't be executed, must be force-closed)
    xch_proposal_inner = Program.to(["x"])
    async with dao_wallet_0.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
        await dao_wallet_0.generate_new_proposal(xch_proposal_inner, action_scope, dao_cat_0_bal, fee=base_fee)
    await full_node_api.wait_transaction_records_entered_mempool(
        records=action_scope.side_effects.transactions, timeout=60
    )
    await full_node_api.process_all_wallet_transactions(wallet_0, timeout=60)
    await full_node_api.wait_for_wallets_synced(wallet_nodes=[wallet_node_0, wallet_node_1, wallet_node_2], timeout=30)

    assert len(dao_wallet_0.dao_info.proposals_list) == 5
    assert len(dao_wallet_1.dao_info.proposals_list) == 5
    assert len(dao_wallet_1.dao_info.proposals_list) == 5
    prop_4 = dao_wallet_0.dao_info.proposals_list[4]

    # Proposal 0 Voting: wallet 1 votes yes, wallet 2 votes no. Proposal Passes
    async with dao_wallet_1.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
        await dao_wallet_1.generate_proposal_vote_spend(prop_0.proposal_id, dao_cat_1_bal, True, action_scope)
    await full_node_api.wait_transaction_records_entered_mempool(
        records=action_scope.side_effects.transactions, timeout=60
    )
    await full_node_api.process_all_wallet_transactions(wallet_1, timeout=60)
    await full_node_api.wait_for_wallets_synced(wallet_nodes=[wallet_node_0, wallet_node_1, wallet_node_2], timeout=30)

    async with dao_wallet_2.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
        await dao_wallet_2.generate_proposal_vote_spend(prop_0.proposal_id, dao_cat_2_bal, False, action_scope)
    await full_node_api.wait_transaction_records_entered_mempool(
        records=action_scope.side_effects.transactions, timeout=60
    )
    await full_node_api.process_all_wallet_transactions(wallet_1, timeout=60)
    await full_node_api.wait_for_wallets_synced(wallet_nodes=[wallet_node_0, wallet_node_1, wallet_node_2], timeout=30)

    total_votes = dao_cat_0_bal + dao_cat_1_bal + dao_cat_2_bal
    assert dao_wallet_0.dao_info.proposals_list[0].amount_voted == total_votes
    assert dao_wallet_0.dao_info.proposals_list[0].yes_votes == total_votes - dao_cat_2_bal
    assert dao_wallet_1.dao_info.proposals_list[0].amount_voted == total_votes
    assert dao_wallet_1.dao_info.proposals_list[0].yes_votes == total_votes - dao_cat_2_bal
    assert dao_wallet_2.dao_info.proposals_list[0].amount_voted == total_votes
    assert dao_wallet_2.dao_info.proposals_list[0].yes_votes == total_votes - dao_cat_2_bal

    prop_0_state = await dao_wallet_0.get_proposal_state(prop_0.proposal_id)
    assert prop_0_state["passed"]
    assert prop_0_state["closable"]

    # Proposal 0 is closable, but soft_close_length has not passed.
    async with dao_wallet_0.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
        await dao_wallet_0.create_proposal_close_spend(prop_0.proposal_id, action_scope)
    with pytest.raises(AssertionError, match="Timed assertion timed out"):
        assert action_scope.side_effects.transactions[0].spend_bundle is not None
        await time_out_assert_not_none(
            5,
            full_node_api.full_node.mempool_manager.get_spendbundle,
            action_scope.side_effects.transactions[0].spend_bundle.name(),
        )

    for _ in range(5):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(puzzle_hash_0))
    await full_node_api.wait_for_wallets_synced(wallet_nodes=[wallet_node_0, wallet_node_1, wallet_node_2], timeout=30)

    # Proposal 0: Close
    async with dao_wallet_0.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
        await dao_wallet_0.create_proposal_close_spend(prop_0.proposal_id, action_scope)
    close_sb_0 = action_scope.side_effects.transactions[0].spend_bundle
    assert close_sb_0 is not None
    await time_out_assert_not_none(5, full_node_api.full_node.mempool_manager.get_spendbundle, close_sb_0.name())
    await full_node_api.process_spend_bundles(bundles=[close_sb_0])
    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(puzzle_hash_0))
    await full_node_api.wait_for_wallets_synced(wallet_nodes=[wallet_node_0, wallet_node_1, wallet_node_2], timeout=30)
    await time_out_assert(20, wallet_2.get_confirmed_balance, funds + proposal_amount_1)
    await time_out_assert(
        20, dao_wallet_0.get_balance_by_asset_type, xch_funds - proposal_amount_1 + proposal_min_amt - 1
    )

    await time_out_assert(20, get_proposal_state, (True, True), *[dao_wallet_0, 0])
    await time_out_assert(20, get_proposal_state, (True, True), *[dao_wallet_1, 0])
    await time_out_assert(20, get_proposal_state, (True, True), *[dao_wallet_2, 0])

    # Proposal 1 vote and close
    async with dao_wallet_1.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
        await dao_wallet_1.generate_proposal_vote_spend(prop_1.proposal_id, dao_cat_1_bal, True, action_scope)
    await full_node_api.wait_transaction_records_entered_mempool(
        records=action_scope.side_effects.transactions, timeout=60
    )
    await full_node_api.process_all_wallet_transactions(wallet_1, timeout=60)
    await full_node_api.wait_for_wallets_synced(wallet_nodes=[wallet_node_0, wallet_node_1, wallet_node_2], timeout=30)

    for _ in range(10):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(puzzle_hash_0))
    await full_node_api.wait_for_wallets_synced(wallet_nodes=[wallet_node_0, wallet_node_1, wallet_node_2], timeout=30)

    prop_1_state = await dao_wallet_0.get_proposal_state(prop_1.proposal_id)
    assert prop_1_state["passed"]
    assert prop_1_state["closable"]

    async with dao_wallet_0.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
        await dao_wallet_0.create_proposal_close_spend(prop_1.proposal_id, action_scope)
    await full_node_api.wait_transaction_records_entered_mempool(
        records=action_scope.side_effects.transactions, timeout=60
    )
    await full_node_api.process_all_wallet_transactions(wallet_0, timeout=60)
    await full_node_api.wait_for_wallets_synced(wallet_nodes=[wallet_node_0, wallet_node_1, wallet_node_2], timeout=30)

    await time_out_assert(20, cat_wallet_2.get_confirmed_balance, new_mint_amount)

    # Proposal 2 vote and close
    async with dao_wallet_1.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
        await dao_wallet_1.generate_proposal_vote_spend(prop_2.proposal_id, dao_cat_1_bal, True, action_scope)
    await full_node_api.wait_transaction_records_entered_mempool(
        records=action_scope.side_effects.transactions, timeout=60
    )
    await full_node_api.process_all_wallet_transactions(wallet_1, timeout=60)
    await full_node_api.wait_for_wallets_synced(wallet_nodes=[wallet_node_0, wallet_node_1, wallet_node_2], timeout=30)

    for _ in range(10):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(puzzle_hash_0))
    await full_node_api.wait_for_wallets_synced(wallet_nodes=[wallet_node_0, wallet_node_1, wallet_node_2], timeout=30)

    prop_2_state = await dao_wallet_0.get_proposal_state(prop_2.proposal_id)
    assert prop_2_state["passed"]
    assert prop_2_state["closable"]

    async with dao_wallet_0.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
        await dao_wallet_0.create_proposal_close_spend(prop_2.proposal_id, action_scope)
    await full_node_api.wait_transaction_records_entered_mempool(
        records=action_scope.side_effects.transactions, timeout=60
    )
    await full_node_api.process_all_wallet_transactions(wallet_0, timeout=60)
    await full_node_api.wait_for_wallets_synced(wallet_nodes=[wallet_node_0, wallet_node_1, wallet_node_2], timeout=30)

    assert dao_wallet_0.dao_rules == new_dao_rules
    assert dao_wallet_1.dao_rules == new_dao_rules
    assert dao_wallet_2.dao_rules == new_dao_rules

    # Proposal 3 - Close as FAILED
    async with dao_wallet_1.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
        await dao_wallet_1.generate_proposal_vote_spend(prop_3.proposal_id, dao_cat_1_bal, False, action_scope)
    await full_node_api.wait_transaction_records_entered_mempool(
        records=action_scope.side_effects.transactions, timeout=60
    )
    await full_node_api.process_all_wallet_transactions(wallet_1, timeout=60)
    await full_node_api.wait_for_wallets_synced(wallet_nodes=[wallet_node_0, wallet_node_1, wallet_node_2], timeout=30)

    for _ in range(10):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(puzzle_hash_0))
    await full_node_api.wait_for_wallets_synced(wallet_nodes=[wallet_node_0, wallet_node_1, wallet_node_2], timeout=30)

    prop_3_state = await dao_wallet_1.get_proposal_state(prop_3.proposal_id)
    assert not prop_3_state["passed"]
    assert prop_3_state["closable"]

    async with dao_wallet_0.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
        await dao_wallet_0.create_proposal_close_spend(prop_3.proposal_id, action_scope)
    await full_node_api.wait_transaction_records_entered_mempool(
        records=action_scope.side_effects.transactions, timeout=60
    )
    await full_node_api.process_all_wallet_transactions(wallet_0, timeout=60)
    await full_node_api.wait_for_wallets_synced(wallet_nodes=[wallet_node_0, wallet_node_1, wallet_node_2], timeout=30)

    await time_out_assert(20, wallet_2.get_confirmed_balance, funds + proposal_amount_1)
    expected_balance = xch_funds - proposal_amount_1 + (3 * proposal_min_amt) - 3 - new_mint_amount
    await time_out_assert(20, dao_wallet_0.get_balance_by_asset_type, expected_balance)

    await time_out_assert(20, get_proposal_state, (False, True), *[dao_wallet_0, 3])
    await time_out_assert(20, get_proposal_state, (False, True), *[dao_wallet_1, 3])
    await time_out_assert(20, get_proposal_state, (False, True), *[dao_wallet_2, 3])

    # Proposal 4 - Self Destruct a broken proposal
    async with dao_wallet_1.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
        await dao_wallet_1.generate_proposal_vote_spend(prop_4.proposal_id, dao_cat_1_bal, True, action_scope)
    await full_node_api.wait_transaction_records_entered_mempool(
        records=action_scope.side_effects.transactions, timeout=60
    )
    await full_node_api.process_all_wallet_transactions(wallet_1, timeout=60)
    await full_node_api.wait_for_wallets_synced(wallet_nodes=[wallet_node_0, wallet_node_1, wallet_node_2], timeout=30)

    for _ in range(10):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(puzzle_hash_0))
    await full_node_api.wait_for_wallets_synced(wallet_nodes=[wallet_node_0, wallet_node_1, wallet_node_2], timeout=30)

    prop_4_state = await dao_wallet_1.get_proposal_state(prop_4.proposal_id)
    assert prop_4_state["passed"]
    assert prop_4_state["closable"]

    with pytest.raises(Exception, match="Unrecognised proposal type"):
        async with dao_wallet_0.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
            await dao_wallet_0.create_proposal_close_spend(prop_4.proposal_id, action_scope)

    async with dao_wallet_0.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
        await dao_wallet_0.create_proposal_close_spend(prop_4.proposal_id, action_scope, self_destruct=True)
    await full_node_api.wait_transaction_records_entered_mempool(
        records=action_scope.side_effects.transactions, timeout=60
    )
    await full_node_api.process_all_wallet_transactions(wallet_0, timeout=60)
    await full_node_api.wait_for_wallets_synced(wallet_nodes=[wallet_node_0, wallet_node_1, wallet_node_2], timeout=30)

    # expected balance is unchanged because broken props can't release their amount
    await time_out_assert(20, dao_wallet_0.get_balance_by_asset_type, expected_balance)
    await time_out_assert(20, get_proposal_state, (True, True), *[dao_wallet_0, 4])
    await time_out_assert(20, get_proposal_state, (True, True), *[dao_wallet_1, 4])
    await time_out_assert(20, get_proposal_state, (True, True), *[dao_wallet_2, 4])

    # Remove Proposals from Memory and Free up locked coins
    await time_out_assert(20, len, 5, dao_wallet_0.dao_info.proposals_list)
    await dao_wallet_0.clear_finished_proposals_from_memory()
    async with dao_wallet_0.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
        await dao_wallet_0.free_coins_from_finished_proposals(action_scope, fee=uint64(100))
    await full_node_api.wait_transaction_records_entered_mempool(
        records=action_scope.side_effects.transactions, timeout=60
    )
    await full_node_api.process_all_wallet_transactions(wallet_0, timeout=60)
    await full_node_api.wait_for_wallets_synced(wallet_nodes=[wallet_node_0, wallet_node_1, wallet_node_2], timeout=30)

    await dao_wallet_0.clear_finished_proposals_from_memory()
    await time_out_assert(20, len, 0, dao_wallet_0.dao_info.proposals_list)


@pytest.mark.limit_consensus_modes(reason="does not depend on consensus rules")
@pytest.mark.parametrize(
    "trusted",
    [True, False],
)
@pytest.mark.anyio
async def test_dao_proposal_partial_vote(
    self_hostname: str, two_wallet_nodes: OldSimulatorsAndWallets, trusted: bool
) -> None:
    full_nodes, wallets, _ = two_wallet_nodes
    full_node_api = full_nodes[0]
    full_node_server = full_node_api.server
    wallet_node_0, server_0 = wallets[0]
    wallet_node_1, server_1 = wallets[1]
    wallet_0 = wallet_node_0.wallet_state_manager.main_wallet
    wallet_1 = wallet_node_1.wallet_state_manager.main_wallet
    ph = await wallet_0.get_new_puzzlehash()
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

    await server_0.start_client(PeerInfo(self_hostname, full_node_server.get_port()), None)
    await server_1.start_client(PeerInfo(self_hostname, full_node_server.get_port()), None)

    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))
    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph_1))
    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(puzzle_hash_0))

    funds = calculate_pool_reward(uint32(1)) + calculate_base_farmer_reward(uint32(1))

    await time_out_assert(20, wallet_0.get_confirmed_balance, funds)
    await time_out_assert(20, full_node_api.wallet_is_synced, True, wallet_node_0)

    cat_amt = 300000
    dao_rules = DAORules(
        proposal_timelock=uint64(10),
        soft_close_length=uint64(5),
        attendance_required=uint64(1000),  # 10%
        pass_percentage=uint64(5100),  # 51%
        self_destruct_length=uint64(20),
        oracle_spend_delay=uint64(10),
        proposal_minimum_amount=uint64(1),
    )

    async with wallet_0.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
        dao_wallet_0 = await DAOWallet.create_new_dao_and_wallet(
            wallet_node_0.wallet_state_manager, wallet_0, uint64(cat_amt), dao_rules, action_scope
        )

    # Get the full node sim to process the wallet creation spend
    await full_node_api.wait_transaction_records_entered_mempool(
        records=action_scope.side_effects.transactions, timeout=60
    )
    await full_node_api.process_all_wallet_transactions(wallet_0, timeout=60)
    await full_node_api.wait_for_wallets_synced(wallet_nodes=[wallet_node_0, wallet_node_1], timeout=30)

    # get the cat wallets
    cat_wallet_0 = dao_wallet_0.wallet_state_manager.wallets[dao_wallet_0.dao_info.cat_wallet_id]
    await time_out_assert(10, cat_wallet_0.get_confirmed_balance, cat_amt)

    # get the dao_cat wallet
    dao_cat_wallet_0 = dao_wallet_0.wallet_state_manager.wallets[dao_wallet_0.dao_info.dao_cat_wallet_id]

    treasury_id = dao_wallet_0.dao_info.treasury_id

    # make sure the next wallet node can find the treasury
    assert dao_wallet_0.dao_info.current_treasury_coin is not None
    treasury_parent = dao_wallet_0.dao_info.current_treasury_coin.parent_coin_info
    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(puzzle_hash_0))
    await time_out_assert_not_none(
        60, wallet_node_1.fetch_children, treasury_parent, wallet_node_1.get_full_node_peer()
    )
    # Create the other user's wallet from the treasury id
    dao_wallet_1 = await DAOWallet.create_new_dao_wallet_for_existing_dao(
        wallet_node_1.wallet_state_manager, wallet_1, treasury_id
    )
    assert dao_wallet_1.dao_info.treasury_id == treasury_id

    # Create funding spends for xch
    xch_funds = uint64(500000)
    async with dao_wallet_0.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
        await dao_wallet_0.create_add_funds_to_treasury_spend(
            xch_funds,
            action_scope,
        )
    await full_node_api.process_transaction_records(records=action_scope.side_effects.transactions)
    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(puzzle_hash_0))
    await full_node_api.wait_for_wallet_synced(wallet_node=wallet_node_0, timeout=30)

    # Check that the funding spend is recognized by both dao wallets
    await time_out_assert(10, dao_wallet_0.get_balance_by_asset_type, xch_funds)

    # Send some dao_cats to wallet_1
    # Get the cat wallets for wallet_1
    cat_wallet_1 = dao_wallet_1.wallet_state_manager.wallets[dao_wallet_1.dao_info.cat_wallet_id]
    dao_cat_wallet_1 = dao_wallet_1.wallet_state_manager.wallets[dao_wallet_1.dao_info.dao_cat_wallet_id]
    assert cat_wallet_1
    assert dao_cat_wallet_1

    async with cat_wallet_0.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
        await cat_wallet_0.generate_signed_transaction([100000], [ph_1], action_scope)
    await full_node_api.process_transaction_records(records=action_scope.side_effects.transactions)
    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(puzzle_hash_0))
    await full_node_api.wait_for_wallet_synced(wallet_node=wallet_node_0, timeout=30)
    await time_out_assert(10, cat_wallet_1.get_spendable_balance, 100000)

    # Create dao cats for voting
    dao_cat_0_bal = await dao_cat_wallet_0.get_votable_balance()
    async with dao_cat_wallet_0.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
        await dao_cat_wallet_0.enter_dao_cat_voting_mode(dao_cat_0_bal, action_scope)
    await full_node_api.process_transaction_records(records=action_scope.side_effects.transactions)
    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(puzzle_hash_0))
    await full_node_api.wait_for_wallets_synced(wallet_nodes=[wallet_node_0, wallet_node_1], timeout=30)

    # Create a mint proposal
    recipient_puzzle_hash = await cat_wallet_1.get_new_inner_hash()
    new_mint_amount = uint64(500)
    mint_proposal_inner = await generate_mint_proposal_innerpuz(
        treasury_id,
        cat_wallet_0.cat_info.limitations_program_hash,
        new_mint_amount,
        recipient_puzzle_hash,
    )

    vote_amount = dao_cat_0_bal - 10
    async with dao_wallet_0.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
        await dao_wallet_0.generate_new_proposal(
            mint_proposal_inner, action_scope, vote_amount=vote_amount, fee=uint64(1000)
        )
    await full_node_api.wait_transaction_records_entered_mempool(records=action_scope.side_effects.transactions)
    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(puzzle_hash_0))
    await full_node_api.wait_for_wallets_synced(wallet_nodes=[wallet_node_0, wallet_node_1], timeout=30)

    # Check the proposal is saved
    assert len(dao_wallet_0.dao_info.proposals_list) == 1
    assert dao_wallet_0.dao_info.proposals_list[0].amount_voted == vote_amount
    assert dao_wallet_0.dao_info.proposals_list[0].timer_coin is not None

    # Check that wallet_1 also finds and saved the proposal
    assert len(dao_wallet_1.dao_info.proposals_list) == 1
    prop = dao_wallet_1.dao_info.proposals_list[0]

    # Create votable dao cats and add a new vote
    dao_cat_1_bal = await dao_cat_wallet_1.get_votable_balance()
    async with dao_cat_wallet_1.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
        await dao_cat_wallet_1.enter_dao_cat_voting_mode(dao_cat_1_bal, action_scope)
    await full_node_api.process_transaction_records(records=action_scope.side_effects.transactions)
    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(puzzle_hash_0))
    await full_node_api.wait_for_wallets_synced(wallet_nodes=[wallet_node_0, wallet_node_1], timeout=30)

    async with dao_wallet_1.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
        await dao_wallet_1.generate_proposal_vote_spend(prop.proposal_id, dao_cat_1_bal // 2, True, action_scope)
    [vote_tx] = action_scope.side_effects.transactions
    vote_sb = vote_tx.spend_bundle
    assert vote_sb is not None
    await time_out_assert_not_none(5, full_node_api.full_node.mempool_manager.get_spendbundle, vote_sb.name())
    await full_node_api.process_spend_bundles(bundles=[vote_sb])

    for i in range(1, dao_rules.proposal_timelock + 1):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(puzzle_hash_0))
    await full_node_api.wait_for_wallets_synced(wallet_nodes=[wallet_node_0, wallet_node_1], timeout=30)

    total_votes = vote_amount + dao_cat_1_bal // 2

    assert dao_wallet_0.dao_info.proposals_list[0].amount_voted == total_votes
    assert dao_wallet_0.dao_info.proposals_list[0].yes_votes == total_votes
    assert dao_wallet_1.dao_info.proposals_list[0].amount_voted == total_votes
    assert dao_wallet_1.dao_info.proposals_list[0].yes_votes == total_votes

    try:
        async with dao_wallet_0.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
            await dao_wallet_0.create_proposal_close_spend(prop.proposal_id, action_scope, fee=uint64(100))
    except Exception as e:  # pragma: no cover
        print(e)

    await full_node_api.process_transaction_records(action_scope.side_effects.transactions)
    balance = await cat_wallet_1.get_spendable_balance()

    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(puzzle_hash_0))
    await full_node_api.wait_for_wallets_synced(wallet_nodes=[wallet_node_0, wallet_node_1], timeout=30)

    await time_out_assert(20, get_proposal_state, (True, True), dao_wallet_0, 0)
    await time_out_assert(20, get_proposal_state, (True, True), dao_wallet_1, 0)

    await time_out_assert(20, cat_wallet_1.get_spendable_balance, balance + new_mint_amount)
    # Can we spend the newly minted CATs?
    old_balance = await cat_wallet_0.get_spendable_balance()
    ph_0 = await cat_wallet_0.get_new_inner_hash()
    async with cat_wallet_1.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
        await cat_wallet_1.generate_signed_transaction([balance + new_mint_amount], [ph_0], action_scope)
    await full_node_api.process_transaction_records(records=action_scope.side_effects.transactions)
    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(puzzle_hash_0))
    await full_node_api.wait_for_wallets_synced(wallet_nodes=[wallet_node_0, wallet_node_1], timeout=30)

    await time_out_assert(20, cat_wallet_1.get_spendable_balance, 0)
    await time_out_assert(20, cat_wallet_0.get_spendable_balance, old_balance + balance + new_mint_amount)
    # release coins
    async with dao_wallet_0.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
        await dao_wallet_0.free_coins_from_finished_proposals(action_scope)


@pytest.mark.limit_consensus_modes(reason="does not depend on consensus rules")
@pytest.mark.parametrize(
    "trusted",
    [True, False],
)
@pytest.mark.anyio
async def test_dao_rpc_api(self_hostname: str, two_wallet_nodes: Any, trusted: Any) -> None:
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

    await server_0.start_client(PeerInfo(self_hostname, full_node_server.get_port()), None)
    await server_1.start_client(PeerInfo(self_hostname, full_node_server.get_port()), None)

    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph_0))
    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(puzzle_hash_0))
    await full_node_api.wait_for_wallet_synced(wallet_node=wallet_node_0, timeout=30)

    funds = calculate_pool_reward(uint32(1)) + calculate_base_farmer_reward(uint32(1))

    await time_out_assert(30, wallet_0.get_unconfirmed_balance, funds)
    await time_out_assert(30, wallet_0.get_confirmed_balance, funds)

    api_0 = WalletRpcApi(wallet_node_0)
    api_1 = WalletRpcApi(wallet_node_1)

    cat_amt = 300000
    fee = 10000
    dao_rules = DAORules(
        proposal_timelock=uint64(10),
        soft_close_length=uint64(5),
        attendance_required=uint64(1000),  # 10%
        pass_percentage=uint64(5100),  # 51%
        self_destruct_length=uint64(20),
        oracle_spend_delay=uint64(10),
        proposal_minimum_amount=uint64(1),
    )

    # Try to create a DAO without rules
    with pytest.raises(ValueError) as e_info:
        dao_wallet_0 = await api_0.create_new_wallet(
            dict(
                wallet_type="dao_wallet",
                name="DAO WALLET 1",
                mode="new",
                amount_of_cats=cat_amt,
                filter_amount=1,
                fee=fee,
            )
        )
    assert e_info.value.args[0] == "DAO rules must be specified for wallet creation"

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
    txs = await wallet_0.wallet_state_manager.tx_store.get_all_unconfirmed()
    await full_node_api.wait_transaction_records_entered_mempool(records=txs, timeout=60)
    await full_node_api.process_all_wallet_transactions(wallet_0, timeout=60)
    await full_node_api.wait_for_wallet_synced(wallet_node=wallet_node_0, timeout=30)

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
            test=True,
            mode="new",
            amount=new_cat_amt,
        )
    )
    txs = await wallet_0.wallet_state_manager.tx_store.get_all_unconfirmed()
    await full_node_api.wait_transaction_records_entered_mempool(records=txs, timeout=60)
    await full_node_api.process_all_wallet_transactions(wallet_0, timeout=60)
    await full_node_api.wait_for_wallet_synced(wallet_node=wallet_node_0, timeout=30)

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
    cat_tx = await api_0.dao_add_funds_to_treasury(
        dict(
            wallet_id=dao_wallet_0_id,
            amount=cat_funding_amt,
            funding_wallet_id=cat_wallet_0_id,
        )
    )

    xch_funding_amt = 200000
    xch_tx = await api_0.dao_add_funds_to_treasury(
        dict(
            wallet_id=dao_wallet_0_id,
            amount=xch_funding_amt,
            funding_wallet_id=1,
        )
    )
    txs = [TransactionRecord.from_json_dict(cat_tx["tx"]), TransactionRecord.from_json_dict(xch_tx["tx"])]
    await full_node_api.wait_transaction_records_entered_mempool(records=txs, timeout=60)
    await full_node_api.process_all_wallet_transactions(wallet_0, timeout=60)
    await full_node_api.wait_for_wallet_synced(wallet_node=wallet_node_0, timeout=30)

    expected_xch -= xch_funding_amt + new_cat_amt
    await time_out_assert(30, wallet_0.get_confirmed_balance, expected_xch)

    await rpc_state(
        20,
        api_0.get_wallet_balance,
        [{"wallet_id": cat_wallet_0_id}],
        lambda x: x["wallet_balance"]["confirmed_wallet_balance"],
        new_cat_amt - cat_funding_amt,
    )

    await rpc_state(
        20, api_0.dao_get_treasury_balance, [{"wallet_id": dao_wallet_0_id}], lambda x: x["balances"]["xch"]
    )
    balances = await api_0.dao_get_treasury_balance({"wallet_id": dao_wallet_0_id})
    assert balances["balances"]["xch"] == xch_funding_amt
    assert balances["balances"][cat_id.hex()] == cat_funding_amt

    # Send some cats to wallet_1
    await api_0.cat_spend(
        {
            "wallet_id": dao_cat_wallet_0_id,
            "amount": cat_amt // 2,
            "inner_address": encode_puzzle_hash(ph_1, "xch"),
            "fee": fee,
        }
    )
    txs = await wallet_0.wallet_state_manager.tx_store.get_all_unconfirmed()
    await full_node_api.wait_transaction_records_entered_mempool(records=txs, timeout=60)
    await full_node_api.process_all_wallet_transactions(wallet_0, timeout=60)
    await full_node_api.wait_for_wallet_synced(wallet_node=wallet_node_0, timeout=30)

    await rpc_state(
        20,
        api_0.get_wallet_balance,
        [{"wallet_id": dao_cat_wallet_0_id}],
        lambda x: x["wallet_balance"]["confirmed_wallet_balance"],
        cat_amt // 2,
    )

    # send cats to lockup
    await api_0.dao_send_to_lockup({"wallet_id": dao_wallet_0_id, "amount": cat_amt // 2})
    tx_queue = await wallet_node_0.wallet_state_manager.tx_store.get_not_sent()
    await full_node_api.process_transaction_records(records=[tx for tx in tx_queue])
    await api_1.dao_send_to_lockup({"wallet_id": dao_wallet_1_id, "amount": cat_amt // 2})
    tx_queue = await wallet_node_1.wallet_state_manager.tx_store.get_not_sent()
    await full_node_api.process_transaction_records(records=[tx for tx in tx_queue])
    await full_node_api.wait_for_wallet_synced(wallet_node=wallet_node_0, timeout=30)

    # create a spend proposal
    additions = [
        {"puzzle_hash": ph_1.hex(), "amount": 1000},
    ]
    create_proposal = await api_0.dao_create_proposal(
        {
            "wallet_id": dao_wallet_0_id,
            "proposal_type": "spend",
            "additions": additions,
            "vote_amount": cat_amt // 2,
            "fee": fee,
        }
    )
    txs = [TransactionRecord.from_json_dict(create_proposal["tx"])]
    await full_node_api.wait_transaction_records_entered_mempool(records=txs, timeout=60)
    await full_node_api.process_all_wallet_transactions(wallet_0, timeout=60)
    await full_node_api.wait_for_wallets_synced(wallet_nodes=[wallet_node_0, wallet_node_1], timeout=30)

    await rpc_state(20, api_0.dao_get_proposals, [{"wallet_id": dao_wallet_0_id}], lambda x: len(x["proposals"]), 1)

    await rpc_state(20, api_1.dao_get_proposals, [{"wallet_id": dao_wallet_1_id}], lambda x: len(x["proposals"]), 1)

    props_0 = await api_0.dao_get_proposals({"wallet_id": dao_wallet_0_id})
    prop = props_0["proposals"][0]
    assert prop.amount_voted == cat_amt // 2
    assert prop.yes_votes == cat_amt // 2

    # Add votes
    vote_tx = await api_1.dao_vote_on_proposal(
        {
            "wallet_id": dao_wallet_1_id,
            "vote_amount": cat_amt // 2,
            "proposal_id": prop.proposal_id.hex(),
            "is_yes_vote": True,
        }
    )
    txs = [TransactionRecord.from_json_dict(vote_tx["tx"])]
    await full_node_api.wait_transaction_records_entered_mempool(records=txs, timeout=60)
    await full_node_api.process_all_wallet_transactions(wallet_1, timeout=60)
    await full_node_api.wait_for_wallets_synced(wallet_nodes=[wallet_node_0, wallet_node_1], timeout=30)

    await rpc_state(
        20, api_0.dao_get_proposals, [{"wallet_id": dao_wallet_0_id}], lambda x: x["proposals"][0].amount_voted, cat_amt
    )

    # farm blocks until we can close proposal
    state = await api_0.dao_get_proposal_state({"wallet_id": dao_wallet_0_id, "proposal_id": prop.proposal_id.hex()})
    for _ in range(state["state"]["blocks_needed"] + 1):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(puzzle_hash_0))
    await full_node_api.wait_for_wallets_synced(wallet_nodes=[wallet_node_0, wallet_node_1], timeout=30)

    await rpc_state(
        20,
        api_0.dao_get_proposal_state,
        [{"wallet_id": dao_wallet_0_id, "proposal_id": prop.proposal_id.hex()}],
        lambda x: x["state"]["closable"],
        True,
    )

    proposal_tx = await api_0.dao_close_proposal({"wallet_id": dao_wallet_0_id, "proposal_id": prop.proposal_id.hex()})
    txs = [TransactionRecord.from_json_dict(proposal_tx["tx"])]
    try:
        await full_node_api.wait_transaction_records_entered_mempool(records=txs, timeout=60)
    except TimeoutError:  # pragma: no cover
        # try again
        await api_0.push_tx({"spend_bundle": txs[0].spend_bundle.stream_to_bytes().hex()})
        await full_node_api.wait_transaction_records_marked_as_in_mempool([txs[0].name], wallet_node_0, 60)
    await full_node_api.process_all_wallet_transactions(wallet_0, timeout=60)
    await full_node_api.wait_for_wallets_synced(wallet_nodes=[wallet_node_0, wallet_node_1], timeout=30)

    await rpc_state(
        20, api_0.dao_get_proposals, [{"wallet_id": dao_wallet_0_id}], lambda x: x["proposals"][0].closed, True
    )

    # check that the proposal state has changed for everyone
    await rpc_state(
        20,
        api_0.dao_get_proposal_state,
        [{"wallet_id": dao_wallet_0_id, "proposal_id": prop.proposal_id.hex()}],
        lambda x: x["state"]["closed"],
        True,
    )

    await rpc_state(
        20,
        api_1.dao_get_proposal_state,
        [{"wallet_id": dao_wallet_1_id, "proposal_id": prop.proposal_id.hex()}],
        lambda x: x["state"]["closed"],
        True,
    )

    # create a mint proposal
    mint_proposal = await api_0.dao_create_proposal(
        {
            "wallet_id": dao_wallet_0_id,
            "proposal_type": "mint",
            "amount": uint64(10000),
            "cat_target_address": encode_puzzle_hash(ph_0, "xch"),
            "vote_amount": cat_amt // 2,
            "fee": fee,
        }
    )
    txs = [TransactionRecord.from_json_dict(mint_proposal["tx"])]
    await full_node_api.wait_transaction_records_entered_mempool(records=txs, timeout=60)
    await full_node_api.process_all_wallet_transactions(wallet_0, timeout=60)
    await full_node_api.wait_for_wallets_synced(wallet_nodes=[wallet_node_0, wallet_node_1], timeout=30)

    await rpc_state(20, api_0.dao_get_proposals, [{"wallet_id": dao_wallet_0_id}], lambda x: len(x["proposals"]), 2)

    await rpc_state(20, api_1.dao_get_proposals, [{"wallet_id": dao_wallet_1_id}], lambda x: len(x["proposals"]), 2)

    props = await api_0.dao_get_proposals({"wallet_id": dao_wallet_0_id})
    prop = props["proposals"][1]
    assert prop.amount_voted == cat_amt // 2
    assert prop.yes_votes == cat_amt // 2

    # Add votes
    vote_tx = await api_1.dao_vote_on_proposal(
        {
            "wallet_id": dao_wallet_1_id,
            "vote_amount": cat_amt // 2,
            "proposal_id": prop.proposal_id.hex(),
            "is_yes_vote": True,
        }
    )
    txs = [TransactionRecord.from_json_dict(vote_tx["tx"])]
    await full_node_api.wait_transaction_records_entered_mempool(records=txs, timeout=60)
    await full_node_api.process_all_wallet_transactions(wallet_1, timeout=60)
    await full_node_api.wait_for_wallets_synced(wallet_nodes=[wallet_node_0, wallet_node_1], timeout=30)

    await rpc_state(
        20, api_0.dao_get_proposals, [{"wallet_id": dao_wallet_0_id}], lambda x: x["proposals"][1].amount_voted, cat_amt
    )

    # farm blocks until we can close proposal
    state = await api_0.dao_get_proposal_state({"wallet_id": dao_wallet_0_id, "proposal_id": prop.proposal_id.hex()})
    for _ in range(state["state"]["blocks_needed"] + 1):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(puzzle_hash_0))
    await full_node_api.wait_for_wallets_synced(wallet_nodes=[wallet_node_0, wallet_node_1], timeout=30)

    await rpc_state(
        20,
        api_0.dao_get_proposal_state,
        [{"wallet_id": dao_wallet_0_id, "proposal_id": prop.proposal_id.hex()}],
        lambda x: x["state"]["closable"],
        True,
    )

    proposal_tx = await api_0.dao_close_proposal({"wallet_id": dao_wallet_0_id, "proposal_id": prop.proposal_id.hex()})
    txs = [TransactionRecord.from_json_dict(proposal_tx["tx"])]
    try:
        await full_node_api.wait_transaction_records_entered_mempool(records=txs, timeout=60)
    except TimeoutError:  # pragma: no cover
        # try again
        await api_0.push_tx({"spend_bundle": txs[0].spend_bundle.stream_to_bytes().hex()})
        await full_node_api.wait_transaction_records_marked_as_in_mempool([txs[0].name], wallet_node_0, 60)
    await full_node_api.process_all_wallet_transactions(wallet_0, timeout=60)
    await full_node_api.wait_for_wallets_synced(wallet_nodes=[wallet_node_0, wallet_node_1], timeout=30)

    await rpc_state(
        20, api_0.dao_get_proposals, [{"wallet_id": dao_wallet_0_id}], lambda x: x["proposals"][1].closed, True
    )

    # check that the proposal state has changed for everyone
    await rpc_state(
        20,
        api_0.dao_get_proposal_state,
        [{"wallet_id": dao_wallet_0_id, "proposal_id": prop.proposal_id.hex()}],
        lambda x: x["state"]["closed"],
        True,
    )

    await rpc_state(
        20,
        api_1.dao_get_proposal_state,
        [{"wallet_id": dao_wallet_1_id, "proposal_id": prop.proposal_id.hex()}],
        lambda x: x["state"]["closed"],
        True,
    )

    # Check the minted cats are received
    await rpc_state(
        20,
        api_0.get_wallet_balance,
        [{"wallet_id": dao_cat_wallet_0_id}],
        lambda x: x["wallet_balance"]["confirmed_wallet_balance"],
        10000,
    )

    # create an update proposal
    new_dao_rules = {"pass_percentage": 10000}
    update_proposal = await api_0.dao_create_proposal(
        {
            "wallet_id": dao_wallet_0_id,
            "proposal_type": "update",
            "new_dao_rules": new_dao_rules,
            "vote_amount": cat_amt // 2,
            "fee": fee,
        }
    )
    txs = [TransactionRecord.from_json_dict(update_proposal["tx"])]
    await full_node_api.wait_transaction_records_entered_mempool(records=txs, timeout=60)
    await full_node_api.process_all_wallet_transactions(wallet_0, timeout=60)
    await full_node_api.wait_for_wallets_synced(wallet_nodes=[wallet_node_0, wallet_node_1], timeout=30)

    await rpc_state(20, api_0.dao_get_proposals, [{"wallet_id": dao_wallet_0_id}], lambda x: len(x["proposals"]), 3)

    await rpc_state(20, api_1.dao_get_proposals, [{"wallet_id": dao_wallet_1_id}], lambda x: len(x["proposals"]), 3)

    props = await api_0.dao_get_proposals({"wallet_id": dao_wallet_0_id})
    prop = props["proposals"][2]
    assert prop.amount_voted == cat_amt // 2
    assert prop.yes_votes == cat_amt // 2

    # Add votes
    vote_tx = await api_1.dao_vote_on_proposal(
        {
            "wallet_id": dao_wallet_1_id,
            "vote_amount": cat_amt // 2,
            "proposal_id": prop.proposal_id.hex(),
            "is_yes_vote": True,
        }
    )
    txs = [TransactionRecord.from_json_dict(vote_tx["tx"])]
    await full_node_api.wait_transaction_records_entered_mempool(records=txs, timeout=60)
    await full_node_api.process_all_wallet_transactions(wallet_1, timeout=60)
    await full_node_api.wait_for_wallets_synced(wallet_nodes=[wallet_node_0, wallet_node_1], timeout=30)

    await rpc_state(
        20, api_0.dao_get_proposals, [{"wallet_id": dao_wallet_0_id}], lambda x: x["proposals"][2].amount_voted, cat_amt
    )

    # farm blocks until we can close proposal
    state = await api_0.dao_get_proposal_state({"wallet_id": dao_wallet_0_id, "proposal_id": prop.proposal_id.hex()})
    for _ in range(state["state"]["blocks_needed"] + 1):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(puzzle_hash_0))
    await full_node_api.wait_for_wallets_synced(wallet_nodes=[wallet_node_0, wallet_node_1], timeout=30)

    await rpc_state(
        20,
        api_0.dao_get_proposal_state,
        [{"wallet_id": dao_wallet_0_id, "proposal_id": prop.proposal_id.hex()}],
        lambda x: x["state"]["closable"],
        True,
    )

    open_props = await api_0.dao_get_proposals({"wallet_id": dao_wallet_0_id, "include_closed": False})
    assert len(open_props["proposals"]) == 1

    close_tx = await api_0.dao_close_proposal({"wallet_id": dao_wallet_0_id, "proposal_id": prop.proposal_id.hex()})
    txs = [TransactionRecord.from_json_dict(close_tx["tx"])]
    try:
        await full_node_api.wait_transaction_records_entered_mempool(records=txs, timeout=60)
    except TimeoutError:  # pragma: no cover
        # try again
        await api_0.push_tx({"spend_bundle": txs[0].spend_bundle.stream_to_bytes().hex()})
        await full_node_api.wait_transaction_records_marked_as_in_mempool([txs[0].name], wallet_node_0, 60)
    await full_node_api.process_all_wallet_transactions(wallet_0, timeout=60)
    await full_node_api.wait_for_wallets_synced(wallet_nodes=[wallet_node_0, wallet_node_1], timeout=30)

    await rpc_state(
        20, api_0.dao_get_proposals, [{"wallet_id": dao_wallet_0_id}], lambda x: x["proposals"][1].closed, True
    )

    # check that the proposal state has changed for everyone
    await rpc_state(
        20,
        api_0.dao_get_proposal_state,
        [{"wallet_id": dao_wallet_0_id, "proposal_id": prop.proposal_id.hex()}],
        lambda x: x["state"]["closed"],
        True,
    )

    await rpc_state(
        20,
        api_1.dao_get_proposal_state,
        [{"wallet_id": dao_wallet_1_id, "proposal_id": prop.proposal_id.hex()}],
        lambda x: x["state"]["closed"],
        True,
    )

    # Check the rules have updated
    dao_wallet = wallet_node_0.wallet_state_manager.wallets[dao_wallet_0_id]
    assert dao_wallet.dao_rules.pass_percentage == 10000

    # Test adjust filter level
    resp = await api_0.dao_adjust_filter_level({"wallet_id": dao_wallet_1_id, "filter_level": 101})
    assert resp["success"]
    assert resp["dao_info"].filter_below_vote_amount == 101

    # Test get_treasury_id
    resp = await api_0.dao_get_treasury_id({"wallet_id": dao_wallet_0_id})
    assert resp["treasury_id"] == treasury_id


@pytest.mark.limit_consensus_modes(reason="does not depend on consensus rules")
@pytest.mark.parametrize(
    "trusted",
    [True, False],
)
@pytest.mark.anyio
async def test_dao_rpc_client(
    two_wallet_nodes_services: SimulatorsAndWalletsServices, trusted: bool, self_hostname: str
) -> None:
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

    await server_0.start_client(PeerInfo(self_hostname, full_node_server.get_port()), None)
    await server_1.start_client(PeerInfo(self_hostname, full_node_server.get_port()), None)

    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph_0))
    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph_1))
    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(puzzle_hash_0))
    await full_node_api.wait_for_wallets_synced(wallet_nodes=[wallet_node_0, wallet_node_1], timeout=30)

    initial_funds = calculate_pool_reward(uint32(1)) + calculate_base_farmer_reward(uint32(1))

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
        cat_amt = uint64(150000)
        amount_of_cats = uint64(cat_amt * 2)
        dao_rules = DAORules(
            proposal_timelock=uint64(8),
            soft_close_length=uint64(4),
            attendance_required=uint64(1000),  # 10%
            pass_percentage=uint64(4900),  # 49%
            self_destruct_length=uint64(20),
            oracle_spend_delay=uint64(10),
            proposal_minimum_amount=uint64(1),
        )
        filter_amount = uint64(1)
        fee = uint64(10000)

        # create new dao
        dao_wallet_res_0 = await client_0.create_new_dao_wallet(
            mode="new",
            tx_config=DEFAULT_TX_CONFIG,
            dao_rules=dao_rules.to_json_dict(),
            amount_of_cats=amount_of_cats,
            filter_amount=filter_amount,
            name="DAO WALLET 0",
        )
        dao_id_0 = dao_wallet_res_0.wallet_id
        cat_wallet_0 = wallet_node_0.wallet_state_manager.wallets[dao_wallet_res_0.cat_wallet_id]

        txs = await wallet_0.wallet_state_manager.tx_store.get_all_unconfirmed()
        await full_node_api.wait_transaction_records_entered_mempool(records=txs, timeout=60)
        await full_node_api.process_all_wallet_transactions(wallet_0, timeout=60)
        await full_node_api.wait_for_wallets_synced(wallet_nodes=[wallet_node_0, wallet_node_1], timeout=30)

        await time_out_assert(20, cat_wallet_0.get_confirmed_balance, amount_of_cats)

        # Create a new standard cat for treasury funds
        new_cat_amt = uint64(100000)
        new_cat_res = await client_0.create_new_cat_and_wallet(new_cat_amt, test=True)
        new_cat_wallet_id = new_cat_res["wallet_id"]
        new_cat_wallet = wallet_node_0.wallet_state_manager.wallets[new_cat_wallet_id]

        txs = await wallet_0.wallet_state_manager.tx_store.get_all_unconfirmed()
        await full_node_api.wait_transaction_records_entered_mempool(records=txs, timeout=60)
        await full_node_api.process_all_wallet_transactions(wallet_0, timeout=60)
        await full_node_api.wait_for_wallets_synced(wallet_nodes=[wallet_node_0, wallet_node_1], timeout=30)

        # join dao
        dao_wallet_res_1 = await client_1.create_new_dao_wallet(
            mode="existing",
            tx_config=DEFAULT_TX_CONFIG,
            treasury_id=dao_wallet_res_0.treasury_id,
            filter_amount=filter_amount,
            name="DAO WALLET 1",
        )
        dao_id_1 = dao_wallet_res_1.wallet_id
        cat_wallet_1 = wallet_node_1.wallet_state_manager.wallets[dao_wallet_res_1.cat_wallet_id]

        # fund treasury
        xch_funds = uint64(10000000000)
        await client_0.dao_add_funds_to_treasury(dao_id_0, 1, xch_funds, DEFAULT_TX_CONFIG)
        await client_0.dao_add_funds_to_treasury(dao_id_0, new_cat_wallet_id, new_cat_amt, DEFAULT_TX_CONFIG)
        txs = await wallet_0.wallet_state_manager.tx_store.get_all_unconfirmed()
        await full_node_api.wait_transaction_records_entered_mempool(records=txs, timeout=60)
        await full_node_api.process_all_wallet_transactions(wallet_0, timeout=60)
        await full_node_api.wait_for_wallets_synced(wallet_nodes=[wallet_node_0, wallet_node_1], timeout=30)

        await rpc_state(20, client_0.dao_get_treasury_balance, [dao_id_0], lambda x: x["balances"]["xch"], xch_funds)
        assert isinstance(new_cat_wallet, CATWallet)
        new_cat_asset_id = new_cat_wallet.cat_info.limitations_program_hash
        await rpc_state(
            20,
            client_0.dao_get_treasury_balance,
            [dao_id_0],
            lambda x: x["balances"][new_cat_asset_id.hex()],
            new_cat_amt,
        )
        await rpc_state(
            20,
            client_0.dao_get_treasury_balance,
            [dao_id_0],
            lambda x: x["balances"]["xch"],
            xch_funds,
        )

        # send cats to wallet 1
        await client_0.cat_spend(
            wallet_id=dao_wallet_res_0.cat_wallet_id,
            tx_config=DEFAULT_TX_CONFIG,
            amount=cat_amt,
            inner_address=encode_puzzle_hash(ph_1, "xch"),
            fee=fee,
        )

        txs = await wallet_0.wallet_state_manager.tx_store.get_all_unconfirmed()
        await full_node_api.wait_transaction_records_entered_mempool(records=txs, timeout=60)
        await full_node_api.process_all_wallet_transactions(wallet_0, timeout=60)
        await full_node_api.wait_for_wallets_synced(wallet_nodes=[wallet_node_0, wallet_node_1], timeout=30)

        await time_out_assert(20, cat_wallet_0.get_confirmed_balance, cat_amt)
        await time_out_assert(20, cat_wallet_1.get_confirmed_balance, cat_amt)

        # send cats to lockup
        await client_0.dao_send_to_lockup(dao_id_0, cat_amt, DEFAULT_TX_CONFIG)
        await client_1.dao_send_to_lockup(dao_id_1, cat_amt, DEFAULT_TX_CONFIG)

        txs_0 = await wallet_0.wallet_state_manager.tx_store.get_all_unconfirmed()
        txs_1 = await wallet_1.wallet_state_manager.tx_store.get_all_unconfirmed()
        await full_node_api.wait_transaction_records_entered_mempool(records=txs_0 + txs_1, timeout=60)
        await full_node_api.process_all_wallet_transactions(wallet_0, timeout=60)
        await full_node_api.process_all_wallet_transactions(wallet_1, timeout=60)
        await full_node_api.wait_for_wallets_synced(wallet_nodes=[wallet_node_0, wallet_node_1], timeout=30)

        # create a spend proposal
        additions = [
            {"puzzle_hash": ph_0.hex(), "amount": 1000},
            {"puzzle_hash": ph_0.hex(), "amount": 10000, "asset_id": new_cat_asset_id.hex()},
        ]
        await client_0.dao_create_proposal(
            wallet_id=dao_id_0,
            proposal_type="spend",
            tx_config=DEFAULT_TX_CONFIG,
            additions=additions,
            vote_amount=cat_amt,
            fee=fee,
        )
        txs = await wallet_0.wallet_state_manager.tx_store.get_all_unconfirmed()
        await full_node_api.wait_transaction_records_entered_mempool(records=txs, timeout=60)
        await full_node_api.process_all_wallet_transactions(wallet_0, timeout=60)
        await full_node_api.wait_for_wallets_synced(wallet_nodes=[wallet_node_0, wallet_node_1], timeout=30)

        # check proposal is found by wallet 1
        await rpc_state(20, client_1.dao_get_proposals, [dao_id_1], lambda x: x["proposals"][0]["yes_votes"], cat_amt)
        props = await client_1.dao_get_proposals(dao_id_1)
        proposal_id_hex = props["proposals"][0]["proposal_id"]

        # create an update proposal
        await client_1.dao_create_proposal(
            wallet_id=dao_id_1,
            proposal_type="update",
            tx_config=DEFAULT_TX_CONFIG,
            vote_amount=cat_amt,
            new_dao_rules={"proposal_timelock": uint64(10)},
            fee=fee,
        )
        txs = await wallet_1.wallet_state_manager.tx_store.get_all_unconfirmed()
        await full_node_api.wait_transaction_records_entered_mempool(records=txs, timeout=60)
        await full_node_api.process_all_wallet_transactions(wallet_1, timeout=60)
        await full_node_api.wait_for_wallets_synced(wallet_nodes=[wallet_node_0, wallet_node_1], timeout=30)

        # create a mint proposal
        mint_addr = await client_1.get_next_address(wallet_id=wallet_1.id(), new_address=False)
        await client_1.dao_create_proposal(
            wallet_id=dao_id_1,
            proposal_type="mint",
            tx_config=DEFAULT_TX_CONFIG,
            vote_amount=cat_amt,
            amount=uint64(100),
            cat_target_address=mint_addr,
            fee=fee,
        )
        txs = await wallet_1.wallet_state_manager.tx_store.get_all_unconfirmed()
        await full_node_api.wait_transaction_records_entered_mempool(records=txs, timeout=60)
        await full_node_api.process_all_wallet_transactions(wallet_1, timeout=60)
        await full_node_api.wait_for_wallets_synced(wallet_nodes=[wallet_node_0, wallet_node_1], timeout=30)

        # vote spend
        await client_1.dao_vote_on_proposal(
            wallet_id=dao_id_1,
            proposal_id=proposal_id_hex,
            vote_amount=cat_amt,
            tx_config=DEFAULT_TX_CONFIG,
            is_yes_vote=True,
            fee=fee,
        )
        txs = await wallet_1.wallet_state_manager.tx_store.get_all_unconfirmed()
        await full_node_api.wait_transaction_records_entered_mempool(records=txs, timeout=60)
        await full_node_api.process_all_wallet_transactions(wallet_1, timeout=60)
        await full_node_api.wait_for_wallets_synced(wallet_nodes=[wallet_node_0, wallet_node_1], timeout=30)

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
        await full_node_api.wait_for_wallets_synced(wallet_nodes=[wallet_node_0, wallet_node_1], timeout=30)

        state = await client_0.dao_get_proposal_state(wallet_id=dao_id_0, proposal_id=proposal_id_hex)
        assert state["success"]
        assert state["state"]["closable"]

        # check proposal parsing
        props = await client_0.dao_get_proposals(dao_id_0)
        proposal_2_hex = props["proposals"][1]["proposal_id"]
        proposal_3_hex = props["proposals"][2]["proposal_id"]
        parsed_1 = await client_0.dao_parse_proposal(wallet_id=dao_id_0, proposal_id=proposal_id_hex)
        assert parsed_1["success"]
        parsed_2 = await client_0.dao_parse_proposal(wallet_id=dao_id_0, proposal_id=proposal_2_hex)
        assert parsed_2["success"]
        parsed_3 = await client_0.dao_parse_proposal(wallet_id=dao_id_0, proposal_id=proposal_3_hex)
        assert parsed_3["success"]

        # farm blocks so proposal can close
        for i in range(1, 10):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(puzzle_hash_0))
        await full_node_api.wait_for_wallets_synced(wallet_nodes=[wallet_node_0, wallet_node_1], timeout=30)

        # close the proposal
        close = await client_0.dao_close_proposal(
            wallet_id=dao_id_0, proposal_id=proposal_id_hex, tx_config=DEFAULT_TX_CONFIG, self_destruct=False, fee=fee
        )
        tx = close.tx
        await full_node_api.wait_transaction_records_entered_mempool(records=[tx], timeout=60)
        await full_node_api.process_all_wallet_transactions(wallet_0, timeout=60)
        await full_node_api.wait_for_wallets_synced(wallet_nodes=[wallet_node_0, wallet_node_1], timeout=30)

        # check proposal is closed
        await rpc_state(20, client_0.dao_get_proposals, [dao_id_0], lambda x: x["proposals"][0]["closed"], True)
        await rpc_state(20, client_1.dao_get_proposals, [dao_id_1], lambda x: x["proposals"][0]["closed"], True)
        # check treasury balances
        await rpc_state(
            20,
            client_0.dao_get_treasury_balance,
            [dao_id_0],
            lambda x: x["balances"][new_cat_asset_id.hex()],
            new_cat_amt - 10000,
        )
        await rpc_state(
            20, client_0.dao_get_treasury_balance, [dao_id_0], lambda x: x["balances"]["xch"], xch_funds - 1000
        )

        # check wallet balances
        await rpc_state(
            20, client_0.get_wallet_balance, [new_cat_wallet_id], lambda x: x["confirmed_wallet_balance"], 10000
        )
        expected_xch = initial_funds - amount_of_cats - new_cat_amt - xch_funds - (2 * fee) - 2 - 9000
        await rpc_state(
            20, client_0.get_wallet_balance, [wallet_0.id()], lambda x: x["confirmed_wallet_balance"], expected_xch
        )

        # close the mint proposal
        props = await client_0.dao_get_proposals(dao_id_0)
        proposal_id_hex = props["proposals"][2]["proposal_id"]
        close = await client_0.dao_close_proposal(
            wallet_id=dao_id_0, proposal_id=proposal_id_hex, tx_config=DEFAULT_TX_CONFIG, self_destruct=False, fee=fee
        )
        tx = close.tx
        await full_node_api.wait_transaction_records_entered_mempool(records=[tx], timeout=60)
        await full_node_api.process_all_wallet_transactions(wallet_0, timeout=60)
        await full_node_api.wait_for_wallets_synced(wallet_nodes=[wallet_node_0, wallet_node_1], timeout=30)

        # check proposal is closed
        await rpc_state(20, client_0.dao_get_proposals, [dao_id_0], lambda x: x["proposals"][2]["closed"], True)
        await rpc_state(20, client_1.dao_get_proposals, [dao_id_1], lambda x: x["proposals"][2]["closed"], True)

        # check minted cats are received
        await rpc_state(
            20,
            client_1.get_wallet_balance,
            [dao_wallet_res_1.cat_wallet_id],
            lambda x: x["confirmed_wallet_balance"],
            100,
        )

        open_props = await client_0.dao_get_proposals(dao_id_0, False)
        assert len(open_props["proposals"]) == 1

        # close the update proposal
        proposal_id_hex = props["proposals"][1]["proposal_id"]
        close = await client_0.dao_close_proposal(
            wallet_id=dao_id_0, proposal_id=proposal_id_hex, tx_config=DEFAULT_TX_CONFIG, self_destruct=False, fee=fee
        )
        tx = close.tx
        await full_node_api.wait_transaction_records_entered_mempool(records=[tx], timeout=60)
        await full_node_api.process_all_wallet_transactions(wallet_0, timeout=60)
        await full_node_api.wait_for_wallets_synced(wallet_nodes=[wallet_node_0, wallet_node_1], timeout=30)

        # check proposal is closed
        await rpc_state(20, client_0.dao_get_proposals, [dao_id_0], lambda x: x["proposals"][1]["closed"], True)
        await rpc_state(20, client_1.dao_get_proposals, [dao_id_1], lambda x: x["proposals"][1]["closed"], True)

        # check dao rules are updated
        new_rules = await client_0.dao_get_rules(dao_id_0)
        assert new_rules["rules"]["proposal_timelock"] == 10
        new_rules_1 = await client_0.dao_get_rules(dao_id_1)
        assert new_rules_1["rules"]["proposal_timelock"] == 10

        # free locked cats from finished proposal
        free_coins_res = await client_0.dao_free_coins_from_finished_proposals(
            wallet_id=dao_id_0, tx_config=DEFAULT_TX_CONFIG
        )
        free_coins_tx = free_coins_res.tx
        await full_node_api.wait_transaction_records_entered_mempool(records=[free_coins_tx], timeout=60)
        await full_node_api.process_all_wallet_transactions(wallet_0, timeout=60)
        await full_node_api.wait_for_wallets_synced(wallet_nodes=[wallet_node_0, wallet_node_1], timeout=30)

        bal = await client_0.get_wallet_balance(dao_wallet_res_0.dao_cat_wallet_id)
        assert bal["confirmed_wallet_balance"] == cat_amt

        exit = await client_0.dao_exit_lockup(dao_id_0, tx_config=DEFAULT_TX_CONFIG)
        exit_tx = exit.tx
        await full_node_api.wait_transaction_records_entered_mempool(records=[exit_tx], timeout=60)
        await full_node_api.process_all_wallet_transactions(wallet_0, timeout=60)
        await full_node_api.wait_for_wallets_synced(wallet_nodes=[wallet_node_0, wallet_node_1], timeout=30)

        await rpc_state(
            20,
            client_0.get_wallet_balance,
            [dao_wallet_res_0.cat_wallet_id],
            lambda x: x["confirmed_wallet_balance"],
            cat_amt,
        )

        # coverage tests for filter amount and get treasury id
        treasury_id_resp = await client_0.dao_get_treasury_id(wallet_id=dao_id_0)
        assert treasury_id_resp["treasury_id"] == "0x" + dao_wallet_res_0.treasury_id.hex()
        filter_amount_resp = await client_0.dao_adjust_filter_level(wallet_id=dao_id_0, filter_level=30)
        assert filter_amount_resp["dao_info"]["filter_below_vote_amount"] == 30

    finally:
        client_0.close()
        client_1.close()
        await client_0.await_closed()
        await client_1.await_closed()


@pytest.mark.limit_consensus_modes(reason="does not depend on consensus rules")
@pytest.mark.parametrize(
    "trusted",
    [True, False],
)
@pytest.mark.anyio
async def test_dao_complex_spends(
    two_wallet_nodes_services: SimulatorsAndWalletsServices, trusted: bool, self_hostname: str
) -> None:
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

    await server_0.start_client(PeerInfo(self_hostname, full_node_server.get_port()), None)
    await server_1.start_client(PeerInfo(self_hostname, full_node_server.get_port()), None)

    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph_0))
    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph_1))
    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(puzzle_hash_0))
    await full_node_api.wait_for_wallets_synced(wallet_nodes=[wallet_node_0, wallet_node_1], timeout=30)

    initial_funds = calculate_pool_reward(uint32(1)) + calculate_base_farmer_reward(uint32(1))

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
        cat_amt = uint64(300000)
        dao_rules = DAORules(
            proposal_timelock=uint64(2),
            soft_close_length=uint64(2),
            attendance_required=uint64(1000),  # 10%
            pass_percentage=uint64(5100),  # 51%
            self_destruct_length=uint64(5),
            oracle_spend_delay=uint64(2),
            proposal_minimum_amount=uint64(1),
        )
        filter_amount = uint64(1)

        # create new dao
        dao_wallet_res_0 = await client_0.create_new_dao_wallet(
            mode="new",
            tx_config=DEFAULT_TX_CONFIG,
            dao_rules=dao_rules.to_json_dict(),
            amount_of_cats=cat_amt,
            filter_amount=filter_amount,
            name="DAO WALLET 0",
        )
        dao_id_0 = dao_wallet_res_0.wallet_id
        treasury_id = dao_wallet_res_0.treasury_id
        cat_wallet_0 = wallet_node_0.wallet_state_manager.wallets[dao_wallet_res_0.cat_wallet_id]

        txs = await wallet_0.wallet_state_manager.tx_store.get_all_unconfirmed()
        await full_node_api.wait_transaction_records_entered_mempool(records=txs, timeout=60)
        await full_node_api.process_all_wallet_transactions(wallet_0, timeout=60)
        await full_node_api.wait_for_wallets_synced(wallet_nodes=[wallet_node_0, wallet_node_1], timeout=30)

        await time_out_assert(20, cat_wallet_0.get_confirmed_balance, cat_amt)

        # Create a new standard cat for treasury funds
        new_cat_amt = uint64(1000000)
        new_cat_wallet_dict = await client_0.create_new_cat_and_wallet(new_cat_amt, test=True)
        new_cat_wallet_id = new_cat_wallet_dict["wallet_id"]
        new_cat_wallet = wallet_node_0.wallet_state_manager.wallets[new_cat_wallet_id]

        txs = await wallet_0.wallet_state_manager.tx_store.get_all_unconfirmed()
        await full_node_api.wait_transaction_records_entered_mempool(records=txs, timeout=60)
        await full_node_api.process_all_wallet_transactions(wallet_0, timeout=60)
        await full_node_api.wait_for_wallets_synced(wallet_nodes=[wallet_node_0, wallet_node_1], timeout=30)

        # Create a new standard cat for treasury funds
        new_cat_wallet_dict_2 = await client_0.create_new_cat_and_wallet(new_cat_amt, test=True)
        new_cat_wallet_id_2 = new_cat_wallet_dict_2["wallet_id"]
        new_cat_wallet_2 = wallet_node_0.wallet_state_manager.wallets[new_cat_wallet_id_2]

        txs = await wallet_0.wallet_state_manager.tx_store.get_all_unconfirmed()
        await full_node_api.wait_transaction_records_entered_mempool(records=txs, timeout=60)
        await full_node_api.process_all_wallet_transactions(wallet_0, timeout=60)
        await full_node_api.wait_for_wallets_synced(wallet_nodes=[wallet_node_0, wallet_node_1], timeout=30)

        # join dao
        dao_wallet_res_1 = await client_1.create_new_dao_wallet(
            mode="existing",
            tx_config=DEFAULT_TX_CONFIG,
            treasury_id=treasury_id,
            filter_amount=filter_amount,
            name="DAO WALLET 1",
        )
        dao_id_1 = dao_wallet_res_1.wallet_id

        # fund treasury so there are multiple coins for each asset
        xch_funds = uint64(10000000000)
        for _ in range(4):
            await client_0.dao_add_funds_to_treasury(dao_id_0, 1, uint64(xch_funds / 4), DEFAULT_TX_CONFIG)
            await client_0.dao_add_funds_to_treasury(
                dao_id_0, new_cat_wallet_id, uint64(new_cat_amt / 4), DEFAULT_TX_CONFIG
            )
            await client_0.dao_add_funds_to_treasury(
                dao_id_0, new_cat_wallet_id_2, uint64(new_cat_amt / 4), DEFAULT_TX_CONFIG
            )
            txs = await wallet_0.wallet_state_manager.tx_store.get_all_unconfirmed()
            await full_node_api.wait_transaction_records_entered_mempool(records=txs, timeout=60)
            await full_node_api.process_all_wallet_transactions(wallet_0, timeout=60)
            await full_node_api.wait_for_wallets_synced(wallet_nodes=[wallet_node_0, wallet_node_1], timeout=30)

        await rpc_state(20, client_0.dao_get_treasury_balance, [dao_id_0], lambda x: x["balances"]["xch"], xch_funds)
        assert isinstance(new_cat_wallet, CATWallet)
        new_cat_asset_id = new_cat_wallet.cat_info.limitations_program_hash
        assert isinstance(new_cat_wallet_2, CATWallet)
        new_cat_asset_id_2 = new_cat_wallet_2.cat_info.limitations_program_hash
        await rpc_state(
            20,
            client_0.dao_get_treasury_balance,
            [dao_id_0],
            lambda x: x["balances"][new_cat_asset_id.hex()],
            new_cat_amt,
        )
        await rpc_state(
            20,
            client_0.dao_get_treasury_balance,
            [dao_id_0],
            lambda x: x["balances"][new_cat_asset_id_2.hex()],
            new_cat_amt,
        )

        # add the new cat wallets to wallet_1
        await client_1.create_wallet_for_existing_cat(new_cat_asset_id)
        await client_1.create_wallet_for_existing_cat(new_cat_asset_id_2)

        # send cats to lockup
        await client_0.dao_send_to_lockup(dao_id_0, cat_amt, DEFAULT_TX_CONFIG)

        txs = await wallet_0.wallet_state_manager.tx_store.get_all_unconfirmed()
        await full_node_api.wait_transaction_records_entered_mempool(records=txs, timeout=60)
        await full_node_api.process_all_wallet_transactions(wallet_0, timeout=60)
        await full_node_api.wait_for_wallets_synced(wallet_nodes=[wallet_node_0, wallet_node_1], timeout=30)

        # Test spend proposal types

        # Test proposal with multiple conditions and xch coins
        additions = [
            {"puzzle_hash": ph_0.hex(), "amount": xch_funds / 4},
            {"puzzle_hash": ph_1.hex(), "amount": xch_funds / 4},
        ]
        await client_0.dao_create_proposal(
            wallet_id=dao_id_0,
            proposal_type="spend",
            tx_config=DEFAULT_TX_CONFIG,
            additions=additions,
            vote_amount=cat_amt,
        )
        txs = await wallet_0.wallet_state_manager.tx_store.get_all_unconfirmed()
        await full_node_api.wait_transaction_records_entered_mempool(records=txs, timeout=60)
        await full_node_api.process_all_wallet_transactions(wallet_0, timeout=60)
        await full_node_api.wait_for_wallets_synced(wallet_nodes=[wallet_node_0, wallet_node_1], timeout=30)

        props = await client_1.dao_get_proposals(dao_id_1)
        proposal_id_hex = props["proposals"][-1]["proposal_id"]

        await client_0.dao_close_proposal(
            wallet_id=dao_id_0, proposal_id=proposal_id_hex, tx_config=DEFAULT_TX_CONFIG, self_destruct=False
        )
        txs = await wallet_0.wallet_state_manager.tx_store.get_all_unconfirmed()
        await full_node_api.wait_transaction_records_entered_mempool(records=txs, timeout=60)
        await full_node_api.process_all_wallet_transactions(wallet_0, timeout=60)
        await full_node_api.wait_for_wallets_synced(wallet_nodes=[wallet_node_0, wallet_node_1], timeout=30)

        # check proposal is closed
        await rpc_state(20, client_0.dao_get_proposals, [dao_id_0], lambda x: x["proposals"][-1]["closed"], True)
        await rpc_state(20, client_1.dao_get_proposals, [dao_id_1], lambda x: x["proposals"][-1]["closed"], True)
        # check the xch is received and removed from treasury
        await rpc_state(
            20,
            client_1.get_wallet_balance,
            [wallet_1.id()],
            lambda x: x["confirmed_wallet_balance"],
            initial_funds + (xch_funds / 4),
        )
        await rpc_state(
            20,
            client_0.dao_get_treasury_balance,
            [dao_id_0],
            lambda x: x["balances"]["xch"],
            xch_funds / 2,
        )

        # Test proposal with multiple cats and multiple coins
        cat_spend_amt = 510000
        additions = [
            {"puzzle_hash": ph_0.hex(), "amount": cat_spend_amt, "asset_id": new_cat_asset_id.hex()},
            {"puzzle_hash": ph_0.hex(), "amount": cat_spend_amt, "asset_id": new_cat_asset_id_2.hex()},
        ]
        await client_0.dao_create_proposal(
            wallet_id=dao_id_0,
            proposal_type="spend",
            tx_config=DEFAULT_TX_CONFIG,
            additions=additions,
            vote_amount=cat_amt,
        )
        txs = await wallet_0.wallet_state_manager.tx_store.get_all_unconfirmed()
        await full_node_api.wait_transaction_records_entered_mempool(records=txs, timeout=60)
        await full_node_api.process_all_wallet_transactions(wallet_0, timeout=60)
        await full_node_api.wait_for_wallets_synced(wallet_nodes=[wallet_node_0, wallet_node_1], timeout=30)

        props = await client_1.dao_get_proposals(dao_id_1)
        proposal_id_hex = props["proposals"][-1]["proposal_id"]

        await client_0.dao_close_proposal(
            wallet_id=dao_id_0, proposal_id=proposal_id_hex, tx_config=DEFAULT_TX_CONFIG, self_destruct=False
        )
        txs = await wallet_0.wallet_state_manager.tx_store.get_all_unconfirmed()
        await full_node_api.wait_transaction_records_entered_mempool(records=txs, timeout=60)
        await full_node_api.process_all_wallet_transactions(wallet_0, timeout=60)
        await full_node_api.wait_for_wallets_synced(wallet_nodes=[wallet_node_0, wallet_node_1], timeout=30)

        # check proposal is closed
        await rpc_state(20, client_0.dao_get_proposals, [dao_id_0], lambda x: x["proposals"][-1]["closed"], True)
        await rpc_state(20, client_1.dao_get_proposals, [dao_id_1], lambda x: x["proposals"][-1]["closed"], True)

        # check cat balances
        await rpc_state(
            20,
            client_0.dao_get_treasury_balance,
            [dao_id_0],
            lambda x: x["balances"][new_cat_asset_id.hex()],
            new_cat_amt - cat_spend_amt,
        )
        await rpc_state(
            20,
            client_0.dao_get_treasury_balance,
            [dao_id_0],
            lambda x: x["balances"][new_cat_asset_id_2.hex()],
            new_cat_amt - cat_spend_amt,
        )

        await rpc_state(
            20, client_0.get_wallet_balance, [new_cat_wallet_id], lambda x: x["confirmed_wallet_balance"], cat_spend_amt
        )
        await rpc_state(
            20,
            client_0.get_wallet_balance,
            [new_cat_wallet_id_2],
            lambda x: x["confirmed_wallet_balance"],
            cat_spend_amt,
        )

        # Spend remaining balances with multiple outputs

        additions = [
            {"puzzle_hash": ph_0.hex(), "amount": 400000, "asset_id": new_cat_asset_id.hex()},
            {"puzzle_hash": ph_1.hex(), "amount": 90000, "asset_id": new_cat_asset_id.hex()},
            {"puzzle_hash": ph_0.hex(), "amount": 400000, "asset_id": new_cat_asset_id_2.hex()},
            {"puzzle_hash": ph_1.hex(), "amount": 90000, "asset_id": new_cat_asset_id_2.hex()},
            {"puzzle_hash": ph_0.hex(), "amount": xch_funds / 4},
            {"puzzle_hash": ph_1.hex(), "amount": xch_funds / 4},
        ]
        await client_0.dao_create_proposal(
            wallet_id=dao_id_0,
            proposal_type="spend",
            tx_config=DEFAULT_TX_CONFIG,
            additions=additions,
            vote_amount=cat_amt,
        )
        txs = await wallet_0.wallet_state_manager.tx_store.get_all_unconfirmed()
        await full_node_api.wait_transaction_records_entered_mempool(records=txs, timeout=60)
        await full_node_api.process_all_wallet_transactions(wallet_0, timeout=60)
        await full_node_api.wait_for_wallets_synced(wallet_nodes=[wallet_node_0, wallet_node_1], timeout=30)

        props = await client_0.dao_get_proposals(dao_id_0)
        proposal_id_hex = props["proposals"][-1]["proposal_id"]

        await client_0.dao_close_proposal(
            wallet_id=dao_id_0,
            proposal_id=proposal_id_hex,
            tx_config=DEFAULT_TX_CONFIG,
            self_destruct=False,
        )
        txs = await wallet_0.wallet_state_manager.tx_store.get_all_unconfirmed()
        await full_node_api.wait_transaction_records_entered_mempool(records=txs, timeout=60)
        await full_node_api.process_all_wallet_transactions(wallet_0, timeout=60)
        await full_node_api.wait_for_wallets_synced(wallet_nodes=[wallet_node_0, wallet_node_1], timeout=30)

        # check proposal is closed
        await rpc_state(20, client_0.dao_get_proposals, [dao_id_0], lambda x: x["proposals"][-1]["closed"], True)
        await rpc_state(20, client_1.dao_get_proposals, [dao_id_1], lambda x: x["proposals"][-1]["closed"], True)

        # check cat balances
        await rpc_state(
            20,
            client_0.get_wallet_balance,
            [new_cat_wallet_id],
            lambda x: x["confirmed_wallet_balance"],
            cat_spend_amt + 400000,
        )
        await rpc_state(
            20,
            client_0.get_wallet_balance,
            [new_cat_wallet_id_2],
            lambda x: x["confirmed_wallet_balance"],
            cat_spend_amt + 400000,
        )
        await rpc_state(
            20, client_1.get_wallet_balance, [new_cat_wallet_id], lambda x: x["confirmed_wallet_balance"], 90000
        )
        await rpc_state(
            20, client_1.get_wallet_balance, [new_cat_wallet_id_2], lambda x: x["confirmed_wallet_balance"], 90000
        )

        # check xch
        await rpc_state(
            20,
            client_1.get_wallet_balance,
            [wallet_1.id()],
            lambda x: x["confirmed_wallet_balance"],
            initial_funds + (xch_funds / 2),
        )

        # check treasury balances are 0
        await rpc_state(
            20,
            client_1.dao_get_treasury_balance,
            [dao_id_0],
            lambda x: x["balances"]["xch"] + 1,  # add 1 so result isn't 0
            1,
        )
        await rpc_state(
            20,
            client_1.dao_get_treasury_balance,
            [dao_id_0],
            lambda x: x["balances"][new_cat_asset_id.hex()] + 1,  # add 1 so result isn't 0
            1,
        )
        await rpc_state(
            20,
            client_0.dao_get_treasury_balance,
            [dao_id_0],
            lambda x: x["balances"][new_cat_asset_id_2.hex()] + 1,  # add 1 so result isn't 0
            1,
        )

    finally:
        client_0.close()
        client_1.close()
        await client_0.await_closed()
        await client_1.await_closed()


@pytest.mark.limit_consensus_modes(reason="does not depend on consensus rules")
@pytest.mark.parametrize(
    "trusted",
    [True, False],
)
@pytest.mark.anyio
async def test_dao_concurrency(self_hostname: str, three_wallet_nodes: OldSimulatorsAndWallets, trusted: bool) -> None:
    full_nodes, wallets, _ = three_wallet_nodes
    full_node_api = full_nodes[0]
    full_node_server = full_node_api.server
    wallet_node_0, server_0 = wallets[0]
    wallet_node_1, server_1 = wallets[1]
    wallet_node_2, server_2 = wallets[2]
    wallet_0 = wallet_node_0.wallet_state_manager.main_wallet
    wallet_1 = wallet_node_1.wallet_state_manager.main_wallet
    wallet_2 = wallet_node_2.wallet_state_manager.main_wallet
    ph = await wallet_0.get_new_puzzlehash()
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

    await server_0.start_client(PeerInfo(self_hostname, full_node_server.get_port()), None)
    await server_1.start_client(PeerInfo(self_hostname, full_node_server.get_port()), None)
    await server_2.start_client(PeerInfo(self_hostname, full_node_server.get_port()), None)

    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))
    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph_1))
    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph_2))
    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(puzzle_hash_0))

    funds = calculate_pool_reward(uint32(1)) + calculate_base_farmer_reward(uint32(1))

    await time_out_assert(20, wallet_0.get_confirmed_balance, funds)
    await time_out_assert(20, full_node_api.wallet_is_synced, True, wallet_node_0)

    cat_amt = 300000
    dao_rules = DAORules(
        proposal_timelock=uint64(10),
        soft_close_length=uint64(5),
        attendance_required=uint64(1000),  # 10%
        pass_percentage=uint64(5100),  # 51%
        self_destruct_length=uint64(20),
        oracle_spend_delay=uint64(10),
        proposal_minimum_amount=uint64(101),
    )

    async with wallet_0.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
        dao_wallet_0 = await DAOWallet.create_new_dao_and_wallet(
            wallet_node_0.wallet_state_manager, wallet_0, uint64(cat_amt), dao_rules, action_scope
        )

    # Get the full node sim to process the wallet creation spend
    await full_node_api.wait_transaction_records_entered_mempool(
        records=action_scope.side_effects.transactions, timeout=60
    )
    await full_node_api.process_all_wallet_transactions(wallet_0, timeout=60)
    await full_node_api.wait_for_wallets_synced(wallet_nodes=[wallet_node_0, wallet_node_1], timeout=30)

    # get the cat wallets
    cat_wallet_0 = dao_wallet_0.wallet_state_manager.wallets[dao_wallet_0.dao_info.cat_wallet_id]
    await time_out_assert(10, cat_wallet_0.get_confirmed_balance, cat_amt)

    # get the dao_cat wallet
    dao_cat_wallet_0 = dao_wallet_0.wallet_state_manager.wallets[dao_wallet_0.dao_info.dao_cat_wallet_id]

    treasury_id = dao_wallet_0.dao_info.treasury_id

    # Create the other user's wallet from the treasury id
    dao_wallet_1 = await DAOWallet.create_new_dao_wallet_for_existing_dao(
        wallet_node_1.wallet_state_manager, wallet_1, treasury_id
    )
    assert dao_wallet_1.dao_info.treasury_id == treasury_id

    # Create funding spends for xch
    xch_funds = uint64(500000)
    async with dao_wallet_0.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
        await dao_wallet_0.create_add_funds_to_treasury_spend(xch_funds, action_scope)
    await full_node_api.wait_transaction_records_entered_mempool(
        records=action_scope.side_effects.transactions, timeout=60
    )
    await full_node_api.process_all_wallet_transactions(wallet_0, timeout=60)
    await full_node_api.wait_for_wallets_synced(wallet_nodes=[wallet_node_0, wallet_node_1], timeout=30)

    # Check that the funding spend is recognized by both dao wallets
    await time_out_assert(10, dao_wallet_0.get_balance_by_asset_type, xch_funds)

    # Send some dao_cats to wallet_1
    # Get the cat wallets for wallet_1
    cat_wallet_1 = dao_wallet_1.wallet_state_manager.wallets[dao_wallet_1.dao_info.cat_wallet_id]
    dao_cat_wallet_1 = dao_wallet_1.wallet_state_manager.wallets[dao_wallet_1.dao_info.dao_cat_wallet_id]
    assert cat_wallet_1
    assert dao_cat_wallet_1

    # Add a third wallet and check they can find proposal with accurate vote counts
    dao_wallet_2 = await DAOWallet.create_new_dao_wallet_for_existing_dao(
        wallet_node_2.wallet_state_manager, wallet_2, treasury_id
    )
    assert dao_wallet_2.dao_info.treasury_id == treasury_id

    dao_cat_wallet_2 = dao_wallet_2.wallet_state_manager.wallets[dao_wallet_2.dao_info.dao_cat_wallet_id]
    assert dao_cat_wallet_2

    async with cat_wallet_0.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
        await cat_wallet_0.generate_signed_transaction([100000, 100000], [ph_1, ph_2], action_scope)
    await full_node_api.wait_transaction_records_entered_mempool(
        records=action_scope.side_effects.transactions, timeout=60
    )
    await full_node_api.process_all_wallet_transactions(wallet_0, timeout=60)
    await full_node_api.wait_for_wallets_synced(wallet_nodes=[wallet_node_0, wallet_node_1], timeout=30)

    cat_wallet_1 = dao_wallet_1.wallet_state_manager.wallets[dao_wallet_1.dao_info.cat_wallet_id]
    await time_out_assert(10, cat_wallet_1.get_confirmed_balance, 100000)
    cat_wallet_2 = dao_wallet_2.wallet_state_manager.wallets[dao_wallet_2.dao_info.cat_wallet_id]
    await time_out_assert(10, cat_wallet_2.get_confirmed_balance, 100000)
    await time_out_assert(10, cat_wallet_0.get_confirmed_balance, 100000)

    # Create dao cats for voting
    dao_cat_0_bal = await dao_cat_wallet_0.get_votable_balance()
    assert dao_cat_0_bal == 100000
    async with dao_cat_wallet_0.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
        await dao_cat_wallet_0.enter_dao_cat_voting_mode(dao_cat_0_bal, action_scope)
    await full_node_api.wait_transaction_records_entered_mempool(
        records=action_scope.side_effects.transactions, timeout=60
    )
    await full_node_api.process_all_wallet_transactions(wallet_0, timeout=60)
    await full_node_api.wait_for_wallets_synced(wallet_nodes=[wallet_node_0, wallet_node_1], timeout=30)

    # Create a proposal for xch spend
    recipient_puzzle_hash = await wallet_2.get_new_puzzlehash()
    proposal_amount = uint64(10000)
    xch_proposal_inner = generate_simple_proposal_innerpuz(
        treasury_id,
        [recipient_puzzle_hash],
        [proposal_amount],
        [None],
    )
    async with dao_wallet_0.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
        await dao_wallet_0.generate_new_proposal(xch_proposal_inner, action_scope, dao_cat_0_bal, uint64(1000))
    await full_node_api.wait_transaction_records_entered_mempool(
        records=action_scope.side_effects.transactions, timeout=60
    )
    await full_node_api.process_all_wallet_transactions(wallet_0, timeout=60)
    await full_node_api.wait_for_wallets_synced(wallet_nodes=[wallet_node_0, wallet_node_1], timeout=30)

    # Check the proposal is saved
    assert len(dao_wallet_0.dao_info.proposals_list) == 1
    assert dao_wallet_0.dao_info.proposals_list[0].amount_voted == dao_cat_0_bal
    assert dao_wallet_0.dao_info.proposals_list[0].timer_coin is not None

    # Check that wallet_1 also finds and saved the proposal
    assert len(dao_wallet_1.dao_info.proposals_list) == 1
    prop = dao_wallet_1.dao_info.proposals_list[0]

    total_votes = dao_cat_0_bal

    assert dao_wallet_0.dao_info.proposals_list[0].amount_voted == total_votes
    assert dao_wallet_0.dao_info.proposals_list[0].yes_votes == total_votes
    assert dao_wallet_1.dao_info.proposals_list[0].amount_voted == total_votes
    assert dao_wallet_1.dao_info.proposals_list[0].yes_votes == total_votes

    # Create votable dao cats and add a new vote
    dao_cat_1_bal = await dao_cat_wallet_1.get_votable_balance()
    async with dao_cat_wallet_1.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
        await dao_cat_wallet_1.enter_dao_cat_voting_mode(dao_cat_1_bal, action_scope)
    await full_node_api.wait_transaction_records_entered_mempool(
        records=action_scope.side_effects.transactions, timeout=60
    )
    await full_node_api.process_all_wallet_transactions(wallet_1, timeout=60)
    await full_node_api.wait_for_wallets_synced(wallet_nodes=[wallet_node_0, wallet_node_1, wallet_node_2], timeout=30)

    async with dao_cat_wallet_2.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
        await dao_cat_wallet_2.enter_dao_cat_voting_mode(dao_cat_1_bal, action_scope)
    await full_node_api.wait_transaction_records_entered_mempool(
        records=action_scope.side_effects.transactions, timeout=60
    )
    await full_node_api.process_all_wallet_transactions(wallet_2, timeout=60)
    await full_node_api.wait_for_wallets_synced(wallet_nodes=[wallet_node_0, wallet_node_1, wallet_node_2], timeout=30)

    async with dao_wallet_1.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
        await dao_wallet_1.generate_proposal_vote_spend(prop.proposal_id, dao_cat_1_bal, True, action_scope)
    [vote_tx] = action_scope.side_effects.transactions
    vote_sb = vote_tx.spend_bundle
    assert vote_sb is not None
    async with dao_wallet_2.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
        await dao_wallet_2.generate_proposal_vote_spend(prop.proposal_id, dao_cat_1_bal, True, action_scope)
    [vote_tx_2] = action_scope.side_effects.transactions
    vote_2 = vote_tx_2.spend_bundle
    assert vote_2 is not None
    await time_out_assert_not_none(5, full_node_api.full_node.mempool_manager.get_spendbundle, vote_sb.name())
    await time_out_assert_not_none(5, full_node_api.full_node.mempool_manager.get_spendbundle, vote_2.name())

    await time_out_assert(20, len, 1, dao_wallet_2.dao_info.proposals_list)
    await time_out_assert(20, int, total_votes, dao_wallet_1.dao_info.proposals_list[0].amount_voted)
    await time_out_assert(20, int, total_votes, dao_wallet_2.dao_info.proposals_list[0].amount_voted)

    await full_node_api.process_all_wallet_transactions(wallet_1, timeout=60)
    await full_node_api.wait_for_wallets_synced(wallet_nodes=[wallet_node_0, wallet_node_1, wallet_node_2], timeout=30)

    await time_out_assert(20, int, total_votes * 2, dao_wallet_1.dao_info.proposals_list[0].amount_voted)
    await time_out_assert(20, int, total_votes * 2, dao_wallet_2.dao_info.proposals_list[0].amount_voted)
    dao_cat_1_bal = await dao_cat_wallet_1.get_votable_balance(prop.proposal_id)
    dao_cat_2_bal = await dao_cat_wallet_2.get_votable_balance(prop.proposal_id)

    assert (dao_cat_1_bal == 100000 and dao_cat_2_bal == 0) or (dao_cat_1_bal == 0 and dao_cat_2_bal == 100000)


@pytest.mark.limit_consensus_modes(reason="does not depend on consensus rules")
@pytest.mark.parametrize(
    "trusted",
    [True, False],
)
@pytest.mark.anyio
@pytest.mark.standard_block_tools
async def test_dao_cat_exits(
    two_wallet_nodes_services: SimulatorsAndWalletsServices, trusted: bool, self_hostname: str
) -> None:
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

    await server_0.start_client(PeerInfo(self_hostname, full_node_server.get_port()), None)
    await server_1.start_client(PeerInfo(self_hostname, full_node_server.get_port()), None)

    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph_0))
    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph_1))
    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(puzzle_hash_0))

    initial_funds = calculate_pool_reward(uint32(1)) + calculate_base_farmer_reward(uint32(1))

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
        cat_amt = uint64(150000)
        dao_rules = DAORules(
            proposal_timelock=uint64(8),
            soft_close_length=uint64(4),
            attendance_required=uint64(1000),  # 10%
            pass_percentage=uint64(5100),  # 51%
            self_destruct_length=uint64(20),
            oracle_spend_delay=uint64(10),
            proposal_minimum_amount=uint64(1),
        )
        filter_amount = uint64(1)
        fee = uint64(10000)

        # create new dao
        await full_node_api.wait_for_wallets_synced(wallet_nodes=[wallet_node_0, wallet_node_1], timeout=30)
        dao_wallet_res_0 = await client_0.create_new_dao_wallet(
            mode="new",
            tx_config=DEFAULT_TX_CONFIG,
            dao_rules=dao_rules.to_json_dict(),
            amount_of_cats=cat_amt,
            filter_amount=filter_amount,
            name="DAO WALLET 0",
        )
        dao_id_0 = dao_wallet_res_0.wallet_id
        cat_wallet_0 = wallet_node_0.wallet_state_manager.wallets[dao_wallet_res_0.cat_wallet_id]
        dao_cat_wallet_0 = wallet_node_0.wallet_state_manager.wallets[dao_wallet_res_0.dao_cat_wallet_id]
        txs = await wallet_0.wallet_state_manager.tx_store.get_all_unconfirmed()
        await full_node_api.wait_transaction_records_entered_mempool(records=txs, timeout=60)
        await full_node_api.process_transaction_records(records=txs, timeout=60)
        await full_node_api.process_all_wallet_transactions(wallet_0, 60)
        await full_node_api.wait_for_wallets_synced(wallet_nodes=[wallet_node_0, wallet_node_1], timeout=30)
        await full_node_api.check_transactions_confirmed(wallet_node_0.wallet_state_manager, txs, 60)
        await time_out_assert(60, cat_wallet_0.get_confirmed_balance, cat_amt)

        # fund treasury
        xch_funds = uint64(10000000000)
        funding_tx = await client_0.dao_add_funds_to_treasury(dao_id_0, 1, xch_funds, DEFAULT_TX_CONFIG)
        tx = funding_tx.tx
        await full_node_api.wait_transaction_records_entered_mempool(records=[tx], timeout=60)
        await full_node_api.process_all_wallet_transactions(wallet_0, timeout=60)
        await full_node_api.wait_for_wallets_synced(wallet_nodes=[wallet_node_0, wallet_node_1], timeout=30)

        await rpc_state(20, client_0.dao_get_treasury_balance, [dao_id_0], lambda x: x["balances"]["xch"], xch_funds)

        # send cats to lockup
        lockup_0 = await client_0.dao_send_to_lockup(dao_id_0, cat_amt, DEFAULT_TX_CONFIG)
        txs = lockup_0.txs
        await full_node_api.wait_transaction_records_entered_mempool(records=txs, timeout=60)
        await full_node_api.process_all_wallet_transactions(wallet_0, timeout=60)
        await full_node_api.wait_for_wallets_synced(wallet_nodes=[wallet_node_0, wallet_node_1], timeout=30)

        assert isinstance(dao_cat_wallet_0, DAOCATWallet)
        await time_out_assert(60, dao_cat_wallet_0.get_confirmed_balance, cat_amt)

        # create a spend proposal
        additions = [
            {"puzzle_hash": ph_1.hex(), "amount": 1000},
        ]
        proposal = await client_0.dao_create_proposal(
            wallet_id=dao_id_0,
            proposal_type="spend",
            tx_config=DEFAULT_TX_CONFIG,
            additions=additions,
            vote_amount=cat_amt,
            fee=fee,
        )
        tx = proposal.tx
        await full_node_api.wait_transaction_records_entered_mempool(records=[tx], timeout=60)
        await full_node_api.process_all_wallet_transactions(wallet_0, timeout=60)
        await full_node_api.wait_for_wallets_synced(wallet_nodes=[wallet_node_0, wallet_node_1], timeout=30)

        await time_out_assert_not_none(20, client_0.dao_get_proposals, dao_id_0)
        props = await client_0.dao_get_proposals(dao_id_0)
        proposal_id_hex = props["proposals"][0]["proposal_id"]

        # check proposal state and farm enough blocks to pass
        state = await client_0.dao_get_proposal_state(wallet_id=dao_id_0, proposal_id=proposal_id_hex)
        assert state["success"]
        assert state["state"]["passed"]

        for _ in range(state["state"]["blocks_needed"] + 1):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(puzzle_hash_0))
        await full_node_api.wait_for_wallets_synced(wallet_nodes=[wallet_node_0, wallet_node_1], timeout=30)

        state = await client_0.dao_get_proposal_state(wallet_id=dao_id_0, proposal_id=proposal_id_hex)
        assert state["success"]
        assert state["state"]["closable"]

        # close the proposal
        close = await client_0.dao_close_proposal(
            wallet_id=dao_id_0, proposal_id=proposal_id_hex, tx_config=DEFAULT_TX_CONFIG, self_destruct=False, fee=fee
        )
        tx = close.tx
        await full_node_api.wait_transaction_records_entered_mempool(records=[tx], timeout=60)
        await full_node_api.process_all_wallet_transactions(wallet_0, timeout=60)
        await full_node_api.wait_for_wallets_synced(wallet_nodes=[wallet_node_0, wallet_node_1], timeout=30)

        # check proposal is closed
        await rpc_state(20, client_0.dao_get_proposals, [dao_id_0], lambda x: x["proposals"][0]["closed"], True)

        # free locked cats from finished proposal
        res = await client_0.dao_free_coins_from_finished_proposals(wallet_id=dao_id_0, tx_config=DEFAULT_TX_CONFIG)
        tx = res.tx
        await full_node_api.wait_transaction_records_entered_mempool(records=[tx], timeout=60)
        await full_node_api.process_all_wallet_transactions(wallet_0, timeout=60)
        await full_node_api.wait_for_wallets_synced(wallet_nodes=[wallet_node_0, wallet_node_1], timeout=30)

        assert isinstance(dao_cat_wallet_0, DAOCATWallet)
        assert dao_cat_wallet_0.dao_cat_info.locked_coins[0].active_votes == []

        exit = await client_0.dao_exit_lockup(dao_id_0, DEFAULT_TX_CONFIG)
        exit_tx = exit.tx
        await full_node_api.wait_transaction_records_entered_mempool(records=[exit_tx], timeout=60)
        await full_node_api.process_all_wallet_transactions(wallet_0, timeout=60)
        await full_node_api.wait_for_wallets_synced(wallet_nodes=[wallet_node_0, wallet_node_1], timeout=30)

        await time_out_assert(20, dao_cat_wallet_0.get_confirmed_balance, 0)
        await time_out_assert(20, cat_wallet_0.get_confirmed_balance, cat_amt)

    finally:
        client_0.close()
        client_1.close()
        await client_0.await_closed()
        await client_1.await_closed()


@pytest.mark.limit_consensus_modes(reason="does not depend on consensus rules")
@pytest.mark.parametrize(
    "trusted",
    [True, False],
)
@pytest.mark.anyio
async def test_dao_reorgs(self_hostname: str, two_wallet_nodes: OldSimulatorsAndWallets, trusted: bool) -> None:
    full_nodes, wallets, _ = two_wallet_nodes
    full_node_api = full_nodes[0]
    full_node_server = full_node_api.server
    wallet_node_0, server_0 = wallets[0]
    wallet_node_1, server_1 = wallets[1]
    wallet_0 = wallet_node_0.wallet_state_manager.main_wallet
    wallet_1 = wallet_node_1.wallet_state_manager.main_wallet
    ph = await wallet_0.get_new_puzzlehash()
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

    await server_0.start_client(PeerInfo(self_hostname, full_node_server.get_port()), None)
    await server_1.start_client(PeerInfo(self_hostname, full_node_server.get_port()), None)

    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))
    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph_1))
    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(puzzle_hash_0))

    funds = calculate_pool_reward(uint32(1)) + calculate_base_farmer_reward(uint32(1))

    await time_out_assert(20, wallet_0.get_confirmed_balance, funds)
    await time_out_assert(20, full_node_api.wallet_is_synced, True, wallet_node_0)

    cat_amt = 300000
    dao_rules = DAORules(
        proposal_timelock=uint64(5),
        soft_close_length=uint64(2),
        attendance_required=uint64(1000),  # 10%
        pass_percentage=uint64(5100),  # 51%
        self_destruct_length=uint64(5),
        oracle_spend_delay=uint64(2),
        proposal_minimum_amount=uint64(101),
    )

    async with wallet_0.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
        dao_wallet_0 = await DAOWallet.create_new_dao_and_wallet(
            wallet_node_0.wallet_state_manager, wallet_0, uint64(cat_amt), dao_rules, action_scope
        )

    # Get the full node sim to process the wallet creation spend
    await full_node_api.wait_transaction_records_entered_mempool(
        records=action_scope.side_effects.transactions, timeout=60
    )
    await full_node_api.process_all_wallet_transactions(wallet_0, timeout=60)
    await full_node_api.wait_for_wallets_synced(wallet_nodes=[wallet_node_0, wallet_node_1], timeout=30)

    await time_out_assert(60, dao_wallet_0.get_confirmed_balance, uint128(1))

    # Test Reorg on creation
    height = full_node_api.full_node.blockchain.get_peak_height()
    assert height is not None
    await full_node_api.reorg_from_index_to_new_index(
        ReorgProtocol(uint32(height - 2), uint32(height + 1), puzzle_hash_0, None)
    )

    assert dao_wallet_0.dao_info.current_treasury_coin
    await time_out_assert(60, dao_wallet_0.get_confirmed_balance, uint128(1))

    # get the cat wallets
    cat_wallet_0 = dao_wallet_0.wallet_state_manager.wallets[dao_wallet_0.dao_info.cat_wallet_id]
    await time_out_assert(10, cat_wallet_0.get_confirmed_balance, cat_amt)

    # get the dao_cat wallet
    dao_cat_wallet_0 = dao_wallet_0.wallet_state_manager.wallets[dao_wallet_0.dao_info.dao_cat_wallet_id]

    treasury_id = dao_wallet_0.dao_info.treasury_id

    # Create the other user's wallet from the treasury id
    dao_wallet_1 = await DAOWallet.create_new_dao_wallet_for_existing_dao(
        wallet_node_1.wallet_state_manager, wallet_1, treasury_id
    )
    assert dao_wallet_1.dao_info.treasury_id == treasury_id

    # Create funding spends for xch
    xch_funds = uint64(500000)
    async with dao_wallet_0.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
        await dao_wallet_0.create_add_funds_to_treasury_spend(
            xch_funds,
            action_scope,
        )
    await full_node_api.wait_transaction_records_entered_mempool(
        records=action_scope.side_effects.transactions, timeout=60
    )
    await full_node_api.process_all_wallet_transactions(wallet_0, timeout=60)
    await full_node_api.wait_for_wallets_synced(wallet_nodes=[wallet_node_0, wallet_node_1], timeout=30)

    # Check that the funding spend is recognized by both dao wallets
    await time_out_assert(20, dao_wallet_0.get_balance_by_asset_type, xch_funds)
    await time_out_assert(20, dao_wallet_1.get_balance_by_asset_type, xch_funds)

    # Reorg funding spend
    height = full_node_api.full_node.blockchain.get_peak_height()
    assert height is not None
    await full_node_api.reorg_from_index_to_new_index(
        ReorgProtocol(uint32(height - 1), uint32(height + 1), puzzle_hash_0, None)
    )
    await time_out_assert(20, dao_wallet_0.get_balance_by_asset_type, xch_funds)
    await time_out_assert(20, dao_wallet_1.get_balance_by_asset_type, xch_funds)

    # Send some dao_cats to wallet_1
    # Get the cat wallets for wallet_1
    cat_wallet_1 = dao_wallet_1.wallet_state_manager.wallets[dao_wallet_1.dao_info.cat_wallet_id]
    dao_cat_wallet_1 = dao_wallet_1.wallet_state_manager.wallets[dao_wallet_1.dao_info.dao_cat_wallet_id]
    assert cat_wallet_1
    assert dao_cat_wallet_1

    async with cat_wallet_0.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
        await cat_wallet_0.generate_signed_transaction(
            [100000],
            [ph_1],
            action_scope,
        )
    await full_node_api.wait_transaction_records_entered_mempool(
        records=action_scope.side_effects.transactions, timeout=60
    )
    await full_node_api.process_all_wallet_transactions(wallet_0, timeout=60)
    await full_node_api.wait_for_wallets_synced(wallet_nodes=[wallet_node_0, wallet_node_1], timeout=30)

    cat_wallet_1 = dao_wallet_1.wallet_state_manager.wallets[dao_wallet_1.dao_info.cat_wallet_id]
    await time_out_assert(20, cat_wallet_1.get_confirmed_balance, 100000)

    # Create dao cats for voting
    dao_cat_0_bal = await dao_cat_wallet_0.get_votable_balance()
    assert dao_cat_0_bal == 200000
    async with dao_cat_wallet_0.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
        await dao_cat_wallet_0.enter_dao_cat_voting_mode(dao_cat_0_bal, action_scope)
    await full_node_api.wait_transaction_records_entered_mempool(
        records=action_scope.side_effects.transactions, timeout=60
    )
    await full_node_api.process_all_wallet_transactions(wallet_0, timeout=60)
    await full_node_api.wait_for_wallets_synced(wallet_nodes=[wallet_node_0, wallet_node_1], timeout=30)

    # Create a proposal for xch spend
    recipient_puzzle_hash = await wallet_0.get_new_puzzlehash()
    proposal_amount = uint64(10000)
    xch_proposal_inner = generate_simple_proposal_innerpuz(
        treasury_id,
        [recipient_puzzle_hash],
        [proposal_amount],
        [None],
    )
    async with dao_wallet_0.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
        await dao_wallet_0.generate_new_proposal(xch_proposal_inner, action_scope, dao_cat_0_bal, uint64(1000))
    await full_node_api.wait_transaction_records_entered_mempool(
        records=action_scope.side_effects.transactions, timeout=60
    )
    await full_node_api.process_all_wallet_transactions(wallet_0, timeout=60)
    await full_node_api.wait_for_wallets_synced(wallet_nodes=[wallet_node_0, wallet_node_1], timeout=30)

    # Check the proposal is saved
    assert len(dao_wallet_0.dao_info.proposals_list) == 1
    assert dao_wallet_0.dao_info.proposals_list[0].amount_voted == dao_cat_0_bal
    assert dao_wallet_0.dao_info.proposals_list[0].timer_coin is not None

    # Reorg proposal creation
    height = full_node_api.full_node.blockchain.get_peak_height()
    assert height is not None
    await full_node_api.reorg_from_index_to_new_index(
        ReorgProtocol(uint32(height - 1), uint32(height + 1), puzzle_hash_0, None)
    )
    assert len(dao_wallet_0.dao_info.proposals_list) == 1
    assert dao_wallet_0.dao_info.proposals_list[0].amount_voted == dao_cat_0_bal
    assert dao_wallet_0.dao_info.proposals_list[0].timer_coin is not None

    # Check that wallet_1 also finds and saved the proposal
    assert len(dao_wallet_1.dao_info.proposals_list) == 1
    prop = dao_wallet_1.dao_info.proposals_list[0]

    total_votes = dao_cat_0_bal

    assert dao_wallet_0.dao_info.proposals_list[0].amount_voted == total_votes
    assert dao_wallet_0.dao_info.proposals_list[0].yes_votes == total_votes
    assert dao_wallet_1.dao_info.proposals_list[0].amount_voted == total_votes
    assert dao_wallet_1.dao_info.proposals_list[0].yes_votes == total_votes

    # Create votable dao cats and add a new vote
    dao_cat_1_bal = await dao_cat_wallet_1.get_votable_balance()
    async with dao_cat_wallet_1.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
        await dao_cat_wallet_1.enter_dao_cat_voting_mode(dao_cat_1_bal, action_scope)
    await full_node_api.wait_transaction_records_entered_mempool(
        records=action_scope.side_effects.transactions, timeout=60
    )
    await full_node_api.process_all_wallet_transactions(wallet_1, timeout=60)
    await full_node_api.wait_for_wallets_synced(wallet_nodes=[wallet_node_0, wallet_node_1], timeout=30)

    async with dao_cat_wallet_1.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
        await dao_wallet_1.generate_proposal_vote_spend(prop.proposal_id, dao_cat_1_bal, True, action_scope)
    await full_node_api.wait_transaction_records_entered_mempool(
        records=action_scope.side_effects.transactions, timeout=60
    )
    await full_node_api.process_all_wallet_transactions(wallet_1, timeout=60)
    await full_node_api.wait_for_wallets_synced(wallet_nodes=[wallet_node_0, wallet_node_1], timeout=30)

    assert dao_wallet_0.dao_info.proposals_list[0].amount_voted == dao_cat_0_bal + dao_cat_1_bal
    assert dao_wallet_0.dao_info.proposals_list[0].yes_votes == dao_cat_0_bal + dao_cat_1_bal
    assert dao_wallet_1.dao_info.proposals_list[0].amount_voted == dao_cat_0_bal + dao_cat_1_bal
    assert dao_wallet_1.dao_info.proposals_list[0].yes_votes == dao_cat_0_bal + dao_cat_1_bal

    # Reorg on vote spend
    height = full_node_api.full_node.blockchain.get_peak_height()
    assert height is not None
    await full_node_api.reorg_from_index_to_new_index(
        ReorgProtocol(uint32(height - 1), uint32(height + 1), puzzle_hash_0, None)
    )
    assert dao_wallet_0.dao_info.proposals_list[0].amount_voted == dao_cat_0_bal + dao_cat_1_bal
    assert dao_wallet_0.dao_info.proposals_list[0].yes_votes == dao_cat_0_bal + dao_cat_1_bal
    assert dao_wallet_1.dao_info.proposals_list[0].amount_voted == dao_cat_0_bal + dao_cat_1_bal
    assert dao_wallet_1.dao_info.proposals_list[0].yes_votes == dao_cat_0_bal + dao_cat_1_bal

    # Close proposal
    for i in range(5):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(puzzle_hash_0))
    await full_node_api.wait_for_wallets_synced(wallet_nodes=[wallet_node_0, wallet_node_1], timeout=30)

    async with dao_wallet_0.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
        await dao_wallet_0.create_proposal_close_spend(prop.proposal_id, action_scope, fee=uint64(100))
    await full_node_api.wait_transaction_records_entered_mempool(
        records=action_scope.side_effects.transactions, timeout=60
    )
    await full_node_api.process_all_wallet_transactions(wallet_0, timeout=60)
    await full_node_api.wait_for_wallets_synced(wallet_nodes=[wallet_node_0, wallet_node_1], timeout=30)

    await time_out_assert(20, get_proposal_state, (True, True), *[dao_wallet_0, 0])
    await time_out_assert(20, get_proposal_state, (True, True), *[dao_wallet_1, 0])

    # Reorg closed proposal
    height = full_node_api.full_node.blockchain.get_peak_height()
    assert height is not None
    await full_node_api.reorg_from_index_to_new_index(
        ReorgProtocol(uint32(height - 1), uint32(height + 1), puzzle_hash_0, None)
    )
    await full_node_api.wait_for_wallets_synced(wallet_nodes=[wallet_node_0, wallet_node_1], timeout=30)
    await time_out_assert(20, get_proposal_state, (True, True), *[dao_wallet_0, 0])
    await time_out_assert(20, get_proposal_state, (True, True), *[dao_wallet_1, 0])


@pytest.mark.limit_consensus_modes(reason="does not depend on consensus rules")
@pytest.mark.parametrize(
    "trusted",
    [True, False],
)
@pytest.mark.anyio
async def test_dao_votes(self_hostname: str, three_wallet_nodes: OldSimulatorsAndWallets, trusted: bool) -> None:
    full_nodes, wallets, _ = three_wallet_nodes
    full_node_api = full_nodes[0]
    full_node_server = full_node_api.server
    wallet_node_0, server_0 = wallets[0]
    wallet_node_1, server_1 = wallets[1]
    wallet_node_2, server_2 = wallets[2]
    wallet_0 = wallet_node_0.wallet_state_manager.main_wallet
    wallet_1 = wallet_node_1.wallet_state_manager.main_wallet
    wallet_2 = wallet_node_2.wallet_state_manager.main_wallet
    ph_0 = await wallet_0.get_new_puzzlehash()
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

    await server_0.start_client(PeerInfo(self_hostname, full_node_server.get_port()), None)
    await server_1.start_client(PeerInfo(self_hostname, full_node_server.get_port()), None)
    await server_2.start_client(PeerInfo(self_hostname, full_node_server.get_port()), None)

    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph_0))
    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph_1))
    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph_2))
    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(puzzle_hash_0))

    funds = calculate_pool_reward(uint32(1)) + calculate_base_farmer_reward(uint32(1))

    await time_out_assert(20, wallet_0.get_confirmed_balance, funds)
    await time_out_assert(20, full_node_api.wallet_is_synced, True, wallet_node_0)

    # set a standard fee amount to use in all txns
    base_fee = uint64(100)

    # set the cat issuance and DAO rules
    cat_issuance = 300000
    proposal_min_amt = uint64(101)
    dao_rules = DAORules(
        proposal_timelock=uint64(10),
        soft_close_length=uint64(5),
        attendance_required=uint64(190000),
        pass_percentage=uint64(5100),  # 51%
        self_destruct_length=uint64(20),
        oracle_spend_delay=uint64(10),
        proposal_minimum_amount=proposal_min_amt,
    )

    async with wallet_0.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
        dao_wallet_0 = await DAOWallet.create_new_dao_and_wallet(
            wallet_node_0.wallet_state_manager,
            wallet_0,
            uint64(cat_issuance),
            dao_rules,
            action_scope,
        )

    await full_node_api.wait_transaction_records_entered_mempool(
        records=action_scope.side_effects.transactions, timeout=60
    )
    await full_node_api.process_all_wallet_transactions(wallet_0, timeout=60)
    await full_node_api.wait_for_wallets_synced(wallet_nodes=[wallet_node_0, wallet_node_1], timeout=30)

    cat_wallet_0 = dao_wallet_0.wallet_state_manager.wallets[dao_wallet_0.dao_info.cat_wallet_id]
    dao_cat_wallet_0 = dao_wallet_0.wallet_state_manager.wallets[dao_wallet_0.dao_info.dao_cat_wallet_id]
    await time_out_assert(10, cat_wallet_0.get_confirmed_balance, cat_issuance)
    assert dao_cat_wallet_0

    treasury_id = dao_wallet_0.dao_info.treasury_id

    dc_1 = uint64(100000)
    dc_2 = uint64(50000)
    dc_3 = uint64(30000)
    dc_4 = uint64(20000)
    dc_5 = uint64(10000)

    # Lockup voting cats for all wallets
    async with dao_cat_wallet_0.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
        await dao_cat_wallet_0.enter_dao_cat_voting_mode(dc_1, action_scope, fee=base_fee)
    await full_node_api.wait_transaction_records_entered_mempool(
        records=action_scope.side_effects.transactions, timeout=60
    )
    await full_node_api.process_all_wallet_transactions(wallet_0, timeout=60)
    await full_node_api.wait_for_wallet_synced(wallet_node=wallet_node_0, timeout=30)

    async with dao_cat_wallet_0.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
        await dao_cat_wallet_0.enter_dao_cat_voting_mode(dc_2, action_scope, fee=base_fee)
    await full_node_api.wait_transaction_records_entered_mempool(
        records=action_scope.side_effects.transactions, timeout=60
    )
    await full_node_api.process_all_wallet_transactions(wallet_0, timeout=60)
    await full_node_api.wait_for_wallet_synced(wallet_node=wallet_node_0, timeout=30)

    async with dao_cat_wallet_0.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
        await dao_cat_wallet_0.enter_dao_cat_voting_mode(dc_3, action_scope, fee=base_fee)
    await full_node_api.wait_transaction_records_entered_mempool(
        records=action_scope.side_effects.transactions, timeout=60
    )
    await full_node_api.process_all_wallet_transactions(wallet_0, timeout=60)
    await full_node_api.wait_for_wallet_synced(wallet_node=wallet_node_0, timeout=30)

    async with dao_cat_wallet_0.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
        await dao_cat_wallet_0.enter_dao_cat_voting_mode(dc_4, action_scope, fee=base_fee)
    await full_node_api.wait_transaction_records_entered_mempool(
        records=action_scope.side_effects.transactions, timeout=60
    )
    await full_node_api.process_all_wallet_transactions(wallet_0, timeout=60)
    await full_node_api.wait_for_wallet_synced(wallet_node=wallet_node_0, timeout=30)

    async with dao_cat_wallet_0.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
        await dao_cat_wallet_0.enter_dao_cat_voting_mode(dc_5, action_scope, fee=base_fee)
    await full_node_api.wait_transaction_records_entered_mempool(
        records=action_scope.side_effects.transactions, timeout=60
    )
    await full_node_api.process_all_wallet_transactions(wallet_0, timeout=60)
    await full_node_api.wait_for_wallet_synced(wallet_node=wallet_node_0, timeout=30)

    await time_out_assert(10, dao_cat_wallet_0.get_confirmed_balance, dc_1 + dc_2 + dc_3 + dc_4 + dc_5)

    # Create funding spend so the treasury holds some XCH
    xch_funds = uint64(500000)
    async with dao_wallet_0.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
        await dao_wallet_0.create_add_funds_to_treasury_spend(xch_funds, action_scope)
    await full_node_api.wait_transaction_records_entered_mempool(
        records=action_scope.side_effects.transactions, timeout=60
    )
    await full_node_api.process_all_wallet_transactions(wallet_0, timeout=60)
    await full_node_api.wait_for_wallet_synced(wallet_node=wallet_node_0, timeout=30)

    # Check that the funding spend is recognized by all wallets
    await time_out_assert(10, dao_wallet_0.get_balance_by_asset_type, xch_funds)

    # Create Proposals
    recipient_puzzle_hash = await wallet_2.get_new_puzzlehash()
    proposal_amount_1 = uint64(9998)
    xch_proposal_inner = generate_simple_proposal_innerpuz(
        treasury_id,
        [recipient_puzzle_hash],
        [proposal_amount_1],
        [None],
    )

    vote_1 = uint64(120000)
    vote_2 = uint64(150000)

    async with dao_wallet_0.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
        await dao_wallet_0.generate_new_proposal(xch_proposal_inner, action_scope, vote_1, fee=base_fee)
    await full_node_api.wait_transaction_records_entered_mempool(
        records=action_scope.side_effects.transactions, timeout=60
    )
    await full_node_api.process_all_wallet_transactions(wallet_0, timeout=60)
    await full_node_api.wait_for_wallet_synced(wallet_node=wallet_node_0, timeout=30)

    assert len(dao_wallet_0.dao_info.proposals_list) == 1
    assert dao_wallet_0.dao_info.proposals_list[0].amount_voted == vote_1
    assert dao_wallet_0.dao_info.proposals_list[0].timer_coin is not None
    prop_0 = dao_wallet_0.dao_info.proposals_list[0]

    async with dao_wallet_0.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
        await dao_wallet_0.generate_new_proposal(xch_proposal_inner, action_scope, vote_2, fee=base_fee)
    await full_node_api.wait_transaction_records_entered_mempool(
        records=action_scope.side_effects.transactions, timeout=60
    )
    await full_node_api.process_all_wallet_transactions(wallet_0, timeout=60)
    await full_node_api.wait_for_wallet_synced(wallet_node=wallet_node_0, timeout=30)

    assert len(dao_wallet_0.dao_info.proposals_list) == 2
    assert dao_wallet_0.dao_info.proposals_list[1].amount_voted == vote_2

    vote_3 = uint64(30000)
    async with dao_wallet_0.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
        await dao_wallet_0.generate_proposal_vote_spend(prop_0.proposal_id, vote_3, True, action_scope)
    await full_node_api.wait_transaction_records_entered_mempool(
        records=action_scope.side_effects.transactions, timeout=60
    )
    await full_node_api.process_all_wallet_transactions(wallet_0, timeout=60)
    await full_node_api.wait_for_wallet_synced(wallet_node=wallet_node_0, timeout=30)

    assert dao_wallet_0.dao_info.proposals_list[0].amount_voted == vote_1 + vote_3

    vote_4 = uint64(60000)
    async with dao_wallet_0.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
        await dao_wallet_0.generate_proposal_vote_spend(prop_0.proposal_id, vote_4, True, action_scope)
    await full_node_api.wait_transaction_records_entered_mempool(
        records=action_scope.side_effects.transactions, timeout=60
    )
    await full_node_api.process_all_wallet_transactions(wallet_0, timeout=60)
    await full_node_api.wait_for_wallet_synced(wallet_node=wallet_node_0, timeout=30)

    assert dao_wallet_0.dao_info.proposals_list[0].amount_voted == vote_1 + vote_3 + vote_4

    vote_5 = uint64(1)
    async with dao_wallet_0.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
        await dao_wallet_0.generate_new_proposal(xch_proposal_inner, action_scope, vote_5, fee=base_fee)
    await full_node_api.wait_transaction_records_entered_mempool(
        records=action_scope.side_effects.transactions, timeout=60
    )
    await full_node_api.process_all_wallet_transactions(wallet_0, timeout=60)
    await full_node_api.wait_for_wallet_synced(wallet_node=wallet_node_0, timeout=30)

    assert len(dao_wallet_0.dao_info.proposals_list) == 3
    assert dao_wallet_0.dao_info.proposals_list[2].amount_voted == vote_5
    prop_2 = dao_wallet_0.dao_info.proposals_list[2]

    vote_6 = uint64(20000)
    for i in range(10):
        async with dao_wallet_0.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
            await dao_wallet_0.generate_proposal_vote_spend(prop_2.proposal_id, vote_6, True, action_scope)
        await full_node_api.wait_transaction_records_entered_mempool(
            records=action_scope.side_effects.transactions, timeout=60
        )
        await full_node_api.process_all_wallet_transactions(wallet_0, timeout=60)
        await full_node_api.wait_for_wallet_synced(wallet_node=wallet_node_0, timeout=30)

    assert dao_wallet_0.dao_info.proposals_list[2].amount_voted == 200001

    async with dao_wallet_0.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
        await dao_wallet_0.create_proposal_close_spend(prop_0.proposal_id, action_scope)
    await full_node_api.wait_transaction_records_entered_mempool(
        records=action_scope.side_effects.transactions, timeout=60
    )
    await full_node_api.process_all_wallet_transactions(wallet_0, timeout=60)
    await full_node_api.wait_for_wallet_synced(wallet_node=wallet_node_0, timeout=30)

    async with dao_wallet_0.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
        await dao_wallet_0.generate_new_proposal(xch_proposal_inner, action_scope, fee=base_fee)
    await full_node_api.wait_transaction_records_entered_mempool(
        records=action_scope.side_effects.transactions, timeout=60
    )
    await full_node_api.process_all_wallet_transactions(wallet_0, timeout=60)
    await full_node_api.wait_for_wallet_synced(wallet_node=wallet_node_0, timeout=30)

    assert dao_wallet_0.dao_info.proposals_list[3].amount_voted == 210000


@pytest.mark.limit_consensus_modes(reason="does not depend on consensus rules")
@pytest.mark.parametrize(
    "trusted",
    [True, False],
)
@pytest.mark.anyio
async def test_dao_resync(self_hostname: str, two_wallet_nodes: OldSimulatorsAndWallets, trusted: bool) -> None:
    full_nodes, wallets, _ = two_wallet_nodes
    full_node_api = full_nodes[0]
    full_node_server = full_node_api.server
    wallet_node_0, server_0 = wallets[0]
    wallet_node_1, server_1 = wallets[1]
    wallet_api_0 = WalletRpcApi(wallet_node_0)
    wallet_api_1 = WalletRpcApi(wallet_node_1)
    wallet_0 = wallet_node_0.wallet_state_manager.main_wallet
    wallet_1 = wallet_node_1.wallet_state_manager.main_wallet
    ph = await wallet_0.get_new_puzzlehash()
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

    await server_0.start_client(PeerInfo(self_hostname, full_node_server.get_port()), None)
    await server_1.start_client(PeerInfo(self_hostname, full_node_server.get_port()), None)

    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))
    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph_1))

    funds = calculate_pool_reward(uint32(1)) + calculate_base_farmer_reward(uint32(1))

    await time_out_assert(20, wallet_0.get_confirmed_balance, funds)
    await time_out_assert(20, full_node_api.wallet_is_synced, True, wallet_node_0)

    cat_amt = 2000
    dao_rules = DAORules(
        proposal_timelock=uint64(10),
        soft_close_length=uint64(5),
        attendance_required=uint64(1000),  # 10%
        pass_percentage=uint64(5100),  # 51%
        self_destruct_length=uint64(20),
        oracle_spend_delay=uint64(10),
        proposal_minimum_amount=uint64(1),
    )

    fee = uint64(10)
    fee_for_cat = uint64(20)
    async with wallet_0.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
        dao_wallet_0 = await DAOWallet.create_new_dao_and_wallet(
            wallet_node_0.wallet_state_manager,
            wallet_0,
            uint64(cat_amt * 2),
            dao_rules,
            action_scope=action_scope,
            fee=fee,
            fee_for_cat=fee_for_cat,
        )

    await full_node_api.wait_transaction_records_entered_mempool(
        records=action_scope.side_effects.transactions, timeout=60
    )
    await full_node_api.process_all_wallet_transactions(wallet_0, timeout=60)
    await full_node_api.wait_for_wallets_synced(wallet_nodes=[wallet_node_0, wallet_node_1], timeout=30)

    treasury_id = dao_wallet_0.dao_info.treasury_id

    # get the cat wallets
    cat_wallet_0 = dao_wallet_0.wallet_state_manager.wallets[dao_wallet_0.dao_info.cat_wallet_id]
    # dao_cat_wallet_0 = dao_wallet_0.wallet_state_manager.wallets[dao_wallet_0.dao_info.dao_cat_wallet_id]

    # Create the other user's wallet from the treasury id
    dao_wallet_1 = await DAOWallet.create_new_dao_wallet_for_existing_dao(
        wallet_node_1.wallet_state_manager, wallet_1, treasury_id
    )
    assert dao_wallet_0.dao_info.treasury_id == dao_wallet_1.dao_info.treasury_id

    # Get the cat wallets for wallet_1
    cat_wallet_1 = dao_wallet_1.wallet_state_manager.wallets[dao_wallet_1.dao_info.cat_wallet_id]

    # Send some cats to the dao_cat lockup
    dao_cat_amt = uint64(100)
    async with dao_wallet_0.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
        await dao_wallet_0.enter_dao_cat_voting_mode(dao_cat_amt, action_scope)

    await full_node_api.wait_transaction_records_entered_mempool(
        records=action_scope.side_effects.transactions, timeout=60
    )
    await full_node_api.process_all_wallet_transactions(wallet_0, timeout=60)
    await full_node_api.wait_for_wallet_synced(wallet_node=wallet_node_0, timeout=30)

    # send some cats from wallet_0 to wallet_1 so we can test voting
    async with cat_wallet_0.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
        await cat_wallet_0.generate_signed_transaction([cat_amt], [ph_1], action_scope)

    await full_node_api.wait_transaction_records_entered_mempool(
        records=action_scope.side_effects.transactions, timeout=60
    )
    await full_node_api.process_all_wallet_transactions(wallet_0, timeout=60)
    await full_node_api.wait_for_wallet_synced(wallet_node=wallet_node_0, timeout=30)

    await time_out_assert(10, cat_wallet_1.get_confirmed_balance, cat_amt)

    recipient_puzzle_hash = await wallet_1.get_new_puzzlehash()
    proposal_amount_1 = uint64(9998)
    xch_proposal_inner = generate_simple_proposal_innerpuz(
        treasury_id,
        [recipient_puzzle_hash],
        [proposal_amount_1],
        [None],
    )
    async with dao_wallet_0.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
        await dao_wallet_0.generate_new_proposal(xch_proposal_inner, action_scope, uint64(10))
    await full_node_api.wait_transaction_records_entered_mempool(
        records=action_scope.side_effects.transactions, timeout=60
    )
    await full_node_api.process_all_wallet_transactions(wallet_0, timeout=60)
    await full_node_api.wait_for_wallets_synced(wallet_nodes=[wallet_node_0, wallet_node_1], timeout=30)

    # make another proposal spending all the dao_cats
    xch_proposal_inner = generate_simple_proposal_innerpuz(
        treasury_id,
        [recipient_puzzle_hash],
        [proposal_amount_1],
        [None],
    )
    async with dao_wallet_0.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
        await dao_wallet_0.generate_new_proposal(xch_proposal_inner, action_scope)
    await full_node_api.wait_transaction_records_entered_mempool(
        records=action_scope.side_effects.transactions, timeout=60
    )
    await full_node_api.process_all_wallet_transactions(wallet_0, timeout=60)
    await full_node_api.wait_for_wallets_synced(wallet_nodes=[wallet_node_0, wallet_node_1], timeout=30)

    # set flag to reset wallet sync data on start
    await wallet_api_0.set_wallet_resync_on_startup({"enable": True})
    fingerprint_0 = wallet_node_0.logged_in_fingerprint
    await wallet_api_1.set_wallet_resync_on_startup({"enable": True})
    fingerprint_1 = wallet_node_1.logged_in_fingerprint
    # Delete tx records
    await wallet_node_0.wallet_state_manager.tx_store.rollback_to_block(0)
    wallet_node_0._close()
    await wallet_node_0._await_closed()
    wallet_node_1._close()
    await wallet_node_1._await_closed()
    wallet_node_0.config["database_path"] = "wallet/db/blockchain_wallet_v2_test_1_CHALLENGE_KEY.sqlite"
    wallet_node_1.config["database_path"] = "wallet/db/blockchain_wallet_v2_test_2_CHALLENGE_KEY.sqlite"
    # Start resync
    await wallet_node_0._start_with_fingerprint(fingerprint_0)
    await wallet_node_1._start_with_fingerprint(fingerprint_1)
    await server_0.start_client(PeerInfo(self_hostname, full_node_server.get_port()), None)
    await server_1.start_client(PeerInfo(self_hostname, full_node_server.get_port()), None)
    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(puzzle_hash_0))
    await full_node_api.wait_for_wallet_synced(wallet_node=wallet_node_0, timeout=20)
    await full_node_api.wait_for_wallet_synced(wallet_node=wallet_node_1, timeout=20)
    wallet_0 = wallet_node_0.wallet_state_manager.main_wallet

    assert len(await wallet_node_0.wallet_state_manager.get_all_wallet_info_entries()) == 1

    new_dao_wallet = await DAOWallet.create_new_dao_wallet_for_existing_dao(
        wallet_node_0.wallet_state_manager,
        wallet_0,
        treasury_id,
    )

    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(puzzle_hash_0))
    await full_node_api.wait_for_wallet_synced(wallet_node=wallet_node_0, timeout=20)
    assert len(await wallet_node_0.wallet_state_manager.get_all_wallet_info_entries()) == 4
    new_cat_wallet = new_dao_wallet.wallet_state_manager.wallets[new_dao_wallet.dao_info.cat_wallet_id]
    new_dao_cat_wallet = new_dao_wallet.wallet_state_manager.wallets[new_dao_wallet.dao_info.dao_cat_wallet_id]

    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(puzzle_hash_0))
    await full_node_api.wait_for_wallet_synced(wallet_node=wallet_node_0, timeout=20)

    # Check the new wallets have the right balances
    await time_out_assert(20, new_cat_wallet.get_confirmed_balance, cat_amt - dao_cat_amt)
    await time_out_assert(20, new_dao_cat_wallet.get_confirmed_balance, dao_cat_amt)

    # Check the proposals are found and accurate
    assert len(new_dao_wallet.dao_info.proposals_list) == 2
    assert new_dao_wallet.dao_info.proposals_list[0].yes_votes == 10
    assert new_dao_wallet.dao_info.proposals_list[1].yes_votes == 100
