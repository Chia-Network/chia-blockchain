from __future__ import annotations

import asyncio
import dataclasses
import json
import logging
import random
from operator import attrgetter
from typing import Any, Dict, List, Optional, Tuple, cast

import aiosqlite
import pytest
from chia_rs import G1Element, G2Element

from chia._tests.conftest import ConsensusMode
from chia._tests.environments.wallet import WalletStateTransition, WalletTestFramework
from chia._tests.util.time_out_assert import time_out_assert, time_out_assert_not_none
from chia._tests.wallet.test_wallet_coin_store import (
    get_coin_records_amount_filter_tests,
    get_coin_records_amount_range_tests,
    get_coin_records_coin_id_filter_tests,
    get_coin_records_coin_type_tests,
    get_coin_records_confirmed_range_tests,
    get_coin_records_include_total_count_tests,
    get_coin_records_mixed_tests,
    get_coin_records_offset_limit_tests,
    get_coin_records_order_tests,
    get_coin_records_parent_coin_id_filter_tests,
    get_coin_records_puzzle_hash_filter_tests,
    get_coin_records_reverse_tests,
    get_coin_records_spent_range_tests,
    get_coin_records_wallet_id_tests,
    get_coin_records_wallet_type_tests,
    record_1,
    record_2,
    record_3,
    record_4,
    record_5,
    record_6,
    record_7,
    record_8,
    record_9,
)
from chia.consensus.block_rewards import calculate_base_farmer_reward, calculate_pool_reward
from chia.consensus.coinbase import create_puzzlehash_for_pk
from chia.rpc.full_node_rpc_client import FullNodeRpcClient
from chia.rpc.rpc_client import ResponseFailureError
from chia.rpc.rpc_server import RpcServer
from chia.rpc.wallet_request_types import (
    CombineCoins,
    DIDGetPubkey,
    GetNotifications,
    SplitCoins,
    SplitCoinsResponse,
    VerifySignature,
    VerifySignatureResponse,
)
from chia.rpc.wallet_rpc_api import WalletRpcApi
from chia.rpc.wallet_rpc_client import WalletRpcClient
from chia.server.server import ChiaServer
from chia.server.start_service import Service
from chia.simulator.full_node_simulator import FullNodeSimulator
from chia.simulator.simulator_protocol import FarmNewBlockProtocol
from chia.types.blockchain_format.coin import Coin, coin_as_list
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_record import CoinRecord
from chia.types.coin_spend import CoinSpend, make_spend
from chia.types.peer_info import PeerInfo
from chia.types.signing_mode import SigningMode
from chia.util.bech32m import decode_puzzle_hash, encode_puzzle_hash
from chia.util.config import load_config, lock_and_load_config, save_config
from chia.util.db_wrapper import DBWrapper2
from chia.util.hash import std_hash
from chia.util.ints import uint16, uint32, uint64
from chia.util.streamable import ConversionError, InvalidTypeError
from chia.wallet.cat_wallet.cat_constants import DEFAULT_CATS
from chia.wallet.cat_wallet.cat_utils import CAT_MOD, construct_cat_puzzle
from chia.wallet.cat_wallet.cat_wallet import CATWallet
from chia.wallet.conditions import (
    ConditionValidTimes,
    CreateCoinAnnouncement,
    CreatePuzzleAnnouncement,
    Remark,
    conditions_to_json_dicts,
)
from chia.wallet.derive_keys import master_sk_to_wallet_sk, master_sk_to_wallet_sk_unhardened
from chia.wallet.did_wallet.did_wallet import DIDWallet
from chia.wallet.nft_wallet.nft_wallet import NFTWallet
from chia.wallet.puzzles.clawback.metadata import AutoClaimSettings
from chia.wallet.signer_protocol import UnsignedTransaction
from chia.wallet.trading.trade_status import TradeStatus
from chia.wallet.transaction_record import TransactionRecord
from chia.wallet.transaction_sorting import SortKey
from chia.wallet.uncurried_puzzle import uncurry_puzzle
from chia.wallet.util.address_type import AddressType
from chia.wallet.util.blind_signer_tl import BLIND_SIGNER_TRANSLATION
from chia.wallet.util.clvm_streamable import byte_deserialize_clvm_streamable
from chia.wallet.util.compute_memos import compute_memos
from chia.wallet.util.query_filter import AmountFilter, HashFilter, TransactionTypeFilter
from chia.wallet.util.transaction_type import TransactionType
from chia.wallet.util.tx_config import DEFAULT_COIN_SELECTION_CONFIG, DEFAULT_TX_CONFIG
from chia.wallet.util.wallet_types import CoinType, WalletType
from chia.wallet.wallet import Wallet
from chia.wallet.wallet_coin_record import WalletCoinRecord
from chia.wallet.wallet_coin_store import GetCoinRecords
from chia.wallet.wallet_node import WalletNode
from chia.wallet.wallet_protocol import WalletProtocol
from chia.wallet.wallet_spend_bundle import WalletSpendBundle

log = logging.getLogger(__name__)


@dataclasses.dataclass
class WalletBundle:
    service: Service
    node: WalletNode
    rpc_client: WalletRpcClient
    wallet: Wallet


@dataclasses.dataclass
class FullNodeBundle:
    server: ChiaServer
    api: FullNodeSimulator
    rpc_client: FullNodeRpcClient


@dataclasses.dataclass
class WalletRpcTestEnvironment:
    wallet_1: WalletBundle
    wallet_2: WalletBundle
    full_node: FullNodeBundle


async def farm_transaction_block(full_node_api: FullNodeSimulator, wallet_node: WalletNode):
    await full_node_api.farm_blocks_to_puzzlehash(count=1)
    await full_node_api.wait_for_wallet_synced(wallet_node=wallet_node, timeout=20)


def check_mempool_spend_count(full_node_api: FullNodeSimulator, num_of_spends):
    return full_node_api.full_node.mempool_manager.mempool.size() == num_of_spends


async def farm_transaction(full_node_api: FullNodeSimulator, wallet_node: WalletNode, spend_bundle: WalletSpendBundle):
    await time_out_assert(
        20, full_node_api.full_node.mempool_manager.get_spendbundle, spend_bundle, spend_bundle.name()
    )
    await farm_transaction_block(full_node_api, wallet_node)
    assert full_node_api.full_node.mempool_manager.get_spendbundle(spend_bundle.name()) is None


async def generate_funds(full_node_api: FullNodeSimulator, wallet_bundle: WalletBundle, num_blocks: int = 1):
    wallet_id = 1
    initial_balances = await wallet_bundle.rpc_client.get_wallet_balance(wallet_id)
    ph: bytes32 = decode_puzzle_hash(await wallet_bundle.rpc_client.get_next_address(wallet_id, True))
    generated_funds = 0
    for i in range(0, num_blocks):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))
        peak_height = full_node_api.full_node.blockchain.get_peak_height()
        assert peak_height is not None
        generated_funds += calculate_pool_reward(peak_height) + calculate_base_farmer_reward(peak_height)

    # Farm a dummy block to confirm the created funds
    await farm_transaction_block(full_node_api, wallet_bundle.node)

    expected_confirmed = initial_balances["confirmed_wallet_balance"] + generated_funds
    expected_unconfirmed = initial_balances["unconfirmed_wallet_balance"] + generated_funds
    await time_out_assert(20, get_confirmed_balance, expected_confirmed, wallet_bundle.rpc_client, wallet_id)
    await time_out_assert(20, get_unconfirmed_balance, expected_unconfirmed, wallet_bundle.rpc_client, wallet_id)
    await time_out_assert(20, wallet_bundle.rpc_client.get_synced)

    return generated_funds


@pytest.fixture(scope="function", params=[True, False])
async def wallet_rpc_environment(two_wallet_nodes_services, request, self_hostname):
    full_node, wallets, bt = two_wallet_nodes_services
    full_node_service = full_node[0]
    full_node_api = full_node_service._api
    full_node_server = full_node_api.full_node.server
    wallet_service = wallets[0]
    wallet_service_2 = wallets[1]
    wallet_node = wallet_service._node
    wallet_node_2 = wallet_service_2._node
    wallet = wallet_node.wallet_state_manager.main_wallet
    wallet_2 = wallet_node_2.wallet_state_manager.main_wallet

    config = bt.config
    hostname = config["self_hostname"]

    if request.param:
        wallet_node.config["trusted_peers"] = {full_node_server.node_id.hex(): full_node_server.node_id.hex()}
        wallet_node_2.config["trusted_peers"] = {full_node_server.node_id.hex(): full_node_server.node_id.hex()}
    else:
        wallet_node.config["trusted_peers"] = {}
        wallet_node_2.config["trusted_peers"] = {}

    await wallet_node.server.start_client(PeerInfo(self_hostname, full_node_server.get_port()), None)
    await wallet_node_2.server.start_client(PeerInfo(self_hostname, full_node_server.get_port()), None)

    async with WalletRpcClient.create_as_context(
        hostname, wallet_service.rpc_server.listen_port, wallet_service.root_path, wallet_service.config
    ) as client:
        async with WalletRpcClient.create_as_context(
            hostname, wallet_service_2.rpc_server.listen_port, wallet_service_2.root_path, wallet_service_2.config
        ) as client_2:
            async with FullNodeRpcClient.create_as_context(
                hostname,
                full_node_service.rpc_server.listen_port,
                full_node_service.root_path,
                full_node_service.config,
            ) as client_node:
                wallet_bundle_1: WalletBundle = WalletBundle(wallet_service, wallet_node, client, wallet)
                wallet_bundle_2: WalletBundle = WalletBundle(wallet_service_2, wallet_node_2, client_2, wallet_2)
                node_bundle: FullNodeBundle = FullNodeBundle(full_node_server, full_node_api, client_node)

                yield WalletRpcTestEnvironment(wallet_bundle_1, wallet_bundle_2, node_bundle)


async def create_tx_outputs(wallet: Wallet, output_args: List[Tuple[int, Optional[List[str]]]]) -> List[Dict[str, Any]]:
    outputs = []
    for args in output_args:
        output = {"amount": uint64(args[0]), "puzzle_hash": await wallet.get_new_puzzlehash()}
        if args[1] is not None:
            assert len(args[1]) > 0
            output["memos"] = args[1]
        outputs.append(output)
    return outputs


async def assert_wallet_types(client: WalletRpcClient, expected: Dict[WalletType, int]) -> None:
    for wallet_type in WalletType:
        wallets = await client.get_wallets(wallet_type)
        wallet_count = len(wallets)
        if wallet_type in expected:
            assert wallet_count == expected.get(wallet_type, 0)
            for wallet in wallets:
                assert wallet["type"] == wallet_type.value


def assert_tx_amounts(
    tx: TransactionRecord,
    outputs: List[Dict[str, Any]],
    *,
    amount_fee: uint64,
    change_expected: bool,
    is_cat: bool = False,
) -> None:
    assert tx.fee_amount == amount_fee
    assert tx.amount == sum(output["amount"] for output in outputs)
    expected_additions = len(outputs) + 1 if change_expected else len(outputs)
    assert len(tx.additions) == expected_additions
    addition_amounts = [addition.amount for addition in tx.additions]
    removal_amounts = [removal.amount for removal in tx.removals]
    for output in outputs:
        assert output["amount"] in addition_amounts
    if is_cat:
        assert (sum(removal_amounts) - sum(addition_amounts)) == 0
    else:
        assert (sum(removal_amounts) - sum(addition_amounts)) == amount_fee


async def assert_push_tx_error(node_rpc: FullNodeRpcClient, tx: TransactionRecord):
    spend_bundle = tx.spend_bundle
    assert spend_bundle is not None
    # check error for a ASSERT_ANNOUNCE_CONSUMED_FAILED and if the error is not there throw a value error
    try:
        await node_rpc.push_tx(spend_bundle)
    except ValueError as error:
        error_string = error.args[0]["error"]  # noqa:  # pylint: disable=E1126
        if error_string.find("ASSERT_ANNOUNCE_CONSUMED_FAILED") == -1:
            raise ValueError from error


async def assert_get_balance(rpc_client: WalletRpcClient, wallet_node: WalletNode, wallet: WalletProtocol) -> None:
    expected_balance = await wallet_node.get_balance(wallet.id())
    expected_balance_dict = expected_balance.to_json_dict()
    expected_balance_dict["wallet_id"] = wallet.id()
    expected_balance_dict["wallet_type"] = wallet.type()
    expected_balance_dict["fingerprint"] = wallet_node.logged_in_fingerprint
    if wallet.type() in {WalletType.CAT, WalletType.CRCAT}:
        assert isinstance(wallet, CATWallet)
        expected_balance_dict["asset_id"] = wallet.get_asset_id()
    assert await rpc_client.get_wallet_balance(wallet.id()) == expected_balance_dict


async def tx_in_mempool(client: WalletRpcClient, transaction_id: bytes32):
    tx = await client.get_transaction(transaction_id)
    return tx.is_in_mempool()


async def get_confirmed_balance(client: WalletRpcClient, wallet_id: int):
    return (await client.get_wallet_balance(wallet_id))["confirmed_wallet_balance"]


async def get_unconfirmed_balance(client: WalletRpcClient, wallet_id: int):
    return (await client.get_wallet_balance(wallet_id))["unconfirmed_wallet_balance"]


@pytest.mark.anyio
async def test_send_transaction(wallet_rpc_environment: WalletRpcTestEnvironment):
    env: WalletRpcTestEnvironment = wallet_rpc_environment

    wallet_2: Wallet = env.wallet_2.wallet
    wallet_node: WalletNode = env.wallet_1.node
    full_node_api: FullNodeSimulator = env.full_node.api
    client: WalletRpcClient = env.wallet_1.rpc_client

    generated_funds = await generate_funds(full_node_api, env.wallet_1)

    addr = encode_puzzle_hash(await wallet_2.get_new_puzzlehash(), "txch")
    tx_amount = uint64(15600000)
    with pytest.raises(ValueError):
        await client.send_transaction(1, uint64(100000000000000001), addr, DEFAULT_TX_CONFIG)

    # Tests sending a basic transaction
    extra_conditions = (Remark(Program.to(("test", None))),)
    non_existent_coin = Coin(bytes32([0] * 32), bytes32([0] * 32), uint64(0))
    tx_no_push = (
        await client.send_transaction(
            1,
            tx_amount,
            addr,
            memos=["this is a basic tx"],
            tx_config=DEFAULT_TX_CONFIG.override(
                excluded_coin_amounts=[uint64(250000000000)],
                excluded_coin_ids=[non_existent_coin.name()],
                reuse_puzhash=True,
            ),
            extra_conditions=extra_conditions,
            push=False,
        )
    ).transaction
    response = await client.fetch(
        "send_transaction",
        {
            "wallet_id": 1,
            "amount": tx_amount,
            "address": addr,
            "fee": 0,
            "memos": ["this is a basic tx"],
            "puzzle_decorator": None,
            "extra_conditions": conditions_to_json_dicts(extra_conditions),
            "exclude_coin_amounts": [250000000000],
            "exclude_coins": [non_existent_coin.to_json_dict()],
            "reuse_puzhash": True,
            "CHIP-0029": True,
            "translation": "CHIP-0028",
            "push": True,
        },
    )
    assert response["success"]
    tx = TransactionRecord.from_json_dict_convenience(response["transactions"][0])
    [
        byte_deserialize_clvm_streamable(
            bytes.fromhex(utx), UnsignedTransaction, translation_layer=BLIND_SIGNER_TRANSLATION
        )
        for utx in response["unsigned_transactions"]
    ]
    assert tx == dataclasses.replace(tx_no_push, created_at_time=tx.created_at_time)
    transaction_id = tx.name
    spend_bundle = tx.spend_bundle
    assert spend_bundle is not None

    await time_out_assert(20, tx_in_mempool, True, client, transaction_id)
    await time_out_assert(20, get_unconfirmed_balance, generated_funds - tx_amount, client, 1)

    await farm_transaction(full_node_api, wallet_node, spend_bundle)

    # Checks that the memo can be retrieved
    tx_confirmed = await client.get_transaction(transaction_id)
    assert tx_confirmed.confirmed
    assert len(tx_confirmed.get_memos()) == 1
    assert [b"this is a basic tx"] in tx_confirmed.get_memos().values()
    assert list(tx_confirmed.get_memos().keys())[0] in [a.name() for a in spend_bundle.additions()]

    await time_out_assert(20, get_confirmed_balance, generated_funds - tx_amount, client, 1)


@pytest.mark.anyio
async def test_push_transactions(wallet_rpc_environment: WalletRpcTestEnvironment):
    env: WalletRpcTestEnvironment = wallet_rpc_environment

    wallet: Wallet = env.wallet_1.wallet
    wallet_node: WalletNode = env.wallet_1.node
    full_node_api: FullNodeSimulator = env.full_node.api
    client: WalletRpcClient = env.wallet_1.rpc_client

    await generate_funds(full_node_api, env.wallet_1, num_blocks=2)

    outputs = await create_tx_outputs(wallet, [(1234321, None)])

    tx = (
        await client.create_signed_transactions(
            outputs,
            tx_config=DEFAULT_TX_CONFIG,
            fee=uint64(100),
        )
    ).signed_tx

    resp_client = await client.push_transactions([tx], fee=uint64(10))
    resp = await client.fetch(
        "push_transactions", {"transactions": [tx.to_json_dict_convenience(wallet_node.config)], "fee": 10}
    )
    assert resp["success"]
    resp = await client.fetch("push_transactions", {"transactions": [tx.to_json_dict()], "fee": 10})
    assert resp["success"]

    spend_bundle = WalletSpendBundle.aggregate(
        [
            # We ARE checking that the spend bundle is not None but mypy can't recognize this
            TransactionRecord.from_json_dict_convenience(tx).spend_bundle  # type: ignore[type-var]
            for tx in resp_client["transactions"]
            if tx["spend_bundle"] is not None
        ]
    )
    assert spend_bundle is not None
    await farm_transaction(full_node_api, wallet_node, spend_bundle)

    for tx_json in resp_client["transactions"]:
        tx = TransactionRecord.from_json_dict_convenience(tx_json)
        tx = await client.get_transaction(transaction_id=tx.name)
        assert tx.confirmed


@pytest.mark.anyio
async def test_get_balance(wallet_rpc_environment: WalletRpcTestEnvironment):
    env = wallet_rpc_environment
    wallet: Wallet = env.wallet_1.wallet
    wallet_node: WalletNode = env.wallet_1.node
    full_node_api: FullNodeSimulator = env.full_node.api
    wallet_rpc_client = env.wallet_1.rpc_client
    await full_node_api.farm_blocks_to_wallet(2, wallet)
    async with wallet.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
        cat_wallet = await CATWallet.create_new_cat_wallet(
            wallet_node.wallet_state_manager,
            wallet,
            {"identifier": "genesis_by_id"},
            uint64(100),
            action_scope,
        )
    await full_node_api.wait_transaction_records_entered_mempool(action_scope.side_effects.transactions)
    await full_node_api.wait_for_wallet_synced(wallet_node)
    await assert_get_balance(wallet_rpc_client, wallet_node, wallet)
    await assert_get_balance(wallet_rpc_client, wallet_node, cat_wallet)


@pytest.mark.anyio
async def test_get_farmed_amount(wallet_rpc_environment: WalletRpcTestEnvironment):
    env = wallet_rpc_environment
    wallet: Wallet = env.wallet_1.wallet
    full_node_api: FullNodeSimulator = env.full_node.api
    wallet_rpc_client = env.wallet_1.rpc_client
    await full_node_api.farm_blocks_to_wallet(2, wallet)

    get_farmed_amount_result = await wallet_rpc_client.get_farmed_amount()
    get_timestamp_for_height_result = await wallet_rpc_client.get_timestamp_for_height(uint32(3))  # genesis + 2

    expected_result = {
        "blocks_won": 2,
        "farmed_amount": 4_000_000_000_000,
        "farmer_reward_amount": 500_000_000_000,
        "fee_amount": 0,
        "last_height_farmed": 3,
        "last_time_farmed": get_timestamp_for_height_result,
        "pool_reward_amount": 3_500_000_000_000,
        "success": True,
    }
    assert get_farmed_amount_result == expected_result


@pytest.mark.anyio
async def test_get_farmed_amount_with_fee(wallet_rpc_environment: WalletRpcTestEnvironment):
    env = wallet_rpc_environment
    wallet: Wallet = env.wallet_1.wallet
    full_node_api: FullNodeSimulator = env.full_node.api
    wallet_rpc_client = env.wallet_1.rpc_client
    wallet_node: WalletNode = env.wallet_1.node

    await generate_funds(full_node_api, env.wallet_1)

    fee_amount = 100
    async with wallet.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
        await wallet.generate_signed_transaction(
            amount=uint64(5),
            puzzle_hash=bytes32([0] * 32),
            action_scope=action_scope,
            fee=uint64(fee_amount),
        )

    our_ph = await wallet.get_new_puzzlehash()
    await full_node_api.wait_transaction_records_entered_mempool(records=action_scope.side_effects.transactions)
    await full_node_api.farm_blocks_to_puzzlehash(count=2, farm_to=our_ph, guarantee_transaction_blocks=True)
    await full_node_api.wait_for_wallet_synced(wallet_node=wallet_node, timeout=20)

    result = await wallet_rpc_client.get_farmed_amount()
    assert result["fee_amount"] == fee_amount


@pytest.mark.anyio
async def test_get_timestamp_for_height(wallet_rpc_environment: WalletRpcTestEnvironment):
    env: WalletRpcTestEnvironment = wallet_rpc_environment

    full_node_api: FullNodeSimulator = env.full_node.api
    client: WalletRpcClient = env.wallet_1.rpc_client

    await generate_funds(full_node_api, env.wallet_1)

    # This tests that the client returns a uint64, rather than raising or returning something unexpected
    uint64(await client.get_timestamp_for_height(uint32(1)))


@pytest.mark.parametrize(
    "output_args, fee, select_coin, is_cat",
    [
        ([(348026, None)], 0, False, False),
        ([(1270495230, ["memo_1"]), (902347, ["memo_2"])], 1, True, False),
        ([(84920, ["memo_1_0", "memo_1_1"]), (1, ["memo_2_0"])], 0, False, False),
        (
            [(32058710, ["memo_1_0", "memo_1_1"]), (1, ["memo_2_0"]), (923, ["memo_3_0", "memo_3_1"])],
            32804,
            True,
            False,
        ),
        ([(1337, ["LEET"]), (81000, ["pingwei"])], 817, False, True),
        ([(120000000000, None), (120000000000, None)], 10000000000, True, False),
    ],
)
@pytest.mark.anyio
async def test_create_signed_transaction(
    wallet_rpc_environment: WalletRpcTestEnvironment,
    output_args: List[Tuple[int, Optional[List[str]]]],
    fee: int,
    select_coin: bool,
    is_cat: bool,
):
    env: WalletRpcTestEnvironment = wallet_rpc_environment

    wallet_2: Wallet = env.wallet_2.wallet
    wallet_1_node: WalletNode = env.wallet_1.node
    wallet_1_rpc: WalletRpcClient = env.wallet_1.rpc_client
    full_node_api: FullNodeSimulator = env.full_node.api
    full_node_rpc: FullNodeRpcClient = env.full_node.rpc_client

    generated_funds = await generate_funds(full_node_api, env.wallet_1)

    wallet_id = 1
    if is_cat:
        generated_funds = 10**9

        res = await wallet_1_rpc.create_new_cat_and_wallet(uint64(generated_funds), test=True)
        assert res["success"]
        wallet_id = res["wallet_id"]

        await time_out_assert(5, check_mempool_spend_count, True, full_node_api, 1)
        for i in range(5):
            if check_mempool_spend_count(full_node_api, 0):
                break
            await farm_transaction_block(full_node_api, wallet_1_node)

    outputs = await create_tx_outputs(wallet_2, output_args)
    amount_outputs = sum(output["amount"] for output in outputs)
    amount_fee = uint64(fee)

    if is_cat:
        amount_total = amount_outputs
    else:
        amount_total = amount_outputs + amount_fee

    selected_coin = None
    if select_coin:
        selected_coin = await wallet_1_rpc.select_coins(
            amount=amount_total, wallet_id=wallet_id, coin_selection_config=DEFAULT_COIN_SELECTION_CONFIG
        )
        assert len(selected_coin) == 1

    txs = (
        await wallet_1_rpc.create_signed_transactions(
            outputs,
            coins=selected_coin,
            fee=amount_fee,
            wallet_id=wallet_id,
            # shouldn't actually block it
            tx_config=DEFAULT_TX_CONFIG.override(
                excluded_coin_amounts=[uint64(selected_coin[0].amount)] if selected_coin is not None else [],
            ),
            push=True,
        )
    ).transactions
    change_expected = not selected_coin or selected_coin[0].amount - amount_total > 0
    assert_tx_amounts(txs[-1], outputs, amount_fee=amount_fee, change_expected=change_expected, is_cat=is_cat)

    # Farm the transaction and make sure the wallet balance reflects it correct
    spend_bundle = txs[0].spend_bundle
    assert spend_bundle is not None
    await farm_transaction(full_node_api, wallet_1_node, spend_bundle)
    await time_out_assert(20, get_confirmed_balance, generated_funds - amount_total, wallet_1_rpc, wallet_id)

    # Assert every coin comes from the same parent
    additions: List[Coin] = spend_bundle.additions()
    assert len({c.parent_coin_info for c in additions}) == 2 if is_cat else 1

    # Assert you can get the spend for each addition
    for addition in additions:
        cr: Optional[CoinRecord] = await full_node_rpc.get_coin_record_by_name(addition.name())
        assert cr is not None
        spend: Optional[CoinSpend] = await full_node_rpc.get_puzzle_and_solution(
            addition.parent_coin_info, cr.confirmed_block_index
        )
        assert spend is not None

    # Assert the memos are all correct
    addition_dict: Dict[bytes32, Coin] = {addition.name(): addition for addition in additions}
    memo_dictionary: Dict[bytes32, List[bytes]] = compute_memos(spend_bundle)
    for output in outputs:
        if "memos" in output:
            found: bool = False
            for addition_id, addition in addition_dict.items():
                if (
                    is_cat
                    and addition.amount == output["amount"]
                    and memo_dictionary[addition_id][0] == output["puzzle_hash"]
                    and memo_dictionary[addition_id][1:] == [memo.encode() for memo in output["memos"]]
                ) or (
                    addition.amount == output["amount"]
                    and addition.puzzle_hash == output["puzzle_hash"]
                    and memo_dictionary[addition_id] == [memo.encode() for memo in output["memos"]]
                ):
                    found = True
            assert found


@pytest.mark.anyio
async def test_create_signed_transaction_with_coin_announcement(wallet_rpc_environment: WalletRpcTestEnvironment):
    env: WalletRpcTestEnvironment = wallet_rpc_environment

    wallet_2: Wallet = env.wallet_2.wallet
    full_node_api: FullNodeSimulator = env.full_node.api
    client: WalletRpcClient = env.wallet_1.rpc_client
    client_node: FullNodeRpcClient = env.full_node.rpc_client

    await generate_funds(full_node_api, env.wallet_1)

    signed_tx_amount = uint64(888000)
    tx_coin_announcements = [
        CreateCoinAnnouncement(
            std_hash(b"\xca" + std_hash(b"message")),
            std_hash(b"coin_id_1"),
        ),
        CreateCoinAnnouncement(
            bytes(Program.to("a string")),
            std_hash(b"coin_id_2"),
        ),
    ]
    outputs = await create_tx_outputs(wallet_2, [(signed_tx_amount, None)])
    tx_res: TransactionRecord = (
        await client.create_signed_transactions(
            outputs, tx_config=DEFAULT_TX_CONFIG, extra_conditions=(*tx_coin_announcements,)
        )
    ).signed_tx
    assert_tx_amounts(tx_res, outputs, amount_fee=uint64(0), change_expected=True)
    await assert_push_tx_error(client_node, tx_res)


@pytest.mark.anyio
async def test_create_signed_transaction_with_puzzle_announcement(wallet_rpc_environment: WalletRpcTestEnvironment):
    env: WalletRpcTestEnvironment = wallet_rpc_environment

    wallet_2: Wallet = env.wallet_2.wallet
    full_node_api: FullNodeSimulator = env.full_node.api
    client: WalletRpcClient = env.wallet_1.rpc_client
    client_node: FullNodeRpcClient = env.full_node.rpc_client

    await generate_funds(full_node_api, env.wallet_1)

    signed_tx_amount = uint64(888000)
    tx_puzzle_announcements = [
        CreatePuzzleAnnouncement(
            std_hash(b"\xca" + std_hash(b"message")),
            std_hash(b"puzzle_hash_1"),
        ),
        CreatePuzzleAnnouncement(
            bytes(Program.to("a string")),
            std_hash(b"puzzle_hash_2"),
        ),
    ]
    outputs = await create_tx_outputs(wallet_2, [(signed_tx_amount, None)])
    tx_res = (
        await client.create_signed_transactions(
            outputs, tx_config=DEFAULT_TX_CONFIG, extra_conditions=(*tx_puzzle_announcements,)
        )
    ).signed_tx
    assert_tx_amounts(tx_res, outputs, amount_fee=uint64(0), change_expected=True)
    await assert_push_tx_error(client_node, tx_res)


@pytest.mark.anyio
async def test_create_signed_transaction_with_excluded_coins(wallet_rpc_environment: WalletRpcTestEnvironment) -> None:
    env: WalletRpcTestEnvironment = wallet_rpc_environment
    wallet_1: Wallet = env.wallet_1.wallet
    wallet_1_rpc: WalletRpcClient = env.wallet_1.rpc_client
    full_node_api: FullNodeSimulator = env.full_node.api
    full_node_rpc: FullNodeRpcClient = env.full_node.rpc_client
    await generate_funds(full_node_api, env.wallet_1)

    async def it_does_not_include_the_excluded_coins() -> None:
        selected_coins = await wallet_1_rpc.select_coins(
            amount=250000000000, wallet_id=1, coin_selection_config=DEFAULT_COIN_SELECTION_CONFIG
        )
        assert len(selected_coins) == 1
        outputs = await create_tx_outputs(wallet_1, [(uint64(250000000000), None)])

        tx = (
            await wallet_1_rpc.create_signed_transactions(
                outputs,
                DEFAULT_TX_CONFIG.override(
                    excluded_coin_ids=[c.name() for c in selected_coins],
                ),
            )
        ).signed_tx

        assert len(tx.removals) == 1
        assert tx.removals[0] != selected_coins[0]
        assert tx.removals[0].amount == uint64(1750000000000)
        await assert_push_tx_error(full_node_rpc, tx)

    async def it_throws_an_error_when_all_spendable_coins_are_excluded() -> None:
        selected_coins = await wallet_1_rpc.select_coins(
            amount=1750000000000, wallet_id=1, coin_selection_config=DEFAULT_COIN_SELECTION_CONFIG
        )
        assert len(selected_coins) == 1
        outputs = await create_tx_outputs(wallet_1, [(uint64(1750000000000), None)])

        with pytest.raises(ValueError):
            await wallet_1_rpc.create_signed_transactions(
                outputs,
                DEFAULT_TX_CONFIG.override(
                    excluded_coin_ids=[c.name() for c in selected_coins],
                ),
            )

    await it_does_not_include_the_excluded_coins()
    await it_throws_an_error_when_all_spendable_coins_are_excluded()


@pytest.mark.anyio
async def test_spend_clawback_coins(wallet_rpc_environment: WalletRpcTestEnvironment):
    env: WalletRpcTestEnvironment = wallet_rpc_environment

    wallet_1_node: WalletNode = env.wallet_1.node
    wallet_2_node: WalletNode = env.wallet_2.node
    wallet_1_rpc: WalletRpcClient = env.wallet_1.rpc_client
    wallet_2_rpc: WalletRpcClient = env.wallet_2.rpc_client
    wallet_1 = wallet_1_node.wallet_state_manager.main_wallet
    wallet_2 = wallet_2_node.wallet_state_manager.main_wallet
    full_node_api: FullNodeSimulator = env.full_node.api
    wallet_2_api = WalletRpcApi(wallet_2_node)

    generated_funds = await generate_funds(full_node_api, env.wallet_1, 1)
    await generate_funds(full_node_api, env.wallet_2, 1)
    wallet_1_puzhash = await wallet_1.get_new_puzzlehash()
    await full_node_api.wait_for_wallet_synced(wallet_node=wallet_1_node, timeout=20)
    wallet_2_puzhash = await wallet_2.get_new_puzzlehash()
    tx = (
        await wallet_1_rpc.send_transaction(
            wallet_id=1,
            amount=uint64(500),
            address=encode_puzzle_hash(wallet_2_puzhash, "txch"),
            tx_config=DEFAULT_TX_CONFIG,
            fee=uint64(0),
            puzzle_decorator_override=[{"decorator": "CLAWBACK", "clawback_timelock": 5}],
        )
    ).transaction
    clawback_coin_id_1 = tx.additions[0].name()
    assert tx.spend_bundle is not None
    await farm_transaction(full_node_api, wallet_1_node, tx.spend_bundle)
    await full_node_api.wait_for_wallet_synced(wallet_node=wallet_2_node, timeout=20)
    tx = (
        await wallet_2_rpc.send_transaction(
            wallet_id=1,
            amount=uint64(500),
            address=encode_puzzle_hash(wallet_1_puzhash, "txch"),
            tx_config=DEFAULT_TX_CONFIG,
            fee=uint64(0),
            puzzle_decorator_override=[{"decorator": "CLAWBACK", "clawback_timelock": 5}],
        )
    ).transaction
    assert tx.spend_bundle is not None
    clawback_coin_id_2 = tx.additions[0].name()
    await farm_transaction(full_node_api, wallet_2_node, tx.spend_bundle)
    await time_out_assert(20, get_confirmed_balance, generated_funds - 500, wallet_1_rpc, 1)
    await time_out_assert(20, get_confirmed_balance, generated_funds - 500, wallet_2_rpc, 1)
    await asyncio.sleep(10)
    # Test missing coin_ids
    has_exception = False
    try:
        await wallet_2_api.spend_clawback_coins({})
    except ValueError:
        has_exception = True
    assert has_exception
    # Test coin ID is not a Clawback coin
    invalid_coin_id = tx.removals[0].name()
    resp = await wallet_2_rpc.spend_clawback_coins([invalid_coin_id], 500)
    assert resp["success"]
    assert resp["transaction_ids"] == []
    # Test unsupported wallet
    coin_record = await wallet_1_node.wallet_state_manager.coin_store.get_coin_record(clawback_coin_id_1)
    assert coin_record is not None
    await wallet_1_node.wallet_state_manager.coin_store.add_coin_record(
        dataclasses.replace(coin_record, wallet_type=WalletType.CAT)
    )
    resp = await wallet_1_rpc.spend_clawback_coins([clawback_coin_id_1], 100)
    assert resp["success"]
    assert len(resp["transaction_ids"]) == 0
    # Test missing metadata
    await wallet_1_node.wallet_state_manager.coin_store.add_coin_record(dataclasses.replace(coin_record, metadata=None))
    resp = await wallet_1_rpc.spend_clawback_coins([clawback_coin_id_1], 100)
    assert resp["success"]
    assert len(resp["transaction_ids"]) == 0
    # Test missing incoming tx
    coin_record = await wallet_1_node.wallet_state_manager.coin_store.get_coin_record(clawback_coin_id_2)
    assert coin_record is not None
    fake_coin = Coin(coin_record.coin.parent_coin_info, wallet_2_puzhash, coin_record.coin.amount)
    await wallet_1_node.wallet_state_manager.coin_store.add_coin_record(
        dataclasses.replace(coin_record, coin=fake_coin)
    )
    resp = await wallet_1_rpc.spend_clawback_coins([fake_coin.name()], 100)
    assert resp["transaction_ids"] == []
    # Test coin puzzle hash doesn't match the puzzle
    farmed_tx = (await wallet_1.wallet_state_manager.tx_store.get_farming_rewards())[0]
    await wallet_1.wallet_state_manager.tx_store.add_transaction_record(
        dataclasses.replace(farmed_tx, name=fake_coin.name())
    )
    await wallet_1_node.wallet_state_manager.coin_store.add_coin_record(
        dataclasses.replace(coin_record, coin=fake_coin)
    )
    resp = await wallet_1_rpc.spend_clawback_coins([fake_coin.name()], 100)
    assert resp["transaction_ids"] == []
    # Test claim spend
    await wallet_2_rpc.set_auto_claim(
        AutoClaimSettings(
            enabled=False,
            tx_fee=uint64(100),
            min_amount=uint64(0),
            batch_size=uint16(1),
        )
    )
    resp = await wallet_2_rpc.spend_clawback_coins([clawback_coin_id_1, clawback_coin_id_2], 100)
    assert resp["success"]
    assert len(resp["transaction_ids"]) == 2
    for _tx in resp["transactions"]:
        clawback_tx = TransactionRecord.from_json_dict_convenience(_tx)
        if clawback_tx.spend_bundle is not None:
            await time_out_assert_not_none(
                10, full_node_api.full_node.mempool_manager.get_spendbundle, clawback_tx.spend_bundle.name()
            )
    await farm_transaction_block(full_node_api, wallet_2_node)
    await time_out_assert(20, get_confirmed_balance, generated_funds + 300, wallet_2_rpc, 1)
    # Test spent coin
    resp = await wallet_2_rpc.spend_clawback_coins([clawback_coin_id_1], 500)
    assert resp["success"]
    assert resp["transaction_ids"] == []


@pytest.mark.anyio
async def test_send_transaction_multi(wallet_rpc_environment: WalletRpcTestEnvironment):
    env: WalletRpcTestEnvironment = wallet_rpc_environment

    wallet_2: Wallet = env.wallet_2.wallet
    wallet_node: WalletNode = env.wallet_1.node
    full_node_api: FullNodeSimulator = env.full_node.api
    client: WalletRpcClient = env.wallet_1.rpc_client

    generated_funds = await generate_funds(full_node_api, env.wallet_1)

    removals = await client.select_coins(
        1750000000000, wallet_id=1, coin_selection_config=DEFAULT_COIN_SELECTION_CONFIG
    )  # we want a coin that won't be selected by default
    outputs = await create_tx_outputs(wallet_2, [(uint64(1), ["memo_1"]), (uint64(2), ["memo_2"])])
    amount_outputs = sum(output["amount"] for output in outputs)
    amount_fee = uint64(amount_outputs + 1)

    send_tx_res: TransactionRecord = (
        await client.send_transaction_multi(
            1,
            outputs,
            DEFAULT_TX_CONFIG,
            coins=removals,
            fee=amount_fee,
        )
    ).transaction
    spend_bundle = send_tx_res.spend_bundle
    assert spend_bundle is not None
    assert send_tx_res is not None

    assert_tx_amounts(send_tx_res, outputs, amount_fee=amount_fee, change_expected=True)
    assert send_tx_res.removals == removals

    await farm_transaction(full_node_api, wallet_node, spend_bundle)

    await time_out_assert(20, get_confirmed_balance, generated_funds - amount_outputs - amount_fee, client, 1)

    # Checks that the memo can be retrieved
    tx_confirmed = await client.get_transaction(send_tx_res.name)
    assert tx_confirmed.confirmed
    memos = tx_confirmed.get_memos()
    assert len(memos) == len(outputs)
    for output in outputs:
        assert [output["memos"][0].encode()] in memos.values()
    spend_bundle = send_tx_res.spend_bundle
    assert spend_bundle is not None
    for key in memos.keys():
        assert key in [a.name() for a in spend_bundle.additions()]


@pytest.mark.anyio
async def test_get_transactions(wallet_rpc_environment: WalletRpcTestEnvironment):
    env: WalletRpcTestEnvironment = wallet_rpc_environment

    wallet: Wallet = env.wallet_1.wallet
    wallet_node: WalletNode = env.wallet_1.node
    full_node_api: FullNodeSimulator = env.full_node.api
    client: WalletRpcClient = env.wallet_1.rpc_client

    await generate_funds(full_node_api, env.wallet_1, 5)

    all_transactions = await client.get_transactions(1)
    assert len(all_transactions) >= 10
    # Test transaction pagination
    some_transactions = await client.get_transactions(1, 0, 5)
    some_transactions_2 = await client.get_transactions(1, 5, 10)
    assert some_transactions == all_transactions[0:5]
    assert some_transactions_2 == all_transactions[5:10]

    # Testing sorts
    # Test the default sort (CONFIRMED_AT_HEIGHT)
    assert all_transactions == sorted(all_transactions, key=attrgetter("confirmed_at_height"))
    all_transactions = await client.get_transactions(1, reverse=True)
    assert all_transactions == sorted(all_transactions, key=attrgetter("confirmed_at_height"), reverse=True)

    # Test RELEVANCE
    puzhash = await wallet.get_new_puzzlehash()
    await full_node_api.wait_for_wallet_synced(wallet_node=wallet_node, timeout=20)
    await client.send_transaction(
        1, uint64(1), encode_puzzle_hash(puzhash, "txch"), DEFAULT_TX_CONFIG
    )  # Create a pending tx

    all_transactions = await client.get_transactions(1, sort_key=SortKey.RELEVANCE)
    sorted_transactions = sorted(all_transactions, key=attrgetter("created_at_time"), reverse=True)
    sorted_transactions = sorted(sorted_transactions, key=attrgetter("confirmed_at_height"), reverse=True)
    sorted_transactions = sorted(sorted_transactions, key=attrgetter("confirmed"))
    assert all_transactions == sorted_transactions

    all_transactions = await client.get_transactions(1, sort_key=SortKey.RELEVANCE, reverse=True)
    sorted_transactions = sorted(all_transactions, key=attrgetter("created_at_time"))
    sorted_transactions = sorted(sorted_transactions, key=attrgetter("confirmed_at_height"))
    sorted_transactions = sorted(sorted_transactions, key=attrgetter("confirmed"), reverse=True)
    assert all_transactions == sorted_transactions

    # Test get_transactions to address
    ph_by_addr = await wallet.get_new_puzzlehash()
    await full_node_api.wait_for_wallet_synced(wallet_node=wallet_node, timeout=20)
    await client.send_transaction(1, uint64(1), encode_puzzle_hash(ph_by_addr, "txch"), DEFAULT_TX_CONFIG)
    await full_node_api.wait_for_wallet_synced(wallet_node=wallet_node, timeout=20)
    tx_for_address = await client.get_transactions(1, to_address=encode_puzzle_hash(ph_by_addr, "txch"))
    assert len(tx_for_address) == 1
    assert tx_for_address[0].to_puzzle_hash == ph_by_addr

    # Test type filter
    all_transactions = await client.get_transactions(
        1, type_filter=TransactionTypeFilter.include([TransactionType.COINBASE_REWARD])
    )
    assert len(all_transactions) == 5
    assert all(transaction.type == TransactionType.COINBASE_REWARD for transaction in all_transactions)
    # Test confirmed filter
    all_transactions = await client.get_transactions(1, confirmed=True)
    assert len(all_transactions) == 10
    assert all(transaction.confirmed for transaction in all_transactions)
    all_transactions = await client.get_transactions(1, confirmed=False)
    assert len(all_transactions) == 2
    assert all(not transaction.confirmed for transaction in all_transactions)

    # Test bypass broken txs
    await wallet.wallet_state_manager.tx_store.add_transaction_record(
        dataclasses.replace(all_transactions[0], type=uint32(TransactionType.INCOMING_CLAWBACK_SEND))
    )
    all_transactions = await client.get_transactions(
        1, type_filter=TransactionTypeFilter.include([TransactionType.INCOMING_CLAWBACK_SEND]), confirmed=False
    )
    assert len(all_transactions) == 1


@pytest.mark.anyio
async def test_get_transaction_count(wallet_rpc_environment: WalletRpcTestEnvironment):
    env: WalletRpcTestEnvironment = wallet_rpc_environment

    full_node_api: FullNodeSimulator = env.full_node.api
    client: WalletRpcClient = env.wallet_1.rpc_client

    await generate_funds(full_node_api, env.wallet_1)

    all_transactions = await client.get_transactions(1)
    assert len(all_transactions) > 0
    transaction_count = await client.get_transaction_count(1)
    assert transaction_count == len(all_transactions)
    transaction_count = await client.get_transaction_count(1, confirmed=False)
    assert transaction_count == 0
    transaction_count = await client.get_transaction_count(
        1, type_filter=TransactionTypeFilter.include([TransactionType.INCOMING_CLAWBACK_SEND])
    )
    assert transaction_count == 0


@pytest.mark.anyio
async def test_cat_endpoints(wallet_rpc_environment: WalletRpcTestEnvironment):
    env: WalletRpcTestEnvironment = wallet_rpc_environment

    wallet_node: WalletNode = env.wallet_1.node

    client: WalletRpcClient = env.wallet_1.rpc_client
    client_2: WalletRpcClient = env.wallet_2.rpc_client

    full_node_api: FullNodeSimulator = env.full_node.api

    await generate_funds(full_node_api, env.wallet_1, 1)
    await generate_funds(full_node_api, env.wallet_2, 1)

    # Test a deprecated path
    with pytest.raises(ValueError, match="dropped"):
        await client.fetch(
            "create_new_wallet",
            {
                "wallet_type": "cat_wallet",
                "mode": "new",
            },
        )

    # Creates a CAT wallet with 100 mojos and a CAT with 20 mojos and fee=10
    await client.create_new_cat_and_wallet(uint64(100), fee=uint64(10), test=True)
    await time_out_assert(20, client.get_synced)

    res = await client.create_new_cat_and_wallet(uint64(20), test=True)
    assert res["success"]
    cat_0_id = res["wallet_id"]
    asset_id = bytes32.fromhex(res["asset_id"])
    assert len(asset_id) > 0

    await assert_wallet_types(client, {WalletType.STANDARD_WALLET: 1, WalletType.CAT: 2})
    await assert_wallet_types(client_2, {WalletType.STANDARD_WALLET: 1})

    bal_0 = await client.get_wallet_balance(cat_0_id)
    assert bal_0["confirmed_wallet_balance"] == 0
    assert bal_0["pending_coin_removal_count"] == 1
    col = await client.get_cat_asset_id(cat_0_id)
    assert col == asset_id
    assert (await client.get_cat_name(cat_0_id)) == CATWallet.default_wallet_name_for_unknown_cat(asset_id.hex())
    await client.set_cat_name(cat_0_id, "My cat")
    assert (await client.get_cat_name(cat_0_id)) == "My cat"
    result = await client.cat_asset_id_to_name(col)
    assert result is not None
    wid, name = result
    assert wid == cat_0_id
    assert name == "My cat"
    result = await client.cat_asset_id_to_name(bytes32([0] * 32))
    assert result is None
    verified_asset_id = next(iter(DEFAULT_CATS.items()))[1]["asset_id"]
    result = await client.cat_asset_id_to_name(bytes32.from_hexstr(verified_asset_id))
    assert result is not None
    should_be_none, name = result
    assert should_be_none is None
    assert name == next(iter(DEFAULT_CATS.items()))[1]["name"]

    # make sure spend is in mempool before farming tx block
    await time_out_assert(5, check_mempool_spend_count, True, full_node_api, 2)
    for i in range(5):
        if check_mempool_spend_count(full_node_api, 0):
            break
        await farm_transaction_block(full_node_api, wallet_node)

    # check that we farmed the transaction
    assert check_mempool_spend_count(full_node_api, 0)
    await full_node_api.wait_for_wallet_synced(wallet_node=wallet_node, timeout=5)

    await time_out_assert(5, get_confirmed_balance, 20, client, cat_0_id)
    bal_0 = await client.get_wallet_balance(cat_0_id)
    assert bal_0["pending_coin_removal_count"] == 0
    assert bal_0["unspent_coin_count"] == 1

    # Creates a second wallet with the same CAT
    res = await client_2.create_wallet_for_existing_cat(asset_id)
    assert res["success"]
    cat_1_id = res["wallet_id"]
    cat_1_asset_id = bytes.fromhex(res["asset_id"])
    assert cat_1_asset_id == asset_id

    await assert_wallet_types(client, {WalletType.STANDARD_WALLET: 1, WalletType.CAT: 2})
    await assert_wallet_types(client_2, {WalletType.STANDARD_WALLET: 1, WalletType.CAT: 1})

    await farm_transaction_block(full_node_api, wallet_node)

    bal_1 = await client_2.get_wallet_balance(cat_1_id)
    assert bal_1["confirmed_wallet_balance"] == 0

    addr_0 = await client.get_next_address(cat_0_id, False)
    addr_1 = await client_2.get_next_address(cat_1_id, False)

    assert addr_0 != addr_1

    # Test CAT spend without a fee
    with pytest.raises(ValueError):
        await client.cat_spend(
            cat_0_id,
            DEFAULT_TX_CONFIG.override(
                excluded_coin_amounts=[uint64(20)],
                excluded_coin_ids=[bytes32([0] * 32)],
            ),
            uint64(4),
            addr_1,
            uint64(0),
            ["the cat memo"],
        )
    tx_res = await client.cat_spend(cat_0_id, DEFAULT_TX_CONFIG, uint64(4), addr_1, uint64(0), ["the cat memo"])

    spend_bundle = tx_res.transaction.spend_bundle
    assert spend_bundle is not None
    assert uncurry_puzzle(spend_bundle.coin_spends[0].puzzle_reveal).mod == CAT_MOD
    await farm_transaction(full_node_api, wallet_node, spend_bundle)

    await farm_transaction_block(full_node_api, wallet_node)

    # Test CAT spend with a fee
    tx_res = await client.cat_spend(cat_0_id, DEFAULT_TX_CONFIG, uint64(1), addr_1, uint64(5_000_000), ["the cat memo"])

    spend_bundle = tx_res.transaction.spend_bundle
    assert spend_bundle is not None
    await farm_transaction(full_node_api, wallet_node, spend_bundle)

    # Test CAT spend with a fee and pre-specified removals / coins
    removals = await client.select_coins(
        amount=uint64(2), wallet_id=cat_0_id, coin_selection_config=DEFAULT_COIN_SELECTION_CONFIG
    )
    tx_res = await client.cat_spend(
        cat_0_id, DEFAULT_TX_CONFIG, uint64(1), addr_1, uint64(5_000_000), ["the cat memo"], removals=removals
    )

    spend_bundle = tx_res.transaction.spend_bundle
    assert spend_bundle is not None
    assert removals[0] in {removal for tx in tx_res.transactions for removal in tx.removals}
    await farm_transaction(full_node_api, wallet_node, spend_bundle)

    # Test unacknowledged CAT
    await wallet_node.wallet_state_manager.interested_store.add_unacknowledged_token(
        asset_id, "Unknown", uint32(10000), bytes32(b"\00" * 32)
    )
    cats = await client.get_stray_cats()
    assert len(cats) == 1

    await time_out_assert(20, get_confirmed_balance, 14, client, cat_0_id)
    await time_out_assert(20, get_confirmed_balance, 6, client_2, cat_1_id)

    # Test CAT coin selection
    selected_coins = await client.select_coins(
        amount=1, wallet_id=cat_0_id, coin_selection_config=DEFAULT_COIN_SELECTION_CONFIG
    )
    assert len(selected_coins) > 0

    # Test get_cat_list
    assert len(DEFAULT_CATS) == len((await client.get_cat_list()).cat_list)


@pytest.mark.anyio
async def test_offer_endpoints(wallet_rpc_environment: WalletRpcTestEnvironment):
    env: WalletRpcTestEnvironment = wallet_rpc_environment

    wallet_node: WalletNode = env.wallet_1.node
    wallet_1_rpc: WalletRpcClient = env.wallet_1.rpc_client
    wallet_2_rpc: WalletRpcClient = env.wallet_2.rpc_client
    full_node_api: FullNodeSimulator = env.full_node.api

    await generate_funds(full_node_api, env.wallet_1, 1)
    await generate_funds(full_node_api, env.wallet_2, 1)

    # Creates a CAT wallet with 20 mojos
    res = await wallet_1_rpc.create_new_cat_and_wallet(uint64(20), test=True)
    assert res["success"]
    cat_wallet_id = res["wallet_id"]
    cat_asset_id = bytes32.fromhex(res["asset_id"])
    await time_out_assert(5, check_mempool_spend_count, True, full_node_api, 1)
    await farm_transaction_block(full_node_api, wallet_node)
    await full_node_api.wait_for_wallet_synced(wallet_node=wallet_node, timeout=5)

    await time_out_assert(5, get_confirmed_balance, 20, wallet_1_rpc, cat_wallet_id)

    # Creates a wallet for the same CAT on wallet_2 and send 4 CAT from wallet_1 to it
    await wallet_2_rpc.create_wallet_for_existing_cat(cat_asset_id)
    wallet_2_address = await wallet_2_rpc.get_next_address(cat_wallet_id, False)
    adds = [{"puzzle_hash": decode_puzzle_hash(wallet_2_address), "amount": uint64(4), "memos": ["the cat memo"]}]
    tx_res = (
        await wallet_1_rpc.send_transaction_multi(
            cat_wallet_id, additions=adds, tx_config=DEFAULT_TX_CONFIG, fee=uint64(0)
        )
    ).transaction
    spend_bundle = tx_res.spend_bundle
    assert spend_bundle is not None
    await farm_transaction(full_node_api, wallet_node, spend_bundle)
    await time_out_assert(5, get_confirmed_balance, 4, wallet_2_rpc, cat_wallet_id)
    test_crs: List[CoinRecord] = await wallet_1_rpc.get_coin_records_by_names(
        [a.name() for a in spend_bundle.additions() if a.amount != 4]
    )
    for cr in test_crs:
        assert cr.coin in spend_bundle.additions()
    with pytest.raises(ValueError):
        await wallet_1_rpc.get_coin_records_by_names([a.name() for a in spend_bundle.additions() if a.amount == 4])
    # Create an offer of 5 chia for one CAT
    await wallet_1_rpc.create_offer_for_ids(
        {uint32(1): -5, cat_asset_id.hex(): 1}, DEFAULT_TX_CONFIG, validate_only=True
    )
    all_offers = await wallet_1_rpc.get_all_offers()
    assert len(all_offers) == 0

    driver_dict: Dict[str, Any] = {cat_asset_id.hex(): {"type": "CAT", "tail": "0x" + cat_asset_id.hex()}}

    create_res = await wallet_1_rpc.create_offer_for_ids(
        {uint32(1): -5, cat_asset_id.hex(): 1},
        DEFAULT_TX_CONFIG,
        driver_dict=driver_dict,
        fee=uint64(1),
    )
    offer = create_res.offer

    id, summary = await wallet_1_rpc.get_offer_summary(offer)
    assert id == offer.name()
    id, advanced_summary = await wallet_1_rpc.get_offer_summary(offer, advanced=True)
    assert id == offer.name()
    assert summary == {
        "offered": {"xch": 5},
        "requested": {cat_asset_id.hex(): 1},
        "infos": driver_dict,
        "fees": 1,
        "additions": [c.name().hex() for c in offer.additions()],
        "removals": [c.name().hex() for c in offer.removals()],
        "valid_times": {
            "max_height": None,
            "max_time": None,
            "min_height": None,
            "min_time": None,
        },
    }
    assert advanced_summary == summary

    id, valid = await wallet_1_rpc.check_offer_validity(offer)
    assert id == offer.name()

    all_offers = await wallet_1_rpc.get_all_offers(file_contents=True)
    assert len(all_offers) == 1
    assert TradeStatus(all_offers[0].status) == TradeStatus.PENDING_ACCEPT
    assert all_offers[0].offer == bytes(offer)

    offer_count = await wallet_1_rpc.get_offers_count()
    assert offer_count.total == 1
    assert offer_count.my_offers_count == 1
    assert offer_count.taken_offers_count == 0

    trade_record = (await wallet_2_rpc.take_offer(offer, DEFAULT_TX_CONFIG, fee=uint64(1))).trade_record
    assert TradeStatus(trade_record.status) == TradeStatus.PENDING_CONFIRM

    await wallet_1_rpc.cancel_offer(offer.name(), DEFAULT_TX_CONFIG, secure=False)

    trade_record = await wallet_1_rpc.get_offer(offer.name(), file_contents=True)
    assert trade_record.offer == bytes(offer)
    assert TradeStatus(trade_record.status) == TradeStatus.CANCELLED

    await wallet_1_rpc.cancel_offer(offer.name(), DEFAULT_TX_CONFIG, fee=uint64(1), secure=True)

    trade_record = await wallet_1_rpc.get_offer(offer.name())
    assert TradeStatus(trade_record.status) == TradeStatus.PENDING_CANCEL

    create_res = await wallet_1_rpc.create_offer_for_ids(
        {uint32(1): -5, cat_wallet_id: 1}, DEFAULT_TX_CONFIG, fee=uint64(1)
    )
    all_offers = await wallet_1_rpc.get_all_offers()
    assert len(all_offers) == 2
    offer_count = await wallet_1_rpc.get_offers_count()
    assert offer_count.total == 2
    assert offer_count.my_offers_count == 2
    assert offer_count.taken_offers_count == 0
    new_trade_record = create_res.trade_record

    await farm_transaction_block(full_node_api, wallet_node)

    async def is_trade_confirmed(client, trade) -> bool:
        trade_record = await client.get_offer(trade.name())
        return TradeStatus(trade_record.status) == TradeStatus.CONFIRMED

    await time_out_assert(15, is_trade_confirmed, True, wallet_1_rpc, offer)

    # Test trade sorting
    def only_ids(trades):
        return [t.trade_id for t in trades]

    trade_record = await wallet_1_rpc.get_offer(offer.name())
    all_offers = await wallet_1_rpc.get_all_offers(include_completed=True)  # confirmed at index descending
    assert len(all_offers) == 2
    assert only_ids(all_offers) == only_ids([trade_record, new_trade_record])
    all_offers = await wallet_1_rpc.get_all_offers(include_completed=True, reverse=True)  # confirmed at index ascending
    assert only_ids(all_offers) == only_ids([new_trade_record, trade_record])
    all_offers = await wallet_1_rpc.get_all_offers(include_completed=True, sort_key="RELEVANCE")  # most relevant
    assert only_ids(all_offers) == only_ids([new_trade_record, trade_record])
    all_offers = await wallet_1_rpc.get_all_offers(
        include_completed=True, sort_key="RELEVANCE", reverse=True
    )  # least relevant
    assert only_ids(all_offers) == only_ids([trade_record, new_trade_record])
    # Test pagination
    all_offers = await wallet_1_rpc.get_all_offers(include_completed=True, start=0, end=1)
    assert len(all_offers) == 1
    all_offers = await wallet_1_rpc.get_all_offers(include_completed=True, start=50)
    assert len(all_offers) == 0
    all_offers = await wallet_1_rpc.get_all_offers(include_completed=True, start=0, end=50)
    assert len(all_offers) == 2

    ###
    # This is temporary code, delete it when we no longer care about incorrectly parsing old offers
    # There's also temp code in wallet_rpc_api.py
    with pytest.raises(ValueError, match="Old offer format is no longer supported"):
        await wallet_1_rpc.fetch(
            "get_offer_summary",
            {
                "offer": "offer1qqr83wcuu2rykcmqvpsxygqq0qthwpmsrsutadthxda7ppk8wemm74e88h2dh265k7fv7kdk2etmg99xpm0yu8ddl4rkhl73mflmfasl4h75w6lllup4t7urp0mstehm8cnmc6mdxn0rvdejdfpway2ccm6srenn6urvdmgvand96gat25z42f4u2sh7ad7upvhfty77v6ak76dmrdxrzdgn89mlr58ya6j77yax8095r2u2g826yg9jq4q6xzt4g6yveqnhg6r77lrt3weksdwcwz5ava4t5mtdem5syjejwg53q6t5lfd2t5p6dds9dylj7jxw2fmquugdnkvke5jckmsr8ne4akwha9hv9y24x6shezhaxqjegegprjp6h8hua2a24lntev22zkxdkhya5u7k6uhenv2jwwf8nddcs99707290u0yw7jv8w500yarnlew75keam9mwejmanardkdpk6awxj7ndl9ka35zfvydvfj646fuq7j6zv5uzl3czrw76psrnaudu2d65mtez7m9sz9xat52s87v6vmlpmknvju0u4wq5kklflwuamnaczl8vkne284ehyamaaxuzkcdvpjg3tlt7cxhy0r6fammc0arha65nxcv7kpxmra5zck7emrn7v4teuk6473eh7l39mqp5zafdmygm0tf0hp2ug20fhk7mlkmve4atg76xv9mw0xe2ped72mvkqall4hstp0a9jsxyyasz6dl7zmka2kwfx94w0knut43r4x447w3shmw5alldevrdu2gthelcjt8h6775p92ktlmlg846varj62rghj67e2hyhlauwkkv6nhnvt7wm6tt2kh2xw6kze0ttxsqplfct7mk4jvnykm0arw2juvnmkudgyerj59dn4ja8r5avud67zd7mr2cl54skynhs4twu2qgwrcdzcchhfee008e30yazzwu96h2uhaprejkrgns5w8nds244k3uyfhtmmzne29hmmdsvvlrtr02w0nc0thtkpywwmmxuqfc0tsssdflned"  # noqa: E501
            },
        )
    with pytest.raises(ValueError, match="Old offer format is no longer supported"):
        await wallet_1_rpc.fetch(
            "check_offer_validity",
            {
                "offer": "offer1qqr83wcuu2rykcmqvpsxygqq0qthwpmsrsutadthxda7ppk8wemm74e88h2dh265k7fv7kdk2etmg99xpm0yu8ddl4rkhl73mflmfasl4h75w6lllup4t7urp0mstehm8cnmc6mdxn0rvdejdfpway2ccm6srenn6urvdmgvand96gat25z42f4u2sh7ad7upvhfty77v6ak76dmrdxrzdgn89mlr58ya6j77yax8095r2u2g826yg9jq4q6xzt4g6yveqnhg6r77lrt3weksdwcwz5ava4t5mtdem5syjejwg53q6t5lfd2t5p6dds9dylj7jxw2fmquugdnkvke5jckmsr8ne4akwha9hv9y24x6shezhaxqjegegprjp6h8hua2a24lntev22zkxdkhya5u7k6uhenv2jwwf8nddcs99707290u0yw7jv8w500yarnlew75keam9mwejmanardkdpk6awxj7ndl9ka35zfvydvfj646fuq7j6zv5uzl3czrw76psrnaudu2d65mtez7m9sz9xat52s87v6vmlpmknvju0u4wq5kklflwuamnaczl8vkne284ehyamaaxuzkcdvpjg3tlt7cxhy0r6fammc0arha65nxcv7kpxmra5zck7emrn7v4teuk6473eh7l39mqp5zafdmygm0tf0hp2ug20fhk7mlkmve4atg76xv9mw0xe2ped72mvkqall4hstp0a9jsxyyasz6dl7zmka2kwfx94w0knut43r4x447w3shmw5alldevrdu2gthelcjt8h6775p92ktlmlg846varj62rghj67e2hyhlauwkkv6nhnvt7wm6tt2kh2xw6kze0ttxsqplfct7mk4jvnykm0arw2juvnmkudgyerj59dn4ja8r5avud67zd7mr2cl54skynhs4twu2qgwrcdzcchhfee008e30yazzwu96h2uhaprejkrgns5w8nds244k3uyfhtmmzne29hmmdsvvlrtr02w0nc0thtkpywwmmxuqfc0tsssdflned"  # noqa: E501
            },
        )
    with pytest.raises(ValueError, match="Old offer format is no longer supported"):
        await wallet_1_rpc.fetch(
            "take_offer",
            {
                "offer": "offer1qqr83wcuu2rykcmqvpsxygqq0qthwpmsrsutadthxda7ppk8wemm74e88h2dh265k7fv7kdk2etmg99xpm0yu8ddl4rkhl73mflmfasl4h75w6lllup4t7urp0mstehm8cnmc6mdxn0rvdejdfpway2ccm6srenn6urvdmgvand96gat25z42f4u2sh7ad7upvhfty77v6ak76dmrdxrzdgn89mlr58ya6j77yax8095r2u2g826yg9jq4q6xzt4g6yveqnhg6r77lrt3weksdwcwz5ava4t5mtdem5syjejwg53q6t5lfd2t5p6dds9dylj7jxw2fmquugdnkvke5jckmsr8ne4akwha9hv9y24x6shezhaxqjegegprjp6h8hua2a24lntev22zkxdkhya5u7k6uhenv2jwwf8nddcs99707290u0yw7jv8w500yarnlew75keam9mwejmanardkdpk6awxj7ndl9ka35zfvydvfj646fuq7j6zv5uzl3czrw76psrnaudu2d65mtez7m9sz9xat52s87v6vmlpmknvju0u4wq5kklflwuamnaczl8vkne284ehyamaaxuzkcdvpjg3tlt7cxhy0r6fammc0arha65nxcv7kpxmra5zck7emrn7v4teuk6473eh7l39mqp5zafdmygm0tf0hp2ug20fhk7mlkmve4atg76xv9mw0xe2ped72mvkqall4hstp0a9jsxyyasz6dl7zmka2kwfx94w0knut43r4x447w3shmw5alldevrdu2gthelcjt8h6775p92ktlmlg846varj62rghj67e2hyhlauwkkv6nhnvt7wm6tt2kh2xw6kze0ttxsqplfct7mk4jvnykm0arw2juvnmkudgyerj59dn4ja8r5avud67zd7mr2cl54skynhs4twu2qgwrcdzcchhfee008e30yazzwu96h2uhaprejkrgns5w8nds244k3uyfhtmmzne29hmmdsvvlrtr02w0nc0thtkpywwmmxuqfc0tsssdflned"  # noqa: E501
            },
        )
    with pytest.raises(ValueError, match="Old offer format is no longer supported"):
        await wallet_1_rpc.fetch(
            "get_offer_summary",
            {
                "offer": "offer1qqqqqqsqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqx68z6sprqv0dvdkvr4rv8r8mwlw7mzuyht6gn74y8yx8ta952h2qqqqqqqqqqqqrls9lllq8ls9lllq8ls9l67lllsflczlllsflllqnlstlllqnll7zllxnlstq8lluz07zllszqgpq8lluz0llczlutl7tuqlllsfl6llllsflllqtljalllqnls9lllqnl30luqszqgplllqnll7qhl9tll7p8lqtll7p8lsgp8llllqnlcyptllllsfluzpdlllqyqszqgpq8lluz0lqdllllsfluzq9llllcyl7pq9lllluz0lqs9llll7p8lsg9llluqszqgpqyqszqgpqyqszq0llcylllsrlllllln63hlqtlnx08lluzqrlcpl7qukqhlllljplczllls8lc9lllsrlczlue0llcylup0llcyluxlllcylllshlmulllshle5lujgplllp0lhelllp0lhelllp0lnflevsrlsnq8llu9l7l8lp0ll7zllxnlcpqyqszq0lqyqszqgplllqy9cplcpsrll7qhlluplllezlllsnlllphlstq8ly2q0llcflllsmlctsrlj9q8llu2l79llluqcrluqsrll7q0lp0lstlctlutcplllq8ls3qyqluqcplllqtll7qllp0ll7q0lqtll7qllluylllczluh0llcylup0llcylufllqyqszq0lqstn7q0llcplup074hlluz07qhlluz0llczluflllcyla0lllcylutlllcyluhlllcyl7qmllllqnlcyqtllllsflcml7qgpqyqszqgpq8lluz0lqsp0llcpqyqszq0llcpluygpq8lqxq0llcplup0llcrlutlllcplup0llcrllljpluph7q0llcpsgqhllllq8ls3qyqluqcplllq8ls3qyqluqcpq8lqxq07p8lluz07p0ly7q0llcylll3plctlatcplmhszq0llllqtll7qllqhll7q0lqtll7qllluylllczllls8lllp8l3rl6csrll7q2el7qgplcpsrll7qvp37q0llcplup07fhlluz07qhlluz07r0lluz07zllluz0llcyl7qmnluzq9ucpluqszqgpqyqlllsrlczlaa0llcylup0llcyllls9lllq0ll7z0lz8l43q8lluql7p8ltrll7p8llup07ahlluz07qhlluz07yllluz0720lluz0llctlu607kuqlllsfletl7qgpqyqszqgpleeszq0llcplup0llcrlllsnlc3laugplllq8ls9lllq0ll7g8llup0llcrlllsnlllqyslllcdlu5cpq8lluql7qhlluplllcflllselefl7q07dyqlawgplllq8lszq0lszq07qvql7qgplcpszq0llcpp8ll7q0lpzqgplcpsrll7qgfsrlsrqyqluqcplllqnll7qhlluplllcflugl7kyqlllszk0lszq07qvqlllsflllqtljdlllqnls9lllqnlsmlllqnlshlllqnl30luqszqgpqyql7qgpqyqszqgplcpsrll7q0lqnlcplllqnlcplchszqgplcpsrll7qhllupl7p0lluql7p8lp8ll7qhl2mll7p8lqtll7p8lphll7p8lp0lcpqyqszqgplllqy9cplcpsrlshlmulllshle5lu5gplllp0lhelllp0lhelllp0lnflevsrlstq8llu9l7l8llup07vhlluz07qhlluz07pllluz0llctlu607dyql7qgpqyqsrll7zllxnlcpqyqszq0llczllls8lllqllstq8lluql7zllluqs9lllqtljalllqnls9lllqnlsnluqszqgplllqtljalllqnls9lllqnlsmluqszqgpq8lluql7zllluqsrlc9szq07qvqlllsflllqnlnplllqnl4lluqszq0llczlal0llcylup0llcylllsflllqnljllc9srll7p8ltllcyqtlszq0llcyllls9lexlllsflczlllsflctlllsflc9lllsrluqszqgpqyqlllsflchlllsfluphlll7p8lsgqhllllqnll7qhl9tll7p8lqtll7p8lsgz0llllqnll7qhlwmll7p8lqtll7p8lp8ll7p8lsg90llllqnll7zllxnljmq8lluz0790lszqgpqyqszq0llcyl7ppdlllszqgpqyqsrll7p8lsgzlllllqnlcyzlll7qgpqyqszqgpqyqszqgplczlad0llcylup0llcyla0lllcylualllcyllls9lllq0l30lllq8lsnledllls9le2lllsflczlllsfle8lllsflllqtlhdlllqnls9lllqnljnlllqnl40lllqnll7zllxnlcrwvqlllsfl6el7qgpqyqszqgplllqnlcrdllszqgpqyqszq0lqyqluqcplllqnl30lllqnlstlllqnlcyqhllllsflllqnll7p8l0rll7p8llu807h8llup07thlluz07qhlluz0llcyluhlllcyl7pqzlllszqgpluqszqgpq8lszqgplllqnll7p8lyrll7p8llu9llqdllaw0llczluh0llcylup0llcylllsflc4lllsflllzrlcyqtllll3rluzqt0l72uql7pq9luql7qgpq8lszqgpqyql7qgpq8lzwqgpluqszqgpqyqszqgpq8lqxqgplllqnll7qdqx7l0xc8wskqn8d5at9dfqmwyt5q675phnkk4zh4e2x9tklqa9fa0llcylllsrgqn55h9a7c7aq9zfj2tx6aa5268xz2r2ds5emgu9yut5hhkp96rrmll7p8lluql7qhlluql7qhlptll7p8lqtll7p8lq0lcpqyqsrll7p8lluqlllen8mll7qhllupl7p0lluql7p8lluz07r8lluz0llczlu00llcylup0llcyluyllqyqszq0lqyqsrll7qhlzmll7p8lqtll7p8lr8ll7p8llup07zhlluz07qhlluz07r0lszqgpq8lszqgpqyqsrlcpq8lqxq0llczllls8lc9lllsrlcylllsflcgluycplllqtl3dlllqnls9lllqnlsmlllqnlshluqszqgpqyqlllszzuqluqcplczllls8lllqllstq8lluql7zllluqs9lllqtl3alllqnls9lllqnlsnluqszqgplllqtl3alllqnls9lllqnlsmluqszqgpq8lluql7zllluqsrlc9szq07qvqluqcpq8lqxqgpqyqlll6pm3jc0w0dpj78zznpvxj057m22f2nk94gc3kus29jvxnefjjd4nklll6qehe6qve5g6r23z4txtrxjqhdg8npntzhw2w8yrkg7y50ksplt32lup0llaqvmuaqxv6ydp4g324n93nfqtk5rese43th98rjpmy0z28mgql4c4gpqyqsq00wsa2002kemp6v5g4avmmdc4edymhaj5vjzvnxuupgu00ufh83e8mt9q2autw93k0a55w5wf5mtdfdaxw9d3fk97dfqhtx8m2d32eqqqqqw3499peelczlllsrlczlllsrlczllls8lctlllsrlczllls8lllp8lstlllrhlshlllrmll7zllp0ll7qhlqmll7p8lqtll7p8lzllcpqyqszqgpqyqlllsrlczlutl7tuqlllsrlcgszq07qvqlllsrlcylllsflcylllsflc9lllsflllqtlsdlllqnls9lllqnl30luqszqgpluqszqgplllqtl30le0szqgplcpsrll7p8lluql7vhlqtll7qlllurl7pvqlllsrlctlllszqhllup07phlluz07qhlluz07z0lszqgpq8llup07phlluz07qhlluz07r0lszqgpqyqlllsrlctlllszq0lqkqgplcpsrlsrqyqlllsflllqxcgqwvaass7c74kdmgtgwq3v5kzcf7pdchnqjuw9yqd0agsgjr8tmua30nshgv7ddn8t3xehd0htnk5luqcpq8lsrll7q0lluellg96ufqk9maa268cn0r6xsre3fs33hcp384eu0uxj77w5fa0n8u008lsrq8lluellgyyddvdkw7jgeu9ugpwah0mk34v4un87qgnqaphe48qss0nmf637mlc2w3499pe4q8llu607qvqlllnelaqhyk2jzy6hxkmuzskhzpz5m6mwylj0h0akznfr3r7sw0e9n8ka2ycplll8ll6pp0j4c0pkvfpy06hd4gelhdvdp3798ghlx6m6eawkk5f4dcazw5cszq0lqyq5xlm42y5nv02th262u6tkmtmrq28nggx4mgvj35gewqav8wcn28jfgtphpthhwrs2pqys2s8zmwv6pur6s6vtyytar26hgp0tgcrc2xg0cxkqdfx3zyyckk769hp4p5dmvcfshc9a4j7feww6uvqc2mthvez7ttx"  # noqa: E501
            },
        )
    with pytest.raises(ValueError, match="Old offer format is no longer supported"):
        await wallet_1_rpc.fetch(
            "check_offer_validity",
            {
                "offer": "offer1qqqqqqsqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqx68z6sprqv0dvdkvr4rv8r8mwlw7mzuyht6gn74y8yx8ta952h2qqqqqqqqqqqqrls9lllq8ls9lllq8ls9l67lllsflczlllsflllqnlstlllqnll7zllxnlstq8lluz07zllszqgpq8lluz0llczlutl7tuqlllsfl6llllsflllqtljalllqnls9lllqnl30luqszqgplllqnll7qhl9tll7p8lqtll7p8lsgp8llllqnlcyptllllsfluzpdlllqyqszqgpq8lluz0lqdllllsfluzq9llllcyl7pq9lllluz0lqs9llll7p8lsg9llluqszqgpqyqszqgpqyqszq0llcylllsrlllllln63hlqtlnx08lluzqrlcpl7qukqhlllljplczllls8lc9lllsrlczlue0llcylup0llcyluxlllcylllshlmulllshle5lujgplllp0lhelllp0lhelllp0lnflevsrlsnq8llu9l7l8lp0ll7zllxnlcpqyqszq0lqyqszqgplllqy9cplcpsrll7qhlluplllezlllsnlllphlstq8ly2q0llcflllsmlctsrlj9q8llu2l79llluqcrluqsrll7q0lp0lstlctlutcplllq8ls3qyqluqcplllqtll7qllp0ll7q0lqtll7qllluylllczluh0llcylup0llcylufllqyqszq0lqstn7q0llcplup074hlluz07qhlluz0llczluflllcyla0lllcylutlllcyluhlllcyl7qmllllqnlcyqtllllsflcml7qgpqyqszqgpq8lluz0lqsp0llcpqyqszq0llcpluygpq8lqxq0llcplup0llcrlutlllcplup0llcrllljpluph7q0llcpsgqhllllq8ls3qyqluqcplllq8ls3qyqluqcpq8lqxq07p8lluz07p0ly7q0llcylll3plctlatcplmhszq0llllqtll7qllqhll7q0lqtll7qllluylllczllls8lllp8l3rl6csrll7q2el7qgplcpsrll7qvp37q0llcplup07fhlluz07qhlluz07r0lluz07zllluz0llcyl7qmnluzq9ucpluqszqgpqyqlllsrlczlaa0llcylup0llcyllls9lllq0ll7z0lz8l43q8lluql7p8ltrll7p8llup07ahlluz07qhlluz07yllluz0720lluz0llctlu607kuqlllsfletl7qgpqyqszqgpleeszq0llcplup0llcrlllsnlc3laugplllq8ls9lllq0ll7g8llup0llcrlllsnlllqyslllcdlu5cpq8lluql7qhlluplllcflllselefl7q07dyqlawgplllq8lszq0lszq07qvql7qgplcpszq0llcpp8ll7q0lpzqgplcpsrll7qgfsrlsrqyqluqcplllqnll7qhlluplllcflugl7kyqlllszk0lszq07qvqlllsflllqtljdlllqnls9lllqnlsmlllqnlshlllqnl30luqszqgpqyql7qgpqyqszqgplcpsrll7q0lqnlcplllqnlcplchszqgplcpsrll7qhllupl7p0lluql7p8lp8ll7qhl2mll7p8lqtll7p8lphll7p8lp0lcpqyqszqgplllqy9cplcpsrlshlmulllshle5lu5gplllp0lhelllp0lhelllp0lnflevsrlstq8llu9l7l8llup07vhlluz07qhlluz07pllluz0llctlu607dyql7qgpqyqsrll7zllxnlcpqyqszq0llczllls8lllqllstq8lluql7zllluqs9lllqtljalllqnls9lllqnlsnluqszqgplllqtljalllqnls9lllqnlsmluqszqgpq8lluql7zllluqsrlc9szq07qvqlllsflllqnlnplllqnl4lluqszq0llczlal0llcylup0llcylllsflllqnljllc9srll7p8ltllcyqtlszq0llcyllls9lexlllsflczlllsflctlllsflc9lllsrluqszqgpqyqlllsflchlllsfluphlll7p8lsgqhllllqnll7qhl9tll7p8lqtll7p8lsgz0llllqnll7qhlwmll7p8lqtll7p8lp8ll7p8lsg90llllqnll7zllxnljmq8lluz0790lszqgpqyqszq0llcyl7ppdlllszqgpqyqsrll7p8lsgzlllllqnlcyzlll7qgpqyqszqgpqyqszqgplczlad0llcylup0llcyla0lllcylualllcyllls9lllq0l30lllq8lsnledllls9le2lllsflczlllsfle8lllsflllqtlhdlllqnls9lllqnljnlllqnl40lllqnll7zllxnlcrwvqlllsfl6el7qgpqyqszqgplllqnlcrdllszqgpqyqszq0lqyqluqcplllqnl30lllqnlstlllqnlcyqhllllsflllqnll7p8l0rll7p8llu807h8llup07thlluz07qhlluz0llcyluhlllcyl7pqzlllszqgpluqszqgpq8lszqgplllqnll7p8lyrll7p8llu9llqdllaw0llczluh0llcylup0llcylllsflc4lllsflllzrlcyqtllll3rluzqt0l72uql7pq9luql7qgpq8lszqgpqyql7qgpq8lzwqgpluqszqgpqyqszqgpq8lqxqgplllqnll7qdqx7l0xc8wskqn8d5at9dfqmwyt5q675phnkk4zh4e2x9tklqa9fa0llcylllsrgqn55h9a7c7aq9zfj2tx6aa5268xz2r2ds5emgu9yut5hhkp96rrmll7p8lluql7qhlluql7qhlptll7p8lqtll7p8lq0lcpqyqsrll7p8lluqlllen8mll7qhllupl7p0lluql7p8lluz07r8lluz0llczlu00llcylup0llcyluyllqyqszq0lqyqsrll7qhlzmll7p8lqtll7p8lr8ll7p8llup07zhlluz07qhlluz07r0lszqgpq8lszqgpqyqsrlcpq8lqxq0llczllls8lc9lllsrlcylllsflcgluycplllqtl3dlllqnls9lllqnlsmlllqnlshluqszqgpqyqlllszzuqluqcplczllls8lllqllstq8lluql7zllluqs9lllqtl3alllqnls9lllqnlsnluqszqgplllqtl3alllqnls9lllqnlsmluqszqgpq8lluql7zllluqsrlc9szq07qvqluqcpq8lqxqgpqyqlll6pm3jc0w0dpj78zznpvxj057m22f2nk94gc3kus29jvxnefjjd4nklll6qehe6qve5g6r23z4txtrxjqhdg8npntzhw2w8yrkg7y50ksplt32lup0llaqvmuaqxv6ydp4g324n93nfqtk5rese43th98rjpmy0z28mgql4c4gpqyqsq00wsa2002kemp6v5g4avmmdc4edymhaj5vjzvnxuupgu00ufh83e8mt9q2autw93k0a55w5wf5mtdfdaxw9d3fk97dfqhtx8m2d32eqqqqqw3499peelczlllsrlczlllsrlczllls8lctlllsrlczllls8lllp8lstlllrhlshlllrmll7zllp0ll7qhlqmll7p8lqtll7p8lzllcpqyqszqgpqyqlllsrlczlutl7tuqlllsrlcgszq07qvqlllsrlcylllsflcylllsflc9lllsflllqtlsdlllqnls9lllqnl30luqszqgpluqszqgplllqtl30le0szqgplcpsrll7p8lluql7vhlqtll7qlllurl7pvqlllsrlctlllszqhllup07phlluz07qhlluz07z0lszqgpq8llup07phlluz07qhlluz07r0lszqgpqyqlllsrlctlllszq0lqkqgplcpsrlsrqyqlllsflllqxcgqwvaass7c74kdmgtgwq3v5kzcf7pdchnqjuw9yqd0agsgjr8tmua30nshgv7ddn8t3xehd0htnk5luqcpq8lsrll7q0lluellg96ufqk9maa268cn0r6xsre3fs33hcp384eu0uxj77w5fa0n8u008lsrq8lluellgyyddvdkw7jgeu9ugpwah0mk34v4un87qgnqaphe48qss0nmf637mlc2w3499pe4q8llu607qvqlllnelaqhyk2jzy6hxkmuzskhzpz5m6mwylj0h0akznfr3r7sw0e9n8ka2ycplll8ll6pp0j4c0pkvfpy06hd4gelhdvdp3798ghlx6m6eawkk5f4dcazw5cszq0lqyq5xlm42y5nv02th262u6tkmtmrq28nggx4mgvj35gewqav8wcn28jfgtphpthhwrs2pqys2s8zmwv6pur6s6vtyytar26hgp0tgcrc2xg0cxkqdfx3zyyckk769hp4p5dmvcfshc9a4j7feww6uvqc2mthvez7ttx"  # noqa: E501
            },
        )
    with pytest.raises(ValueError, match="Old offer format is no longer supported"):
        await wallet_1_rpc.fetch(
            "take_offer",
            {
                "offer": "offer1qqqqqqsqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqx68z6sprqv0dvdkvr4rv8r8mwlw7mzuyht6gn74y8yx8ta952h2qqqqqqqqqqqqrls9lllq8ls9lllq8ls9l67lllsflczlllsflllqnlstlllqnll7zllxnlstq8lluz07zllszqgpq8lluz0llczlutl7tuqlllsfl6llllsflllqtljalllqnls9lllqnl30luqszqgplllqnll7qhl9tll7p8lqtll7p8lsgp8llllqnlcyptllllsfluzpdlllqyqszqgpq8lluz0lqdllllsfluzq9llllcyl7pq9lllluz0lqs9llll7p8lsg9llluqszqgpqyqszqgpqyqszq0llcylllsrlllllln63hlqtlnx08lluzqrlcpl7qukqhlllljplczllls8lc9lllsrlczlue0llcylup0llcyluxlllcylllshlmulllshle5lujgplllp0lhelllp0lhelllp0lnflevsrlsnq8llu9l7l8lp0ll7zllxnlcpqyqszq0lqyqszqgplllqy9cplcpsrll7qhlluplllezlllsnlllphlstq8ly2q0llcflllsmlctsrlj9q8llu2l79llluqcrluqsrll7q0lp0lstlctlutcplllq8ls3qyqluqcplllqtll7qllp0ll7q0lqtll7qllluylllczluh0llcylup0llcylufllqyqszq0lqstn7q0llcplup074hlluz07qhlluz0llczluflllcyla0lllcylutlllcyluhlllcyl7qmllllqnlcyqtllllsflcml7qgpqyqszqgpq8lluz0lqsp0llcpqyqszq0llcpluygpq8lqxq0llcplup0llcrlutlllcplup0llcrllljpluph7q0llcpsgqhllllq8ls3qyqluqcplllq8ls3qyqluqcpq8lqxq07p8lluz07p0ly7q0llcylll3plctlatcplmhszq0llllqtll7qllqhll7q0lqtll7qllluylllczllls8lllp8l3rl6csrll7q2el7qgplcpsrll7qvp37q0llcplup07fhlluz07qhlluz07r0lluz07zllluz0llcyl7qmnluzq9ucpluqszqgpqyqlllsrlczlaa0llcylup0llcyllls9lllq0ll7z0lz8l43q8lluql7p8ltrll7p8llup07ahlluz07qhlluz07yllluz0720lluz0llctlu607kuqlllsfletl7qgpqyqszqgpleeszq0llcplup0llcrlllsnlc3laugplllq8ls9lllq0ll7g8llup0llcrlllsnlllqyslllcdlu5cpq8lluql7qhlluplllcflllselefl7q07dyqlawgplllq8lszq0lszq07qvql7qgplcpszq0llcpp8ll7q0lpzqgplcpsrll7qgfsrlsrqyqluqcplllqnll7qhlluplllcflugl7kyqlllszk0lszq07qvqlllsflllqtljdlllqnls9lllqnlsmlllqnlshlllqnl30luqszqgpqyql7qgpqyqszqgplcpsrll7q0lqnlcplllqnlcplchszqgplcpsrll7qhllupl7p0lluql7p8lp8ll7qhl2mll7p8lqtll7p8lphll7p8lp0lcpqyqszqgplllqy9cplcpsrlshlmulllshle5lu5gplllp0lhelllp0lhelllp0lnflevsrlstq8llu9l7l8llup07vhlluz07qhlluz07pllluz0llctlu607dyql7qgpqyqsrll7zllxnlcpqyqszq0llczllls8lllqllstq8lluql7zllluqs9lllqtljalllqnls9lllqnlsnluqszqgplllqtljalllqnls9lllqnlsmluqszqgpq8lluql7zllluqsrlc9szq07qvqlllsflllqnlnplllqnl4lluqszq0llczlal0llcylup0llcylllsflllqnljllc9srll7p8ltllcyqtlszq0llcyllls9lexlllsflczlllsflctlllsflc9lllsrluqszqgpqyqlllsflchlllsfluphlll7p8lsgqhllllqnll7qhl9tll7p8lqtll7p8lsgz0llllqnll7qhlwmll7p8lqtll7p8lp8ll7p8lsg90llllqnll7zllxnljmq8lluz0790lszqgpqyqszq0llcyl7ppdlllszqgpqyqsrll7p8lsgzlllllqnlcyzlll7qgpqyqszqgpqyqszqgplczlad0llcylup0llcyla0lllcylualllcyllls9lllq0l30lllq8lsnledllls9le2lllsflczlllsfle8lllsflllqtlhdlllqnls9lllqnljnlllqnl40lllqnll7zllxnlcrwvqlllsfl6el7qgpqyqszqgplllqnlcrdllszqgpqyqszq0lqyqluqcplllqnl30lllqnlstlllqnlcyqhllllsflllqnll7p8l0rll7p8llu807h8llup07thlluz07qhlluz0llcyluhlllcyl7pqzlllszqgpluqszqgpq8lszqgplllqnll7p8lyrll7p8llu9llqdllaw0llczluh0llcylup0llcylllsflc4lllsflllzrlcyqtllll3rluzqt0l72uql7pq9luql7qgpq8lszqgpqyql7qgpq8lzwqgpluqszqgpqyqszqgpq8lqxqgplllqnll7qdqx7l0xc8wskqn8d5at9dfqmwyt5q675phnkk4zh4e2x9tklqa9fa0llcylllsrgqn55h9a7c7aq9zfj2tx6aa5268xz2r2ds5emgu9yut5hhkp96rrmll7p8lluql7qhlluql7qhlptll7p8lqtll7p8lq0lcpqyqsrll7p8lluqlllen8mll7qhllupl7p0lluql7p8lluz07r8lluz0llczlu00llcylup0llcyluyllqyqszq0lqyqsrll7qhlzmll7p8lqtll7p8lr8ll7p8llup07zhlluz07qhlluz07r0lszqgpq8lszqgpqyqsrlcpq8lqxq0llczllls8lc9lllsrlcylllsflcgluycplllqtl3dlllqnls9lllqnlsmlllqnlshluqszqgpqyqlllszzuqluqcplczllls8lllqllstq8lluql7zllluqs9lllqtl3alllqnls9lllqnlsnluqszqgplllqtl3alllqnls9lllqnlsmluqszqgpq8lluql7zllluqsrlc9szq07qvqluqcpq8lqxqgpqyqlll6pm3jc0w0dpj78zznpvxj057m22f2nk94gc3kus29jvxnefjjd4nklll6qehe6qve5g6r23z4txtrxjqhdg8npntzhw2w8yrkg7y50ksplt32lup0llaqvmuaqxv6ydp4g324n93nfqtk5rese43th98rjpmy0z28mgql4c4gpqyqsq00wsa2002kemp6v5g4avmmdc4edymhaj5vjzvnxuupgu00ufh83e8mt9q2autw93k0a55w5wf5mtdfdaxw9d3fk97dfqhtx8m2d32eqqqqqw3499peelczlllsrlczlllsrlczllls8lctlllsrlczllls8lllp8lstlllrhlshlllrmll7zllp0ll7qhlqmll7p8lqtll7p8lzllcpqyqszqgpqyqlllsrlczlutl7tuqlllsrlcgszq07qvqlllsrlcylllsflcylllsflc9lllsflllqtlsdlllqnls9lllqnl30luqszqgpluqszqgplllqtl30le0szqgplcpsrll7p8lluql7vhlqtll7qlllurl7pvqlllsrlctlllszqhllup07phlluz07qhlluz07z0lszqgpq8llup07phlluz07qhlluz07r0lszqgpqyqlllsrlctlllszq0lqkqgplcpsrlsrqyqlllsflllqxcgqwvaass7c74kdmgtgwq3v5kzcf7pdchnqjuw9yqd0agsgjr8tmua30nshgv7ddn8t3xehd0htnk5luqcpq8lsrll7q0lluellg96ufqk9maa268cn0r6xsre3fs33hcp384eu0uxj77w5fa0n8u008lsrq8lluellgyyddvdkw7jgeu9ugpwah0mk34v4un87qgnqaphe48qss0nmf637mlc2w3499pe4q8llu607qvqlllnelaqhyk2jzy6hxkmuzskhzpz5m6mwylj0h0akznfr3r7sw0e9n8ka2ycplll8ll6pp0j4c0pkvfpy06hd4gelhdvdp3798ghlx6m6eawkk5f4dcazw5cszq0lqyq5xlm42y5nv02th262u6tkmtmrq28nggx4mgvj35gewqav8wcn28jfgtphpthhwrs2pqys2s8zmwv6pur6s6vtyytar26hgp0tgcrc2xg0cxkqdfx3zyyckk769hp4p5dmvcfshc9a4j7feww6uvqc2mthvez7ttx"  # noqa: E501
            },
        )
    ###

    await wallet_1_rpc.create_offer_for_ids(
        {uint32(1): -5, cat_asset_id.hex(): 1},
        DEFAULT_TX_CONFIG,
        driver_dict=driver_dict,
    )
    assert len([o for o in await wallet_1_rpc.get_all_offers() if o.status == TradeStatus.PENDING_ACCEPT.value]) == 2
    await wallet_1_rpc.cancel_offers(DEFAULT_TX_CONFIG, batch_size=1)
    assert len([o for o in await wallet_1_rpc.get_all_offers() if o.status == TradeStatus.PENDING_ACCEPT.value]) == 0
    await time_out_assert(5, check_mempool_spend_count, True, full_node_api, 2)

    await farm_transaction_block(full_node_api, wallet_node)

    await wallet_1_rpc.create_offer_for_ids(
        {uint32(1): -5, cat_asset_id.hex(): 1},
        DEFAULT_TX_CONFIG,
        driver_dict=driver_dict,
    )
    await wallet_1_rpc.create_offer_for_ids(
        {uint32(1): 5, cat_asset_id.hex(): -1},
        DEFAULT_TX_CONFIG,
        driver_dict=driver_dict,
    )
    assert len([o for o in await wallet_1_rpc.get_all_offers() if o.status == TradeStatus.PENDING_ACCEPT.value]) == 2
    await wallet_1_rpc.cancel_offers(DEFAULT_TX_CONFIG, cancel_all=True)
    assert len([o for o in await wallet_1_rpc.get_all_offers() if o.status == TradeStatus.PENDING_ACCEPT.value]) == 0
    await time_out_assert(5, check_mempool_spend_count, True, full_node_api, 1)
    await farm_transaction_block(full_node_api, wallet_node)

    await wallet_1_rpc.create_offer_for_ids(
        {uint32(1): 5, cat_asset_id.hex(): -1},
        DEFAULT_TX_CONFIG,
        driver_dict=driver_dict,
    )
    assert len([o for o in await wallet_1_rpc.get_all_offers() if o.status == TradeStatus.PENDING_ACCEPT.value]) == 1
    await wallet_1_rpc.cancel_offers(DEFAULT_TX_CONFIG, asset_id=bytes32([0] * 32))
    assert len([o for o in await wallet_1_rpc.get_all_offers() if o.status == TradeStatus.PENDING_ACCEPT.value]) == 1
    await wallet_1_rpc.cancel_offers(DEFAULT_TX_CONFIG, asset_id=cat_asset_id)
    assert len([o for o in await wallet_1_rpc.get_all_offers() if o.status == TradeStatus.PENDING_ACCEPT.value]) == 0
    await time_out_assert(5, check_mempool_spend_count, True, full_node_api, 1)

    with pytest.raises(ValueError, match="not currently supported"):
        await wallet_1_rpc.create_offer_for_ids(
            {uint32(1): -5, cat_asset_id.hex(): 1},
            DEFAULT_TX_CONFIG,
            driver_dict=driver_dict,
            timelock_info=ConditionValidTimes(min_secs_since_created=uint64(1)),
        )


@pytest.mark.anyio
async def test_get_coin_records_by_names(wallet_rpc_environment: WalletRpcTestEnvironment) -> None:
    env: WalletRpcTestEnvironment = wallet_rpc_environment
    wallet_node: WalletNode = env.wallet_1.node
    client: WalletRpcClient = env.wallet_1.rpc_client
    store = wallet_node.wallet_state_manager.coin_store
    full_node_api = env.full_node.api
    # Generate some funds
    generated_funds = await generate_funds(full_node_api, env.wallet_1, 5)
    address = encode_puzzle_hash(await env.wallet_1.wallet.get_new_puzzlehash(), "txch")
    await full_node_api.wait_for_wallet_synced(wallet_node=wallet_node, timeout=20)

    # Spend half of it back to the same wallet get some spent coins in the wallet
    tx = (await client.send_transaction(1, uint64(generated_funds / 2), address, DEFAULT_TX_CONFIG)).transaction
    assert tx.spend_bundle is not None
    await time_out_assert(20, tx_in_mempool, True, client, tx.name)
    await farm_transaction(full_node_api, wallet_node, tx.spend_bundle)
    await full_node_api.wait_for_wallet_synced(wallet_node=wallet_node, timeout=5)
    # Prepare some records and parameters first
    result = await store.get_coin_records()
    coins = {record.coin for record in result.records}
    coins_unspent = {record.coin for record in result.records if not record.spent}
    coin_ids = [coin.name() for coin in coins]
    coin_ids_unspent = [coin.name() for coin in coins_unspent]
    assert len(coin_ids) > 0
    assert len(coin_ids_unspent) > 0
    # Do some queries to trigger all parameters
    # 1. Empty coin_ids
    assert await client.get_coin_records_by_names([]) == []
    # 2. All coins
    rpc_result = await client.get_coin_records_by_names(coin_ids + coin_ids_unspent)
    assert {record.coin for record in rpc_result} == {*coins, *coins_unspent}
    # 3. All spent coins
    rpc_result = await client.get_coin_records_by_names(coin_ids, include_spent_coins=True)
    assert {record.coin for record in rpc_result} == coins
    # 4. All unspent coins
    rpc_result = await client.get_coin_records_by_names(coin_ids_unspent, include_spent_coins=False)
    assert {record.coin for record in rpc_result} == coins_unspent
    # 5. Filter start/end height
    filter_records = result.records[:10]
    assert len(filter_records) == 10
    filter_coin_ids = [record.name() for record in filter_records]
    filter_coins = {record.coin for record in filter_records}
    min_height = min(record.confirmed_block_height for record in filter_records)
    max_height = max(record.confirmed_block_height for record in filter_records)
    assert min_height != max_height
    rpc_result = await client.get_coin_records_by_names(filter_coin_ids, start_height=min_height, end_height=max_height)
    assert {record.coin for record in rpc_result} == filter_coins
    # 8. Test the failure case
    with pytest.raises(ValueError, match="not found"):
        await client.get_coin_records_by_names(coin_ids, include_spent_coins=False)


@pytest.mark.anyio
async def test_did_endpoints(wallet_rpc_environment: WalletRpcTestEnvironment):
    env: WalletRpcTestEnvironment = wallet_rpc_environment

    wallet_1: Wallet = env.wallet_1.wallet
    wallet_2: Wallet = env.wallet_2.wallet
    wallet_1_node: WalletNode = env.wallet_1.node
    wallet_2_node: WalletNode = env.wallet_2.node
    wallet_1_rpc: WalletRpcClient = env.wallet_1.rpc_client
    wallet_2_rpc: WalletRpcClient = env.wallet_2.rpc_client
    full_node_api: FullNodeSimulator = env.full_node.api
    wallet_1_id = wallet_1.id()

    await generate_funds(env.full_node.api, env.wallet_1, 5)

    # Create a DID wallet
    res = await wallet_1_rpc.create_new_did_wallet(amount=1, tx_config=DEFAULT_TX_CONFIG, name="Profile 1")
    assert res["success"]
    did_wallet_id_0 = res["wallet_id"]
    did_id_0 = res["my_did"]

    # Get wallet name
    res = await wallet_1_rpc.did_get_wallet_name(did_wallet_id_0)
    assert res["success"]
    assert res["name"] == "Profile 1"
    nft_wallet: WalletProtocol = wallet_1_node.wallet_state_manager.wallets[did_wallet_id_0 + 1]
    assert isinstance(nft_wallet, NFTWallet)
    assert nft_wallet.get_name() == "Profile 1 NFT Wallet"

    # Set wallet name
    new_wallet_name = "test name"
    res = await wallet_1_rpc.did_set_wallet_name(did_wallet_id_0, new_wallet_name)
    assert res["success"]
    res = await wallet_1_rpc.did_get_wallet_name(did_wallet_id_0)
    assert res["success"]
    assert res["name"] == new_wallet_name
    with pytest.raises(ValueError, match="wallet id 1 is of type Wallet but type DIDWallet is required"):
        await wallet_1_rpc.did_set_wallet_name(wallet_1_id, new_wallet_name)

    # Check DID ID
    res = await wallet_1_rpc.get_did_id(did_wallet_id_0)
    assert res["success"]
    assert did_id_0 == res["my_did"]
    # Create backup file
    res = await wallet_1_rpc.create_did_backup_file(did_wallet_id_0, "backup.did")
    assert res["success"]

    await time_out_assert(5, check_mempool_spend_count, True, full_node_api, 1)
    await farm_transaction_block(full_node_api, wallet_1_node)
    # Update recovery list
    update_res = await wallet_1_rpc.update_did_recovery_list(did_wallet_id_0, [did_id_0], 1, DEFAULT_TX_CONFIG)
    assert len(update_res.transactions) > 0
    res = await wallet_1_rpc.get_did_recovery_list(did_wallet_id_0)
    assert res["num_required"] == 1
    assert res["recovery_list"][0] == did_id_0

    await time_out_assert(5, check_mempool_spend_count, True, full_node_api, 1)
    await farm_transaction_block(full_node_api, wallet_1_node)

    # Update metadata
    with pytest.raises(ValueError, match="wallet id 1 is of type Wallet but type DIDWallet is required"):
        await wallet_1_rpc.update_did_metadata(wallet_1_id, {"Twitter": "Https://test"}, DEFAULT_TX_CONFIG)
    await wallet_1_rpc.update_did_metadata(did_wallet_id_0, {"Twitter": "Https://test"}, DEFAULT_TX_CONFIG)

    res = await wallet_1_rpc.get_did_metadata(did_wallet_id_0)
    assert res["metadata"]["Twitter"] == "Https://test"

    await time_out_assert(5, check_mempool_spend_count, True, full_node_api, 1)
    await farm_transaction_block(full_node_api, wallet_1_node)

    # Transfer DID
    addr = encode_puzzle_hash(await wallet_2.get_new_puzzlehash(), "txch")
    await wallet_1_rpc.did_transfer_did(did_wallet_id_0, addr, 0, True, DEFAULT_TX_CONFIG)

    await time_out_assert(5, check_mempool_spend_count, True, full_node_api, 1)
    await farm_transaction_block(full_node_api, wallet_1_node)

    async def num_wallets() -> int:
        return len(await wallet_2_node.wallet_state_manager.get_all_wallet_info_entries())

    await time_out_assert(30, num_wallets, 2)

    did_wallets = list(
        filter(
            lambda w: (w.type == WalletType.DECENTRALIZED_ID),
            await wallet_2_node.wallet_state_manager.get_all_wallet_info_entries(),
        )
    )
    did_wallet_2: WalletProtocol = wallet_2_node.wallet_state_manager.wallets[did_wallets[0].id]
    assert isinstance(did_wallet_2, DIDWallet)
    assert (
        encode_puzzle_hash(bytes32.from_hexstr(did_wallet_2.get_my_DID()), AddressType.DID.hrp(wallet_2_node.config))
        == did_id_0
    )
    metadata = json.loads(did_wallet_2.did_info.metadata)
    assert metadata["Twitter"] == "Https://test"

    last_did_coin = await did_wallet_2.get_coin()
    await wallet_2_rpc.did_message_spend(did_wallet_2.id(), DEFAULT_TX_CONFIG, push=True)
    await wallet_2_node.wallet_state_manager.add_interested_coin_ids([last_did_coin.name()])

    await time_out_assert(5, check_mempool_spend_count, True, full_node_api, 1)
    await farm_transaction_block(full_node_api, wallet_2_node)

    next_did_coin = await did_wallet_2.get_coin()
    assert next_did_coin.parent_coin_info == last_did_coin.name()
    last_did_coin = next_did_coin

    await wallet_2_rpc.did_message_spend(did_wallet_2.id(), DEFAULT_TX_CONFIG.override(reuse_puzhash=True), push=True)
    await wallet_2_node.wallet_state_manager.add_interested_coin_ids([last_did_coin.name()])

    await time_out_assert(5, check_mempool_spend_count, True, full_node_api, 1)
    await farm_transaction_block(full_node_api, wallet_2_node)

    next_did_coin = await did_wallet_2.get_coin()
    assert next_did_coin.parent_coin_info == last_did_coin.name()
    assert next_did_coin.puzzle_hash == last_did_coin.puzzle_hash

    # Test did_get_pubkey
    pubkey_res = await wallet_2_rpc.get_did_pubkey(DIDGetPubkey(did_wallet_2.id()))
    assert isinstance(pubkey_res.pubkey, G1Element)


@pytest.mark.anyio
async def test_nft_endpoints(wallet_rpc_environment: WalletRpcTestEnvironment):
    env: WalletRpcTestEnvironment = wallet_rpc_environment
    wallet_1_node: WalletNode = env.wallet_1.node
    wallet_1_rpc: WalletRpcClient = env.wallet_1.rpc_client
    wallet_2: Wallet = env.wallet_2.wallet
    wallet_2_node: WalletNode = env.wallet_2.node
    wallet_2_rpc: WalletRpcClient = env.wallet_2.rpc_client
    full_node_api: FullNodeSimulator = env.full_node.api

    await generate_funds(env.full_node.api, env.wallet_1, 5)

    res = await wallet_1_rpc.create_new_nft_wallet(None)
    nft_wallet_id = res["wallet_id"]
    mint_res = await wallet_1_rpc.mint_nft(
        nft_wallet_id,
        None,
        None,
        "0xD4584AD463139FA8C0D9F68F4B59F185",
        ["https://www.chia.net/img/branding/chia-logo.svg"],
        DEFAULT_TX_CONFIG,
    )

    spend_bundle = mint_res.spend_bundle

    await farm_transaction(full_node_api, wallet_1_node, spend_bundle)

    await full_node_api.wait_for_wallet_synced(wallet_node=wallet_1_node, timeout=15)

    nft_wallet: WalletProtocol = wallet_1_node.wallet_state_manager.wallets[nft_wallet_id]
    assert isinstance(nft_wallet, NFTWallet)

    async def have_nfts():
        return await nft_wallet.get_nft_count() > 0

    await time_out_assert(15, have_nfts, True)

    # Test with the hex version of nft_id
    nft_id = (await nft_wallet.get_current_nfts())[0].coin.name().hex()
    nft_info = (await wallet_1_rpc.get_nft_info(nft_id))["nft_info"]
    assert nft_info["nft_coin_id"][2:] == (await nft_wallet.get_current_nfts())[0].coin.name().hex()
    # Test with the bech32m version of nft_id
    hmr_nft_id = encode_puzzle_hash(
        (await nft_wallet.get_current_nfts())[0].coin.name(), AddressType.NFT.hrp(wallet_1_node.config)
    )
    nft_info = (await wallet_1_rpc.get_nft_info(hmr_nft_id))["nft_info"]
    assert nft_info["nft_coin_id"][2:] == (await nft_wallet.get_current_nfts())[0].coin.name().hex()

    addr = encode_puzzle_hash(await wallet_2.get_new_puzzlehash(), "txch")
    await wallet_1_rpc.transfer_nft(nft_wallet_id, nft_id, addr, 0, DEFAULT_TX_CONFIG)
    await time_out_assert(5, check_mempool_spend_count, True, full_node_api, 1)
    await farm_transaction_block(full_node_api, wallet_1_node)
    await time_out_assert(5, check_mempool_spend_count, True, full_node_api, 0)
    await full_node_api.wait_for_wallet_synced(wallet_node=wallet_1_node, timeout=5)

    await full_node_api.wait_for_wallet_synced(wallet_node=wallet_2_node, timeout=5)

    nft_wallet_id_1 = (
        await wallet_2_node.wallet_state_manager.get_all_wallet_info_entries(wallet_type=WalletType.NFT)
    )[0].id
    nft_wallet_1: WalletProtocol = wallet_2_node.wallet_state_manager.wallets[nft_wallet_id_1]
    assert isinstance(nft_wallet_1, NFTWallet)
    nft_info_1 = (await wallet_1_rpc.get_nft_info(nft_id, False))["nft_info"]
    assert nft_info_1 == nft_info
    nft_info_1 = (await wallet_1_rpc.get_nft_info(nft_id))["nft_info"]
    assert nft_info_1["nft_coin_id"][2:] == (await nft_wallet_1.get_current_nfts())[0].coin.name().hex()
    # Cross-check NFT
    nft_info_2 = (await wallet_2_rpc.list_nfts(nft_wallet_id_1))["nft_list"][0]
    assert nft_info_1 == nft_info_2

    # Test royalty endpoint
    royalty_summary = await wallet_1_rpc.nft_calculate_royalties(
        {
            "my asset": ("my address", uint16(10000)),
        },
        {
            None: uint64(10000),
        },
    )
    assert royalty_summary == {
        "my asset": [
            {
                "asset": None,
                "address": "my address",
                "amount": 10000,
            }
        ],
    }


async def _check_delete_key(
    client: WalletRpcClient, wallet_node: WalletNode, farmer_fp: int, pool_fp: int, observer: bool = False
) -> None:
    # Add in reward addresses into farmer and pool for testing delete key checks
    # set farmer to first private key
    create_sk = master_sk_to_wallet_sk_unhardened if observer else master_sk_to_wallet_sk

    sk = await wallet_node.get_key_for_fingerprint(farmer_fp, private=True)
    assert sk is not None
    farmer_ph = create_puzzlehash_for_pk(create_sk(sk, uint32(0)).get_g1())

    sk = await wallet_node.get_key_for_fingerprint(pool_fp, private=True)
    assert sk is not None
    pool_ph = create_puzzlehash_for_pk(create_sk(sk, uint32(0)).get_g1())

    with lock_and_load_config(wallet_node.root_path, "config.yaml") as test_config:
        test_config["farmer"]["xch_target_address"] = encode_puzzle_hash(farmer_ph, "txch")
        test_config["pool"]["xch_target_address"] = encode_puzzle_hash(pool_ph, "txch")
        save_config(wallet_node.root_path, "config.yaml", test_config)

    # Check farmer_fp key
    sk_dict = await client.check_delete_key(farmer_fp)
    assert sk_dict["fingerprint"] == farmer_fp
    assert sk_dict["used_for_farmer_rewards"] is True
    assert sk_dict["used_for_pool_rewards"] is False

    # Check pool_fp key
    sk_dict = await client.check_delete_key(pool_fp)
    assert sk_dict["fingerprint"] == pool_fp
    assert sk_dict["used_for_farmer_rewards"] is False
    assert sk_dict["used_for_pool_rewards"] is True

    # Check unknown key
    sk_dict = await client.check_delete_key(123456, 10)
    assert sk_dict["fingerprint"] == 123456
    assert sk_dict["used_for_farmer_rewards"] is False
    assert sk_dict["used_for_pool_rewards"] is False


@pytest.mark.anyio
async def test_key_and_address_endpoints(wallet_rpc_environment: WalletRpcTestEnvironment):
    env: WalletRpcTestEnvironment = wallet_rpc_environment

    wallet: Wallet = env.wallet_1.wallet
    wallet_node: WalletNode = env.wallet_1.node
    client: WalletRpcClient = env.wallet_1.rpc_client

    address = await client.get_next_address(1, True)
    assert len(address) > 10

    pks = await client.get_public_keys()
    assert len(pks) == 1

    await generate_funds(env.full_node.api, env.wallet_1)

    assert (await client.get_height_info()) > 0

    ph = await wallet.get_new_puzzlehash()
    addr = encode_puzzle_hash(ph, "txch")
    tx_amount = uint64(15600000)
    await env.full_node.api.wait_for_wallet_synced(wallet_node=wallet_node, timeout=20)
    created_tx = (await client.send_transaction(1, tx_amount, addr, DEFAULT_TX_CONFIG)).transaction

    await time_out_assert(20, tx_in_mempool, True, client, created_tx.name)
    assert len(await wallet.wallet_state_manager.tx_store.get_unconfirmed_for_wallet(1)) == 1
    await client.delete_unconfirmed_transactions(1)
    assert len(await wallet.wallet_state_manager.tx_store.get_unconfirmed_for_wallet(1)) == 0

    sk_dict = await client.get_private_key(pks[0])
    assert sk_dict["fingerprint"] == pks[0]
    assert sk_dict["sk"] is not None
    assert sk_dict["pk"] is not None
    assert sk_dict["seed"] is not None

    mnemonic = await client.generate_mnemonic()
    assert len(mnemonic) == 24

    await client.add_key(mnemonic)

    pks = await client.get_public_keys()
    assert len(pks) == 2

    await client.log_in(pks[1])
    sk_dict = await client.get_private_key(pks[1])
    assert sk_dict["fingerprint"] == pks[1]

    # test hardened keys
    await _check_delete_key(client=client, wallet_node=wallet_node, farmer_fp=pks[0], pool_fp=pks[1], observer=False)

    # test observer keys
    await _check_delete_key(client=client, wallet_node=wallet_node, farmer_fp=pks[0], pool_fp=pks[1], observer=True)

    # set farmer to empty string
    with lock_and_load_config(wallet_node.root_path, "config.yaml") as test_config:
        test_config["farmer"]["xch_target_address"] = ""
        save_config(wallet_node.root_path, "config.yaml", test_config)

    # Check key
    sk_dict = await client.check_delete_key(pks[1])
    assert sk_dict["fingerprint"] == pks[1]
    assert sk_dict["used_for_farmer_rewards"] is False
    assert sk_dict["used_for_pool_rewards"] is True

    # set farmer and pool to empty string
    with lock_and_load_config(wallet_node.root_path, "config.yaml") as test_config:
        test_config["farmer"]["xch_target_address"] = ""
        test_config["pool"]["xch_target_address"] = ""
        save_config(wallet_node.root_path, "config.yaml", test_config)

    # Check key
    sk_dict = await client.check_delete_key(pks[0])
    assert sk_dict["fingerprint"] == pks[0]
    assert sk_dict["used_for_farmer_rewards"] is False
    assert sk_dict["used_for_pool_rewards"] is False

    await client.delete_key(pks[0])
    await client.log_in(pks[1])
    assert len(await client.get_public_keys()) == 1

    assert not (await client.get_sync_status())

    wallets = await client.get_wallets()
    assert len(wallets) == 1
    assert await get_unconfirmed_balance(client, int(wallets[0]["id"])) == 0

    with pytest.raises(ValueError):
        await client.send_transaction(wallets[0]["id"], uint64(100), addr, DEFAULT_TX_CONFIG)

    # Delete all keys
    await client.delete_all_keys()
    assert len(await client.get_public_keys()) == 0


@pytest.mark.anyio
async def test_select_coins_rpc(wallet_rpc_environment: WalletRpcTestEnvironment):
    env: WalletRpcTestEnvironment = wallet_rpc_environment

    wallet_2: Wallet = env.wallet_2.wallet
    wallet_node: WalletNode = env.wallet_1.node
    full_node_api: FullNodeSimulator = env.full_node.api
    client: WalletRpcClient = env.wallet_1.rpc_client
    client_2: WalletRpcClient = env.wallet_2.rpc_client

    funds = await generate_funds(full_node_api, env.wallet_1)

    addr = encode_puzzle_hash(await wallet_2.get_new_puzzlehash(), "txch")
    coin_300: List[Coin]
    tx_amounts: List[uint64] = [uint64(1000), uint64(300), uint64(1000), uint64(1000), uint64(10000)]
    for tx_amount in tx_amounts:
        funds -= tx_amount
        # create coins for tests
        tx = (await client.send_transaction(1, tx_amount, addr, DEFAULT_TX_CONFIG)).transaction
        spend_bundle = tx.spend_bundle
        assert spend_bundle is not None
        for coin in spend_bundle.additions():
            if coin.amount == uint64(300):
                coin_300 = [coin]

        await time_out_assert(20, tx_in_mempool, True, client, tx.name)
        await farm_transaction(full_node_api, wallet_node, spend_bundle)
        await time_out_assert(20, get_confirmed_balance, funds, client, 1)

    # test min coin amount
    min_coins: List[Coin] = await client_2.select_coins(
        amount=1000,
        wallet_id=1,
        coin_selection_config=DEFAULT_COIN_SELECTION_CONFIG.override(min_coin_amount=uint64(1001)),
    )
    assert min_coins is not None
    assert len(min_coins) == 1 and min_coins[0].amount == uint64(10000)

    # test max coin amount
    max_coins: List[Coin] = await client_2.select_coins(
        amount=2000,
        wallet_id=1,
        coin_selection_config=DEFAULT_COIN_SELECTION_CONFIG.override(
            min_coin_amount=uint64(999), max_coin_amount=uint64(9999)
        ),
    )
    assert max_coins is not None
    assert len(max_coins) == 2 and max_coins[0].amount == uint64(1000)

    # test excluded coin amounts
    non_1000_amt: int = sum(a for a in tx_amounts if a != 1000)
    excluded_amt_coins: List[Coin] = await client_2.select_coins(
        amount=non_1000_amt,
        wallet_id=1,
        coin_selection_config=DEFAULT_COIN_SELECTION_CONFIG.override(excluded_coin_amounts=[uint64(1000)]),
    )
    assert excluded_amt_coins is not None
    assert (
        len(excluded_amt_coins) == len(tuple(a for a in tx_amounts if a != 1000))
        and sum(c.amount for c in excluded_amt_coins) == non_1000_amt
    )

    # test excluded coins
    with pytest.raises(ValueError):
        await client_2.select_coins(
            amount=5000,
            wallet_id=1,
            coin_selection_config=DEFAULT_COIN_SELECTION_CONFIG.override(
                excluded_coin_ids=[c.name() for c in min_coins]
            ),
        )
    excluded_test = await client_2.select_coins(
        amount=1300,
        wallet_id=1,
        coin_selection_config=DEFAULT_COIN_SELECTION_CONFIG.override(excluded_coin_ids=[c.name() for c in coin_300]),
    )
    assert len(excluded_test) == 2
    for coin in excluded_test:
        assert coin != coin_300[0]

    # test backwards compatibility in the RPC
    identical_test = (
        await client_2.fetch(
            "select_coins",
            {
                "amount": 1300,
                "wallet_id": 1,
                "exclude_coins": [c.to_json_dict() for c in coin_300],
            },
        )
    )["coins"]
    assert len(identical_test) == 2
    for coin in identical_test:
        assert coin != coin_300[0]

    # test get coins
    all_coins, _, _ = await client_2.get_spendable_coins(
        wallet_id=1,
        coin_selection_config=DEFAULT_COIN_SELECTION_CONFIG.override(
            excluded_coin_ids=[c.name() for c in excluded_amt_coins]
        ),
    )
    assert set(excluded_amt_coins).intersection({rec.coin for rec in all_coins}) == set()
    all_coins, _, _ = await client_2.get_spendable_coins(
        wallet_id=1,
        coin_selection_config=DEFAULT_COIN_SELECTION_CONFIG.override(excluded_coin_amounts=[uint64(1000)]),
    )
    assert len([rec for rec in all_coins if rec.coin.amount == 1000]) == 0
    all_coins_2, _, _ = await client_2.get_spendable_coins(
        wallet_id=1,
        coin_selection_config=DEFAULT_COIN_SELECTION_CONFIG.override(max_coin_amount=uint64(999)),
    )
    assert all_coins_2[0].coin == coin_300[0]
    with pytest.raises(ValueError):  # validate fail on invalid coin id.
        await client_2.get_spendable_coins(
            wallet_id=1,
            coin_selection_config=DEFAULT_COIN_SELECTION_CONFIG.override(excluded_coin_ids=[b"a"]),
        )


@pytest.mark.anyio
async def test_get_coin_records_rpc(wallet_rpc_environment: WalletRpcTestEnvironment) -> None:
    env: WalletRpcTestEnvironment = wallet_rpc_environment
    wallet_node: WalletNode = env.wallet_1.node
    client: WalletRpcClient = env.wallet_1.rpc_client
    store = wallet_node.wallet_state_manager.coin_store

    for record in [record_1, record_2, record_3, record_4, record_5, record_6, record_7, record_8, record_9]:
        await store.add_coin_record(record)

    async def run_test_case(
        test_case: str,
        test_request: GetCoinRecords,
        test_total_count: Optional[int],
        test_records: List[WalletCoinRecord],
    ):
        response = await client.get_coin_records(test_request)
        assert response["coin_records"] == [coin.to_json_dict_parsed_metadata() for coin in test_records], test_case
        assert response["total_count"] == test_total_count, test_case

    for name, tests in {
        "offset_limit": get_coin_records_offset_limit_tests,
        "wallet_id": get_coin_records_wallet_id_tests,
        "wallet_type": get_coin_records_wallet_type_tests,
        "coin_type": get_coin_records_coin_type_tests,
        "coin_id_filter": get_coin_records_coin_id_filter_tests,
        "puzzle_hash_filter": get_coin_records_puzzle_hash_filter_tests,
        "parent_coin_id_filter": get_coin_records_parent_coin_id_filter_tests,
        "amount_filter": get_coin_records_amount_filter_tests,
        "amount_range": get_coin_records_amount_range_tests,
        "confirmed_range": get_coin_records_confirmed_range_tests,
        "spent_range": get_coin_records_spent_range_tests,
        "order": get_coin_records_order_tests,
        "reverse": get_coin_records_reverse_tests,
    }.items():
        for i, (request, expected_records) in enumerate(tests):
            await run_test_case(f"{name}-{i}", request, None, expected_records)

    for name, total_count_tests in {
        "total_count": get_coin_records_include_total_count_tests,
        "mixed": get_coin_records_mixed_tests,
    }.items():
        for i, (request, expected_total_count, expected_records) in enumerate(total_count_tests):
            await run_test_case(f"{name}-{i}", request, expected_total_count, expected_records)


@pytest.mark.anyio
async def test_get_coin_records_rpc_limits(
    wallet_rpc_environment: WalletRpcTestEnvironment,
    seeded_random: random.Random,
) -> None:
    env: WalletRpcTestEnvironment = wallet_rpc_environment
    wallet_node: WalletNode = env.wallet_1.node
    client: WalletRpcClient = env.wallet_1.rpc_client
    rpc_server: Optional[RpcServer] = wallet_rpc_environment.wallet_1.service.rpc_server
    assert rpc_server is not None
    api: WalletRpcApi = cast(WalletRpcApi, rpc_server.rpc_api)
    store = wallet_node.wallet_state_manager.coin_store

    # Adjust the limits for faster testing
    WalletRpcApi.max_get_coin_records_limit = uint32(5)
    WalletRpcApi.max_get_coin_records_filter_items = uint32(5)

    max_coins = api.max_get_coin_records_limit * 10
    coin_records = [
        WalletCoinRecord(
            Coin(bytes32.random(seeded_random), bytes32.random(seeded_random), uint64(seeded_random.randrange(2**64))),
            uint32(seeded_random.randrange(2**32)),
            uint32(0),
            False,
            False,
            WalletType.STANDARD_WALLET,
            uint32(0),
            CoinType.NORMAL,
            None,
        )
        for _ in range(max_coins)
    ]
    for record in coin_records:
        await store.add_coin_record(record)

    limit = api.max_get_coin_records_limit
    response_records = []
    for i in range(int(max_coins / api.max_get_coin_records_limit)):
        offset = uint32(api.max_get_coin_records_limit * i)
        response = await client.get_coin_records(GetCoinRecords(limit=limit, offset=offset, include_total_count=True))
        response_records.extend(list(response["coin_records"]))

    assert len(response_records) == max_coins
    # Make sure we got all expected records
    parsed_records = [coin.to_json_dict_parsed_metadata() for coin in coin_records]
    for expected_record in parsed_records:
        assert expected_record in response_records

    # Request coins with the max number of filter items
    max_filter_items = api.max_get_coin_records_filter_items
    filter_records = coin_records[:max_filter_items]
    coin_id_filter = HashFilter.include([coin.name() for coin in filter_records])
    puzzle_hash_filter = HashFilter.include([coin.coin.puzzle_hash for coin in filter_records])
    parent_coin_id_filter = HashFilter.include([coin.coin.parent_coin_info for coin in filter_records])
    amount_filter = AmountFilter.include([uint64(coin.coin.amount) for coin in coin_records[:max_filter_items]])
    for request in [
        GetCoinRecords(coin_id_filter=coin_id_filter),
        GetCoinRecords(puzzle_hash_filter=puzzle_hash_filter),
        GetCoinRecords(parent_coin_id_filter=parent_coin_id_filter),
        GetCoinRecords(amount_filter=amount_filter),
        GetCoinRecords(
            coin_id_filter=coin_id_filter,
            puzzle_hash_filter=puzzle_hash_filter,
            parent_coin_id_filter=parent_coin_id_filter,
            amount_filter=amount_filter,
        ),
    ]:
        response = await client.get_coin_records(request)
        parsed_records = [coin.to_json_dict_parsed_metadata() for coin in filter_records]
        for expected_record in parsed_records:
            assert expected_record in response["coin_records"]


@pytest.mark.anyio
async def test_get_coin_records_rpc_failures(
    wallet_rpc_environment: WalletRpcTestEnvironment,
    seeded_random: random.Random,
) -> None:
    env: WalletRpcTestEnvironment = wallet_rpc_environment
    client: WalletRpcClient = env.wallet_1.rpc_client
    rpc_server: Optional[RpcServer] = wallet_rpc_environment.wallet_1.service.rpc_server
    assert rpc_server is not None
    api = cast(WalletRpcApi, rpc_server.rpc_api)

    too_many_hashes = [bytes32.random(seeded_random) for _ in range(api.max_get_coin_records_filter_items + 1)]
    too_many_amounts = [
        uint64(uint64(seeded_random.randrange(2**64))) for _ in range(api.max_get_coin_records_filter_items + 1)
    ]
    # Run requests which exceeds the allowed limit and contain too much filter items
    for name, request in {
        "limit": GetCoinRecords(limit=uint32(api.max_get_coin_records_limit + 1)),
        "coin_id_filter": GetCoinRecords(coin_id_filter=HashFilter.include(too_many_hashes)),
        "puzzle_hash_filter": GetCoinRecords(puzzle_hash_filter=HashFilter.include(too_many_hashes)),
        "parent_coin_id_filter": GetCoinRecords(parent_coin_id_filter=HashFilter.include(too_many_hashes)),
        "amount_filter": GetCoinRecords(amount_filter=AmountFilter.include(too_many_amounts)),
    }.items():
        with pytest.raises(ValueError, match=name):
            await client.get_coin_records(request)

    # Type validation is handled via `Streamable.from_json_dict´ but the below should make at least sure it triggers.
    for field, value in {
        "offset": "invalid",
        "limit": "invalid",
        "wallet_id": "invalid",
        "wallet_type": 100,
        "coin_type": 100,
        "coin_id_filter": "invalid",
        "puzzle_hash_filter": "invalid",
        "parent_coin_id_filter": "invalid",
        "amount_filter": "invalid",
        "amount_range": "invalid",
        "confirmed_range": "invalid",
        "spent_range": "invalid",
        "order": 8,
    }.items():
        with pytest.raises((ConversionError, InvalidTypeError, ValueError)):
            json_dict = GetCoinRecords().to_json_dict()
            json_dict[field] = value
            await api.get_coin_records(json_dict)


@pytest.mark.anyio
async def test_notification_rpcs(wallet_rpc_environment: WalletRpcTestEnvironment):
    env: WalletRpcTestEnvironment = wallet_rpc_environment

    wallet_2: Wallet = env.wallet_2.wallet
    wallet_node: WalletNode = env.wallet_1.node
    full_node_api: FullNodeSimulator = env.full_node.api
    client: WalletRpcClient = env.wallet_1.rpc_client
    client_2: WalletRpcClient = env.wallet_2.rpc_client

    await generate_funds(full_node_api, env.wallet_1)

    env.wallet_2.node.config["enable_notifications"] = True
    env.wallet_2.node.config["required_notification_amount"] = 100000000000
    tx = await client.send_notification(
        await wallet_2.get_new_puzzlehash(),
        b"hello",
        uint64(100000000000),
        fee=uint64(100000000000),
    )

    assert tx.spend_bundle is not None
    await time_out_assert(
        5,
        full_node_api.full_node.mempool_manager.get_spendbundle,
        tx.spend_bundle,
        tx.spend_bundle.name(),
    )
    await farm_transaction(full_node_api, wallet_node, tx.spend_bundle)
    await time_out_assert(20, env.wallet_2.wallet.get_confirmed_balance, uint64(100000000000))

    notification = (await client_2.get_notifications(GetNotifications())).notifications[0]
    assert [notification] == (await client_2.get_notifications(GetNotifications([notification.id]))).notifications
    assert [] == (await client_2.get_notifications(GetNotifications(None, uint32(0), uint32(0)))).notifications
    assert [notification] == (await client_2.get_notifications(GetNotifications(None, None, uint32(1)))).notifications
    assert [] == (await client_2.get_notifications(GetNotifications(None, uint32(1), None))).notifications
    assert [notification] == (await client_2.get_notifications(GetNotifications(None, None, None))).notifications
    assert await client_2.delete_notifications()
    assert [] == (await client_2.get_notifications(GetNotifications([notification.id]))).notifications

    tx = await client.send_notification(
        await wallet_2.get_new_puzzlehash(),
        b"hello",
        uint64(100000000000),
        fee=uint64(100000000000),
    )

    assert tx.spend_bundle is not None
    await time_out_assert(
        5,
        full_node_api.full_node.mempool_manager.get_spendbundle,
        tx.spend_bundle,
        tx.spend_bundle.name(),
    )
    await farm_transaction(full_node_api, wallet_node, tx.spend_bundle)
    await time_out_assert(20, env.wallet_2.wallet.get_confirmed_balance, uint64(200000000000))

    notification = (await client_2.get_notifications(GetNotifications())).notifications[0]
    assert await client_2.delete_notifications([notification.id])
    assert [] == (await client_2.get_notifications(GetNotifications([notification.id]))).notifications


# The signatures below were made from an ephemeral key pair that isn't included in the test code.
# When modifying this test, any key can be used to generate signatures. Only the pubkey needs to
# be included in the test code.
#
# Example 1:
# $ chia keys generate
# $ chia keys sign -d 'hello world' -t 'm/12381/8444/1/1'
#
# Example 2:
# $ chia wallet get_address
# xch1vk0dj7cx7d638h80mcuw70xqlnr56pmuhzajemn5ym02vhl3mzyqrrd4wp
# $ chia wallet sign_message -m $(echo -n 'hello world' | xxd -p)
# -a xch1vk0dj7cx7d638h80mcuw70xqlnr56pmuhzajemn5ym02vhl3mzyqrrd4wp
#
@pytest.mark.parametrize(
    ["rpc_request", "rpc_response"],
    [
        # Valid signatures
        (
            # chia keys sign -d "Let's eat, Grandma" -t "m/12381/8444/1/1"
            {
                "message": "4c65742773206561742c204772616e646d61",  # Let's eat, Grandma
                "pubkey": (
                    "89d8e2a225c2ff543222bd0f2ba457a44acbdd147e4dfa02"
                    "eadaef73eae49450dc708fd7c86800b60e8bc456e77563e4"
                ),
                "signature": (
                    "8006f63537563f038321eeda25f3838613d8f938e95f19d1d19ccbe634e9ee4d69552536aab08b4fe961305"
                    "e534ffddf096199ae936b272dac88c936e8774bfc7a6f24025085026db3b7c3c41b472db3daf99b5e6cabf2"
                    "6034d8782d10ef148d"
                ),
            },
            VerifySignatureResponse(isValid=True),
        ),
        (
            # chia wallet sign_message -m $(echo -n 'Happy happy joy joy' | xxd -p)
            # -a xch1e2pcue5q7t4sg8gygz3aht369sk78rzzs92zx65ktn9a9qurw35saajvkh
            {
                "message": "4861707079206861707079206a6f79206a6f79",  # Happy happy joy joy
                "pubkey": (
                    "8e156d106f1b0ff0ebbe5ab27b1797a19cf3e895a7a435b0"
                    "03a1df2dd477d622be928379625b759ef3b388b286ee8658"
                ),
                "signature": (
                    "a804111f80be2ed0d4d3fdd139c8fe20cd506b99b03592563d85292abcbb9cd6ff6df2e7a13093e330d66aa"
                    "5218bbe0e17677c9a23a9f18dbe488b7026be59d476161f5e6f0eea109cd7be22b1f74fda9c80c6b845ecc6"
                    "91246eb1c7f1b66a6a"
                ),
                "signing_mode": SigningMode.CHIP_0002.value,
            },
            VerifySignatureResponse(isValid=True),
        ),
        (
            # chia wallet sign_message -m $(echo -n 'Happy happy joy joy' | xxd -p)
            # -a xch1e2pcue5q7t4sg8gygz3aht369sk78rzzs92zx65ktn9a9qurw35saajvkh
            {
                "message": "4861707079206861707079206a6f79206a6f79",  # Happy happy joy joy
                "pubkey": (
                    "8e156d106f1b0ff0ebbe5ab27b1797a19cf3e895a7a435b0"
                    "03a1df2dd477d622be928379625b759ef3b388b286ee8658"
                ),
                "signature": (
                    "a804111f80be2ed0d4d3fdd139c8fe20cd506b99b03592563d85292abcbb9cd6ff6df2e7a13093e330d66aa"
                    "5218bbe0e17677c9a23a9f18dbe488b7026be59d476161f5e6f0eea109cd7be22b1f74fda9c80c6b845ecc6"
                    "91246eb1c7f1b66a6a"
                ),
                "signing_mode": SigningMode.CHIP_0002.value,
                "address": "xch1e2pcue5q7t4sg8gygz3aht369sk78rzzs92zx65ktn9a9qurw35saajvkh",
            },
            VerifySignatureResponse(isValid=True),
        ),
        (
            {
                "message": "4f7a6f6e65",  # Ozone
                "pubkey": (
                    "8fba5482e6c798a06ee1fd95deaaa83f11c46da06006ab35"
                    "24e917f4e116c2bdec69d6098043ca568290ac366e5e2dc5"
                ),
                "signature": (
                    "92a5124d53b74e4197d075277d0b31eda1571353415c4a87952035aa392d4e9206b35e4af959e7135e45db1"
                    "c884b8b970f9cbffd42291edc1acdb124554f04608b8d842c19e1404d306f881fa79c0e287bdfcf36a6e5da"
                    "334981b974a6cebfd0"
                ),
                "signing_mode": SigningMode.CHIP_0002_P2_DELEGATED_CONDITIONS.value,
                "address": "xch1hh9phcc8tt703dla70qthlhrxswy88va04zvc7vd8cx2v6a5ywyst8mgul",
            },
            VerifySignatureResponse(isValid=True),
        ),
        # Negative tests
        (
            # Message was modified
            {
                "message": "4c6574277320656174204772616e646d61",  # Let's eat Grandma
                "pubkey": (
                    "89d8e2a225c2ff543222bd0f2ba457a44acbdd147e4dfa02"
                    "eadaef73eae49450dc708fd7c86800b60e8bc456e77563e4"
                ),
                "signature": (
                    "8006f63537563f038321eeda25f3838613d8f938e95f19d1d19ccbe634e9ee4d69552536aab08b4fe961305"
                    "e534ffddf096199ae936b272dac88c936e8774bfc7a6f24025085026db3b7c3c41b472db3daf99b5e6cabf2"
                    "6034d8782d10ef148d"
                ),
            },
            VerifySignatureResponse(isValid=False, error="Signature is invalid."),
        ),
        (
            # Valid signature but address doesn't match pubkey
            {
                "message": "4861707079206861707079206a6f79206a6f79",  # Happy happy joy joy
                "pubkey": (
                    "8e156d106f1b0ff0ebbe5ab27b1797a19cf3e895a7a435b0"
                    "03a1df2dd477d622be928379625b759ef3b388b286ee8658"
                ),
                "signature": (
                    "a804111f80be2ed0d4d3fdd139c8fe20cd506b99b03592563d85292abcbb9cd6ff6df2e7a13093e330d66aa"
                    "5218bbe0e17677c9a23a9f18dbe488b7026be59d476161f5e6f0eea109cd7be22b1f74fda9c80c6b845ecc6"
                    "91246eb1c7f1b66a6a"
                ),
                "signing_mode": SigningMode.CHIP_0002.value,
                "address": "xch1d0rekc2javy5gpruzmcnk4e4qq834jzlvxt5tcgl2ylt49t26gdsjen7t0",
            },
            VerifySignatureResponse(isValid=False, error="Public key doesn't match the address"),
        ),
        (
            {
                "message": "4f7a6f6e65",  # Ozone
                "pubkey": (
                    "8fba5482e6c798a06ee1fd95deaaa83f11c46da06006ab35"
                    "24e917f4e116c2bdec69d6098043ca568290ac366e5e2dc5"
                ),
                "signature": (
                    "92a5124d53b74e4197d075277d0b31eda1571353415c4a87952035aa392d4e9206b35e4af959e7135e45db1"
                    "c884b8b970f9cbffd42291edc1acdb124554f04608b8d842c19e1404d306f881fa79c0e287bdfcf36a6e5da"
                    "334981b974a6cebfd0"
                ),
                "address": "xch1hh9phcc8tt703dla70qthlhrxswy88va04zvc7vd8cx2v6a5ywyst8mgul",
            },
            VerifySignatureResponse(isValid=False, error="Public key doesn't match the address"),
        ),
    ],
)
@pytest.mark.parametrize("prefix_hex_strings", [True, False], ids=["with 0x", "no 0x"])
@pytest.mark.anyio
@pytest.mark.limit_consensus_modes(reason="irrelevant")
async def test_verify_signature(
    wallet_rpc_environment: WalletRpcTestEnvironment,
    rpc_request: Dict[str, Any],
    rpc_response: Dict[str, Any],
    prefix_hex_strings: bool,
):
    rpc_server: Optional[RpcServer] = wallet_rpc_environment.wallet_1.service.rpc_server
    assert rpc_server is not None
    updated_request = rpc_request.copy()
    updated_request["pubkey"] = ("0x" if prefix_hex_strings else "") + updated_request["pubkey"]
    updated_request["signature"] = ("0x" if prefix_hex_strings else "") + updated_request["signature"]
    res = await wallet_rpc_environment.wallet_1.rpc_client.verify_signature(
        VerifySignature.from_json_dict(updated_request)
    )
    assert res == rpc_response


@pytest.mark.anyio
@pytest.mark.limit_consensus_modes(reason="irrelevant")
async def test_set_auto_claim(wallet_rpc_environment: WalletRpcTestEnvironment):
    env: WalletRpcTestEnvironment = wallet_rpc_environment
    full_node_api: FullNodeSimulator = env.full_node.api
    rpc_server: Optional[RpcServer] = wallet_rpc_environment.wallet_1.service.rpc_server
    await generate_funds(full_node_api, env.wallet_1)
    assert rpc_server is not None
    api: WalletRpcApi = cast(WalletRpcApi, rpc_server.rpc_api)
    req = {"enabled": False, "tx_fee": -1, "min_amount": 100}
    has_exception = False
    try:
        # Manually using API to test error condition
        await api.set_auto_claim(req)
    except ConversionError:
        has_exception = True
    assert has_exception
    req = {"enabled": False, "batch_size": 0, "min_amount": 100}
    res = await env.wallet_1.rpc_client.set_auto_claim(
        AutoClaimSettings(enabled=False, batch_size=uint16(0), min_amount=uint64(100))
    )
    assert not res.enabled
    assert res.tx_fee == 0
    assert res.min_amount == 100
    assert res.batch_size == 50


@pytest.mark.anyio
@pytest.mark.limit_consensus_modes(reason="irrelevant")
async def test_get_auto_claim(wallet_rpc_environment: WalletRpcTestEnvironment):
    env: WalletRpcTestEnvironment = wallet_rpc_environment
    full_node_api: FullNodeSimulator = env.full_node.api
    rpc_server: Optional[RpcServer] = wallet_rpc_environment.wallet_1.service.rpc_server
    await generate_funds(full_node_api, env.wallet_1)
    assert rpc_server is not None
    res = await env.wallet_1.rpc_client.get_auto_claim()
    assert not res.enabled
    assert res.tx_fee == 0
    assert res.min_amount == 0
    assert res.batch_size == 50


@pytest.mark.anyio
async def test_set_wallet_resync_on_startup(wallet_rpc_environment: WalletRpcTestEnvironment):
    env: WalletRpcTestEnvironment = wallet_rpc_environment
    full_node_api: FullNodeSimulator = env.full_node.api
    client: WalletRpcClient = env.wallet_1.rpc_client
    await generate_funds(full_node_api, env.wallet_1)
    wc = env.wallet_1.rpc_client
    await wc.create_new_did_wallet(1, DEFAULT_TX_CONFIG, 0)
    await time_out_assert(5, check_mempool_spend_count, True, full_node_api, 1)
    await farm_transaction_block(full_node_api, env.wallet_1.node)
    await time_out_assert(20, wc.get_synced)

    nft_wallet = await wc.create_new_nft_wallet(None)
    nft_wallet_id = nft_wallet["wallet_id"]
    address = await wc.get_next_address(env.wallet_1.wallet.id(), True)
    await wc.mint_nft(
        nft_wallet_id,
        tx_config=DEFAULT_TX_CONFIG,
        royalty_address=address,
        target_address=address,
        hash="deadbeef",
        uris=["http://test.nft"],
    )
    await time_out_assert(5, check_mempool_spend_count, True, full_node_api, 1)
    await farm_transaction_block(full_node_api, env.wallet_1.node)
    await time_out_assert(20, wc.get_synced)

    wallet_node: WalletNode = env.wallet_1.node
    wallet_node_2: WalletNode = env.wallet_2.node
    # Test Clawback resync
    tx = (
        await wc.send_transaction(
            wallet_id=1,
            amount=uint64(500),
            address=address,
            tx_config=DEFAULT_TX_CONFIG,
            fee=uint64(0),
            puzzle_decorator_override=[{"decorator": "CLAWBACK", "clawback_timelock": 5}],
        )
    ).transaction
    clawback_coin_id = tx.additions[0].name()
    assert tx.spend_bundle is not None
    await farm_transaction(full_node_api, wallet_node, tx.spend_bundle)
    await time_out_assert(20, wc.get_synced)
    await asyncio.sleep(10)
    resp = await wc.spend_clawback_coins([clawback_coin_id], 0)
    assert resp["success"]
    assert len(resp["transaction_ids"]) == 1
    await time_out_assert_not_none(
        10, full_node_api.full_node.mempool_manager.get_spendbundle, bytes32.from_hexstr(resp["transaction_ids"][0])
    )
    await farm_transaction_block(full_node_api, wallet_node)
    await time_out_assert(20, wc.get_synced)
    wallet_node_2._close()
    await wallet_node_2._await_closed()
    # set flag to reset wallet sync data on start
    await client.set_wallet_resync_on_startup()
    fingerprint = wallet_node.logged_in_fingerprint
    assert wallet_node._wallet_state_manager
    # 2 reward coins, 1 DID, 1 NFT, 1 clawbacked coin
    assert len(await wallet_node._wallet_state_manager.coin_store.get_all_unspent_coins()) == 5
    assert await wallet_node._wallet_state_manager.nft_store.count() == 1
    # standard wallet, did wallet, nft wallet, did nft wallet
    assert len(await wallet_node.wallet_state_manager.user_store.get_all_wallet_info_entries()) == 4
    before_txs = await wallet_node.wallet_state_manager.tx_store.get_all_transactions()
    wallet_node._close()
    await wallet_node._await_closed()
    config = load_config(wallet_node.root_path, "config.yaml")
    # check that flag was set in config file
    assert config["wallet"]["reset_sync_for_fingerprint"] == fingerprint
    new_config = wallet_node.config.copy()
    new_config["reset_sync_for_fingerprint"] = config["wallet"]["reset_sync_for_fingerprint"]
    wallet_node_2.config = new_config
    wallet_node_2.root_path = wallet_node.root_path
    wallet_node_2.local_keychain = wallet_node.local_keychain
    # use second node to start the same wallet, reusing config and db
    await wallet_node_2._start_with_fingerprint(fingerprint)
    assert wallet_node_2._wallet_state_manager
    after_txs = await wallet_node_2.wallet_state_manager.tx_store.get_all_transactions()
    # transactions should be the same
    assert after_txs == before_txs
    # Check clawback
    clawback_tx = await wallet_node_2.wallet_state_manager.tx_store.get_transaction_record(clawback_coin_id)
    assert clawback_tx is not None
    assert clawback_tx.confirmed
    # only coin_store was populated in this case, but now should be empty
    assert len(await wallet_node_2._wallet_state_manager.coin_store.get_all_unspent_coins()) == 0
    assert await wallet_node_2._wallet_state_manager.nft_store.count() == 0
    # we don't delete wallets
    assert len(await wallet_node_2.wallet_state_manager.user_store.get_all_wallet_info_entries()) == 4
    updated_config = load_config(wallet_node.root_path, "config.yaml")
    # check that it's disabled after reset
    assert updated_config["wallet"].get("reset_sync_for_fingerprint") is None
    wallet_node_2._close()
    await wallet_node_2._await_closed()


@pytest.mark.anyio
async def test_set_wallet_resync_on_startup_disable(wallet_rpc_environment: WalletRpcTestEnvironment):
    env: WalletRpcTestEnvironment = wallet_rpc_environment
    full_node_api: FullNodeSimulator = env.full_node.api
    client: WalletRpcClient = env.wallet_1.rpc_client
    await generate_funds(full_node_api, env.wallet_1)
    wallet_node: WalletNode = env.wallet_1.node
    wallet_node_2: WalletNode = env.wallet_2.node
    wallet_node_2._close()
    await wallet_node_2._await_closed()
    # set flag to reset wallet sync data on start
    await client.set_wallet_resync_on_startup()
    fingerprint = wallet_node.logged_in_fingerprint
    assert wallet_node._wallet_state_manager
    assert len(await wallet_node._wallet_state_manager.coin_store.get_all_unspent_coins()) == 2
    before_txs = await wallet_node.wallet_state_manager.tx_store.get_all_transactions()
    await client.set_wallet_resync_on_startup(False)
    wallet_node._close()
    await wallet_node._await_closed()
    config = load_config(wallet_node.root_path, "config.yaml")
    # check that flag was set in config file
    assert config["wallet"].get("reset_sync_for_fingerprint") is None
    new_config = wallet_node.config.copy()
    new_config["reset_sync_for_fingerprint"] = config["wallet"].get("reset_sync_for_fingerprint")
    wallet_node_2.config = new_config
    wallet_node_2.root_path = wallet_node.root_path
    wallet_node_2.local_keychain = wallet_node.local_keychain
    # use second node to start the same wallet, reusing config and db
    await wallet_node_2._start_with_fingerprint(fingerprint)
    assert wallet_node_2._wallet_state_manager
    after_txs = await wallet_node_2.wallet_state_manager.tx_store.get_all_transactions()
    # transactions should be the same
    assert after_txs == before_txs
    # only coin_store was populated in this case, but now should be empty
    assert len(await wallet_node_2._wallet_state_manager.coin_store.get_all_unspent_coins()) == 2
    wallet_node_2._close()
    await wallet_node_2._await_closed()


@pytest.mark.anyio
@pytest.mark.limit_consensus_modes(reason="irrelevant")
async def test_set_wallet_resync_schema(wallet_rpc_environment: WalletRpcTestEnvironment):
    env: WalletRpcTestEnvironment = wallet_rpc_environment
    full_node_api: FullNodeSimulator = env.full_node.api
    await generate_funds(full_node_api, env.wallet_1)
    wallet_node: WalletNode = env.wallet_1.node
    fingerprint = wallet_node.logged_in_fingerprint
    assert fingerprint
    db_path = wallet_node.wallet_state_manager.db_path
    assert await wallet_node.reset_sync_db(
        db_path, fingerprint
    ), "Schema has been changed, reset sync db won't work, please update WalletNode.reset_sync_db function"
    dbw: DBWrapper2 = wallet_node.wallet_state_manager.db_wrapper
    conn: aiosqlite.Connection
    async with dbw.writer() as conn:
        await conn.execute("CREATE TABLE blah(temp int)")
    await wallet_node.reset_sync_db(db_path, fingerprint)
    assert (
        len(list(await conn.execute_fetchall("SELECT name FROM sqlite_master WHERE type='table' AND name='blah'"))) == 0
    )


@pytest.mark.anyio
async def test_cat_spend_run_tail(wallet_rpc_environment: WalletRpcTestEnvironment):
    env: WalletRpcTestEnvironment = wallet_rpc_environment

    wallet_node: WalletNode = env.wallet_1.node
    client: WalletRpcClient = env.wallet_1.rpc_client
    full_node_api: FullNodeSimulator = env.full_node.api
    full_node_rpc: FullNodeRpcClient = env.full_node.rpc_client

    await generate_funds(full_node_api, env.wallet_1, 1)

    # Send to a CAT with an anyone can spend TAIL
    our_ph: bytes32 = await env.wallet_1.wallet.get_new_puzzlehash()
    cat_puzzle: Program = construct_cat_puzzle(CAT_MOD, Program.to(None).get_tree_hash(), Program.to(1))
    addr = encode_puzzle_hash(
        cat_puzzle.get_tree_hash(),
        "txch",
    )
    tx_amount = uint64(100)

    tx = (await client.send_transaction(1, tx_amount, addr, DEFAULT_TX_CONFIG)).transaction
    transaction_id = tx.name
    spend_bundle = tx.spend_bundle
    assert spend_bundle is not None

    await time_out_assert(20, tx_in_mempool, True, client, transaction_id)
    await farm_transaction(full_node_api, wallet_node, spend_bundle)

    # Do the eve spend back to our wallet
    cat_coin = next(c for c in spend_bundle.additions() if c.amount == tx_amount)
    eve_spend = WalletSpendBundle(
        [
            make_spend(
                cat_coin,
                cat_puzzle,
                Program.to(
                    [
                        Program.to([[51, our_ph, tx_amount, [our_ph]], [51, None, -113, None, None]]),
                        None,
                        cat_coin.name(),
                        coin_as_list(cat_coin),
                        [cat_coin.parent_coin_info, Program.to(1).get_tree_hash(), cat_coin.amount],
                        0,
                        0,
                    ]
                ),
            )
        ],
        G2Element(),
    )
    await full_node_rpc.push_tx(eve_spend)
    await farm_transaction(full_node_api, wallet_node, eve_spend)

    # Make sure we have the CAT
    res = await client.create_wallet_for_existing_cat(Program.to(None).get_tree_hash())
    assert res["success"]
    cat_wallet_id = res["wallet_id"]
    await time_out_assert(20, get_confirmed_balance, tx_amount, client, cat_wallet_id)

    # Attempt to melt it fully
    tx = (
        await client.cat_spend(
            cat_wallet_id,
            amount=uint64(0),
            tx_config=DEFAULT_TX_CONFIG,
            inner_address=encode_puzzle_hash(our_ph, "txch"),
            cat_discrepancy=(tx_amount * -1, Program.to(None), Program.to(None)),
        )
    ).transaction
    transaction_id = tx.name
    spend_bundle = tx.spend_bundle
    assert spend_bundle is not None

    await time_out_assert(20, tx_in_mempool, True, client, transaction_id)
    await farm_transaction(full_node_api, wallet_node, spend_bundle)

    await time_out_assert(20, get_confirmed_balance, 0, client, cat_wallet_id)


@pytest.mark.anyio
async def test_get_balances(wallet_rpc_environment: WalletRpcTestEnvironment):
    env: WalletRpcTestEnvironment = wallet_rpc_environment

    client: WalletRpcClient = env.wallet_1.rpc_client
    wallet_node: WalletNode = env.wallet_1.node

    full_node_api: FullNodeSimulator = env.full_node.api

    await generate_funds(full_node_api, env.wallet_1, 1)

    await time_out_assert(20, client.get_synced)
    # Creates a CAT wallet with 100 mojos and a CAT with 20 mojos
    await client.create_new_cat_and_wallet(uint64(100), test=True)

    await time_out_assert(20, client.get_synced)
    res = await client.create_new_cat_and_wallet(uint64(20), test=True)
    assert res["success"]
    await time_out_assert(5, check_mempool_spend_count, True, full_node_api, 2)
    await farm_transaction_block(full_node_api, wallet_node)
    await time_out_assert(20, client.get_synced)
    bal = await client.get_wallet_balances()
    assert len(bal) == 3
    assert bal["1"]["confirmed_wallet_balance"] == 1999999999880
    assert bal["2"]["confirmed_wallet_balance"] == 100
    assert bal["3"]["confirmed_wallet_balance"] == 20
    bal_ids = await client.get_wallet_balances([3, 2])
    assert len(bal_ids) == 2
    assert bal["2"]["confirmed_wallet_balance"] == 100
    assert bal["3"]["confirmed_wallet_balance"] == 20


@pytest.mark.parametrize(
    "wallet_environments",
    [
        {
            "num_environments": 1,
            "blocks_needed": [1],
        }
    ],
    indirect=True,
)
@pytest.mark.limit_consensus_modes([ConsensusMode.PLAIN], reason="irrelevant")
@pytest.mark.anyio
async def test_split_coins(wallet_environments: WalletTestFramework) -> None:
    env = wallet_environments.environments[0]
    env.wallet_aliases = {
        "xch": 1,
        "cat": 2,
    }

    # Test XCH first
    async with env.wallet_state_manager.new_action_scope(wallet_environments.tx_config) as action_scope:
        target_coin = list(await env.xch_wallet.select_coins(uint64(250_000_000_000), action_scope))[0]
        assert target_coin.amount == 250_000_000_000

    xch_request = SplitCoins(
        wallet_id=uint32(1),
        number_of_coins=uint16(100),
        amount_per_coin=uint64(100),
        target_coin_id=target_coin.name(),
        fee=uint64(1_000_000_000_000),  # 1 XCH
        push=True,
    )

    with pytest.raises(ResponseFailureError, match="501 coins is greater then the maximum limit of 500 coins"):
        await env.rpc_client.split_coins(
            dataclasses.replace(xch_request, number_of_coins=uint16(501)),
            wallet_environments.tx_config,
        )

    with pytest.raises(ResponseFailureError, match="Could not find coin with ID 00000000000000000"):
        await env.rpc_client.split_coins(
            dataclasses.replace(xch_request, target_coin_id=bytes32([0] * 32)),
            wallet_environments.tx_config,
        )

    with pytest.raises(ResponseFailureError, match="is less than the total amount of the split"):
        await env.rpc_client.split_coins(
            dataclasses.replace(xch_request, amount_per_coin=uint64(1_000_000_000_000)),
            wallet_environments.tx_config,
        )

    with pytest.raises(ResponseFailureError, match="Wallet with ID 42 does not exist"):
        await env.rpc_client.split_coins(
            dataclasses.replace(xch_request, wallet_id=uint32(42)),
            wallet_environments.tx_config,
        )

    env.wallet_state_manager.wallets[uint32(42)] = object()  # type: ignore[assignment]
    with pytest.raises(ResponseFailureError, match="Cannot split coins from non-fungible wallet types"):
        await env.rpc_client.split_coins(
            dataclasses.replace(xch_request, wallet_id=uint32(42)),
            wallet_environments.tx_config,
        )
    del env.wallet_state_manager.wallets[uint32(42)]

    response = await env.rpc_client.split_coins(
        dataclasses.replace(xch_request, number_of_coins=uint16(0)),
        wallet_environments.tx_config,
    )
    assert response == SplitCoinsResponse([], [])

    await env.rpc_client.split_coins(
        xch_request,
        wallet_environments.tx_config,
    )

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {
                        "unconfirmed_wallet_balance": -1_000_000_000_000,  # just the fee
                        "spendable_balance": -2_000_000_000_000,
                        "pending_change": 1_000_000_000_000,
                        "max_send_amount": -2_000_000_000_000,
                        "pending_coin_removal_count": 2,
                    }
                },
                post_block_balance_updates={
                    "xch": {
                        "confirmed_wallet_balance": -1_000_000_000_000,  # just the fee
                        "spendable_balance": 1_000_000_000_000,
                        "pending_change": -1_000_000_000_000,
                        "max_send_amount": 1_000_000_000_000,
                        "pending_coin_removal_count": -2,
                        "unspent_coin_count": 99,  # split 1 into 100 i.e. +99
                    }
                },
            )
        ]
    )

    # Now do CATs
    async with env.wallet_state_manager.new_action_scope(wallet_environments.tx_config, push=True) as action_scope:
        cat_wallet = await CATWallet.create_new_cat_wallet(
            env.wallet_state_manager,
            env.xch_wallet,
            {"identifier": "genesis_by_id"},
            uint64(50),
            action_scope,
        )

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                # no need to test this, it is tested elsewhere
                pre_block_balance_updates={
                    "xch": {"set_remainder": True},
                    "cat": {"init": True, "set_remainder": True},
                },
                post_block_balance_updates={
                    "xch": {"set_remainder": True},
                    "cat": {"set_remainder": True},
                },
            )
        ]
    )

    async with env.wallet_state_manager.new_action_scope(wallet_environments.tx_config) as action_scope:
        target_coin = list(await cat_wallet.select_coins(uint64(50), action_scope))[0]
        assert target_coin.amount == 50

    cat_request = SplitCoins(
        wallet_id=uint32(2),
        number_of_coins=uint16(50),
        amount_per_coin=uint64(1),
        target_coin_id=target_coin.name(),
        push=True,
    )

    await env.rpc_client.split_coins(
        cat_request,
        wallet_environments.tx_config,
    )

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "cat": {
                        "unconfirmed_wallet_balance": 0,
                        "spendable_balance": -50,
                        "pending_change": 50,
                        "max_send_amount": -50,
                        "pending_coin_removal_count": 1,
                    }
                },
                post_block_balance_updates={
                    "cat": {
                        "confirmed_wallet_balance": 0,
                        "spendable_balance": 50,
                        "pending_change": -50,
                        "max_send_amount": 50,
                        "pending_coin_removal_count": -1,
                        "unspent_coin_count": 49,  # split 1 into 50 i.e. +49
                    }
                },
            )
        ]
    )


@pytest.mark.parametrize(
    "wallet_environments",
    [
        {
            "num_environments": 1,
            "blocks_needed": [2],
        }
    ],
    indirect=True,
)
@pytest.mark.limit_consensus_modes([ConsensusMode.PLAIN], reason="irrelevant")
@pytest.mark.anyio
async def test_combine_coins(wallet_environments: WalletTestFramework) -> None:
    env = wallet_environments.environments[0]
    env.wallet_aliases = {
        "xch": 1,
        "cat": 2,
    }

    # Should have 4 coins, two 1.75 XCH, two 0.25 XCH

    # Grab one of the 0.25 ones to specify
    async with env.wallet_state_manager.new_action_scope(wallet_environments.tx_config) as action_scope:
        target_coin = list(await env.xch_wallet.select_coins(uint64(250_000_000_000), action_scope))[0]
        assert target_coin.amount == 250_000_000_000

    # These parameters will give us the maximum amount of behavior coverage
    # - More amount than the coin we specify
    # - Less amount than will have to be selected in order create it
    # - Higher # coins than necessary to create it
    fee = uint64(100)
    xch_combine_request = CombineCoins(
        wallet_id=uint32(1),
        target_coin_amount=uint64(1_000_000_000_000),
        number_of_coins=uint16(3),
        target_coin_ids=[target_coin.name()],
        fee=fee,
        push=True,
    )

    # Test some error cases first
    with pytest.raises(ResponseFailureError, match="greater then the maximum limit"):
        await env.rpc_client.combine_coins(
            dataclasses.replace(xch_combine_request, number_of_coins=uint16(501)),
            wallet_environments.tx_config,
        )

    with pytest.raises(ResponseFailureError, match="You need at least two coins to combine"):
        await env.rpc_client.combine_coins(
            dataclasses.replace(xch_combine_request, number_of_coins=uint16(0)),
            wallet_environments.tx_config,
        )

    with pytest.raises(ResponseFailureError, match="More coin IDs specified than desired number of coins to combine"):
        await env.rpc_client.combine_coins(
            dataclasses.replace(xch_combine_request, target_coin_ids=[bytes32([0] * 32)] * 100),
            wallet_environments.tx_config,
        )

    with pytest.raises(ResponseFailureError, match="Wallet with ID 50 does not exist"):
        await env.rpc_client.combine_coins(
            dataclasses.replace(xch_combine_request, wallet_id=uint32(50)),
            wallet_environments.tx_config,
        )

    env.wallet_state_manager.wallets[uint32(42)] = object()  # type: ignore[assignment]
    with pytest.raises(ResponseFailureError, match="Cannot combine coins from non-fungible wallet types"):
        await env.rpc_client.combine_coins(
            dataclasses.replace(xch_combine_request, wallet_id=uint32(42)),
            wallet_environments.tx_config,
        )
    del env.wallet_state_manager.wallets[uint32(42)]

    # Now push the request
    await env.rpc_client.combine_coins(
        xch_combine_request,
        wallet_environments.tx_config,
    )

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {
                        "unconfirmed_wallet_balance": -fee,
                        "spendable_balance": -2_250_000_000_000,
                        "pending_change": 2_250_000_000_000 - fee,
                        "max_send_amount": -2_250_000_000_000,
                        "pending_coin_removal_count": 3,
                    }
                },
                post_block_balance_updates={
                    "xch": {
                        "confirmed_wallet_balance": -fee,
                        "spendable_balance": 2_250_000_000_000 - fee,
                        "pending_change": -(2_250_000_000_000 - fee),
                        "max_send_amount": 2_250_000_000_000 - fee,
                        "pending_coin_removal_count": -3,
                        "unspent_coin_count": -1,  # combine 3 into 1 + change
                    }
                },
            )
        ]
    )

    # Now do CATs
    async with env.wallet_state_manager.new_action_scope(wallet_environments.tx_config, push=True) as action_scope:
        cat_wallet = await CATWallet.create_new_cat_wallet(
            env.wallet_state_manager,
            env.xch_wallet,
            {"identifier": "genesis_by_id"},
            uint64(50),
            action_scope,
        )

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                # no need to test this, it is tested elsewhere
                pre_block_balance_updates={
                    "xch": {"set_remainder": True},
                    "cat": {"init": True, "set_remainder": True},
                },
                post_block_balance_updates={
                    "xch": {"set_remainder": True},
                    "cat": {"set_remainder": True},
                },
            )
        ]
    )

    BIG_COIN_AMOUNT = uint64(30)
    SMALL_COIN_AMOUNT = uint64(15)
    REALLY_SMALL_COIN_AMOUNT = uint64(5)
    async with env.wallet_state_manager.new_action_scope(wallet_environments.tx_config, push=True) as action_scope:
        await cat_wallet.generate_signed_transaction(
            [BIG_COIN_AMOUNT, SMALL_COIN_AMOUNT, REALLY_SMALL_COIN_AMOUNT],
            [await env.xch_wallet.get_puzzle_hash(new=action_scope.config.tx_config.reuse_puzhash)] * 3,
            action_scope,
        )

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                # no need to test this, it is tested elsewhere
                pre_block_balance_updates={
                    "xch": {"set_remainder": True},
                    "cat": {"init": True, "set_remainder": True},
                },
                post_block_balance_updates={
                    "xch": {"set_remainder": True},
                    "cat": {"set_remainder": True},
                },
            )
        ]
    )

    # We're going to test that we select the two smaller coins
    cat_combine_request = CombineCoins(
        wallet_id=uint32(2),
        target_coin_amount=None,
        number_of_coins=uint16(2),
        target_coin_ids=[],
        largest_first=False,
        fee=fee,
        push=True,
    )

    await env.rpc_client.combine_coins(
        cat_combine_request,
        wallet_environments.tx_config,
    )

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {
                        "unconfirmed_wallet_balance": -fee,
                        "set_remainder": True,  # We only really care that a fee was in fact attached
                    },
                    "cat": {
                        "spendable_balance": -SMALL_COIN_AMOUNT - REALLY_SMALL_COIN_AMOUNT,
                        "pending_change": SMALL_COIN_AMOUNT + REALLY_SMALL_COIN_AMOUNT,
                        "max_send_amount": -SMALL_COIN_AMOUNT - REALLY_SMALL_COIN_AMOUNT,
                        "pending_coin_removal_count": 2,
                    },
                },
                post_block_balance_updates={
                    "xch": {
                        "confirmed_wallet_balance": -fee,
                        "set_remainder": True,  # We only really care that a fee was in fact attached
                    },
                    "cat": {
                        "spendable_balance": SMALL_COIN_AMOUNT + REALLY_SMALL_COIN_AMOUNT,
                        "pending_change": -SMALL_COIN_AMOUNT - REALLY_SMALL_COIN_AMOUNT,
                        "max_send_amount": SMALL_COIN_AMOUNT + REALLY_SMALL_COIN_AMOUNT,
                        "pending_coin_removal_count": -2,
                        "unspent_coin_count": -1,
                    },
                },
            )
        ]
    )
