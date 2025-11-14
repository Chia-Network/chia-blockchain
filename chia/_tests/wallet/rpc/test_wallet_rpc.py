from __future__ import annotations

import dataclasses
import io
import json
import logging
import re
from operator import attrgetter
from typing import Any, Optional
from unittest.mock import patch

import aiosqlite
import pytest
from chia_rs import CoinSpend, G1Element, G2Element
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint16, uint32, uint64, uint128

from chia._tests.environments.wallet import WalletStateTransition, WalletTestFramework
from chia._tests.util.time_out_assert import time_out_assert
from chia._tests.wallet.cat_wallet.test_cat_wallet import mint_cat
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
from chia.cmds.coins import CombineCMD, SplitCMD
from chia.cmds.param_types import CliAmount
from chia.full_node.full_node_rpc_client import FullNodeRpcClient
from chia.rpc.rpc_client import ResponseFailureError
from chia.simulator.full_node_simulator import FullNodeSimulator
from chia.types.blockchain_format.coin import Coin, coin_as_list
from chia.types.blockchain_format.program import Program
from chia.types.coin_record import CoinRecord
from chia.types.coin_spend import make_spend
from chia.types.signing_mode import SigningMode
from chia.util.bech32m import decode_puzzle_hash, encode_puzzle_hash
from chia.util.config import load_config, lock_and_load_config, save_config
from chia.util.db_wrapper import DBWrapper2
from chia.util.hash import std_hash
from chia.wallet.cat_wallet.cat_constants import DEFAULT_CATS
from chia.wallet.cat_wallet.cat_utils import CAT_MOD, construct_cat_puzzle
from chia.wallet.cat_wallet.cat_wallet import CATWallet
from chia.wallet.cat_wallet.r_cat_wallet import RCATWallet
from chia.wallet.conditions import (
    ConditionValidTimes,
    ConditionValidTimesAbsolute,
    CreateCoinAnnouncement,
    CreatePuzzleAnnouncement,
    Remark,
    conditions_to_json_dicts,
)
from chia.wallet.derive_keys import master_sk_to_wallet_sk, master_sk_to_wallet_sk_unhardened
from chia.wallet.did_wallet.did_wallet import DIDWallet
from chia.wallet.nft_wallet.nft_wallet import NFTWallet
from chia.wallet.puzzle_drivers import PuzzleInfo
from chia.wallet.puzzles.p2_delegated_puzzle_or_hidden_puzzle import puzzle_hash_for_pk
from chia.wallet.signer_protocol import UnsignedTransaction
from chia.wallet.trade_record import TradeRecord
from chia.wallet.trading.offer import Offer, OfferSummary
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
from chia.wallet.util.tx_config import TXConfig
from chia.wallet.util.wallet_types import CoinType, WalletType
from chia.wallet.wallet import Wallet
from chia.wallet.wallet_coin_record import WalletCoinRecord
from chia.wallet.wallet_coin_store import GetCoinRecords
from chia.wallet.wallet_node import WalletNode, get_wallet_db_path
from chia.wallet.wallet_protocol import WalletProtocol
from chia.wallet.wallet_request_types import (
    AddKey,
    CATAssetIDToName,
    CATGetAssetID,
    CATGetName,
    CATSetName,
    CATSpend,
    CheckDeleteKey,
    CheckOfferValidity,
    ClawbackPuzzleDecoratorOverride,
    CombineCoins,
    CreateOfferForIDs,
    DefaultCAT,
    DeleteKey,
    DeleteNotifications,
    DeleteUnconfirmedTransactions,
    DIDCreateBackupFile,
    DIDGetDID,
    DIDGetMetadata,
    DIDGetPubkey,
    DIDGetWalletName,
    DIDMessageSpend,
    DIDSetWalletName,
    DIDTransferDID,
    DIDUpdateMetadata,
    FungibleAsset,
    GetCoinRecordsByNames,
    GetNextAddress,
    GetNotifications,
    GetOfferSummary,
    GetPrivateKey,
    GetSpendableCoins,
    GetSyncStatusResponse,
    GetTimestampForHeight,
    GetTransaction,
    GetTransactionCount,
    GetTransactions,
    GetWalletBalance,
    GetWalletBalances,
    GetWallets,
    LogIn,
    NFTCalculateRoyalties,
    NFTGetInfo,
    NFTGetNFTs,
    NFTMintNFTRequest,
    NFTTransferNFT,
    PushTransactions,
    PushTX,
    RoyaltyAsset,
    SelectCoins,
    SendNotification,
    SendTransaction,
    SetWalletResyncOnStartup,
    SpendClawbackCoins,
    SplitCoins,
    TakeOffer,
    VerifySignature,
    VerifySignatureResponse,
)
from chia.wallet.wallet_rpc_api import WalletRpcApi
from chia.wallet.wallet_rpc_client import WalletRpcClient
from chia.wallet.wallet_spend_bundle import WalletSpendBundle

log = logging.getLogger(__name__)


async def farm_transaction_block(full_node_api: FullNodeSimulator, wallet_node: WalletNode) -> None:
    await full_node_api.farm_blocks_to_puzzlehash(count=1)
    await full_node_api.wait_for_wallet_synced(wallet_node=wallet_node, timeout=20)


async def farm_transaction(
    full_node_api: FullNodeSimulator, wallet_node: WalletNode, spend_bundle: WalletSpendBundle
) -> None:
    spend_bundle_name = spend_bundle.name()
    await time_out_assert(20, full_node_api.full_node.mempool_manager.get_spendbundle, spend_bundle, spend_bundle_name)
    await farm_transaction_block(full_node_api, wallet_node)
    assert full_node_api.full_node.mempool_manager.get_spendbundle(spend_bundle_name) is None


async def create_tx_outputs(
    wallet: Wallet, tx_config: TXConfig, output_args: list[tuple[int, Optional[list[str]]]]
) -> list[dict[str, Any]]:
    outputs = []
    async with wallet.wallet_state_manager.new_action_scope(tx_config, push=True) as action_scope:
        for args in output_args:
            output = {
                "amount": uint64(args[0]),
                "puzzle_hash": await action_scope.get_puzzle_hash(wallet.wallet_state_manager),
            }
            if args[1] is not None:
                assert len(args[1]) > 0
                output["memos"] = args[1]
            outputs.append(output)
    return outputs


def assert_tx_amounts(
    tx: TransactionRecord,
    outputs: list[dict[str, Any]],
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


async def assert_push_tx_error(node_rpc: FullNodeRpcClient, tx: TransactionRecord) -> None:
    spend_bundle = tx.spend_bundle
    assert spend_bundle is not None
    # check error for a ASSERT_ANNOUNCE_CONSUMED_FAILED and if the error is not there throw a value error
    try:
        await node_rpc.push_tx(spend_bundle)
    except ValueError as error:
        error_string = error.args[0]["error"]
        if error_string.find("ASSERT_ANNOUNCE_CONSUMED_FAILED") == -1:
            raise ValueError from error


async def assert_get_balance(rpc_client: WalletRpcClient, wallet_node: WalletNode, wallet: WalletProtocol[Any]) -> None:
    expected_balance = await wallet_node.get_balance(wallet.id())
    expected_balance_dict = expected_balance.to_json_dict()
    expected_balance_dict.setdefault("pending_approval_balance", None)
    expected_balance_dict["wallet_id"] = wallet.id()
    expected_balance_dict["wallet_type"] = wallet.type()
    expected_balance_dict["fingerprint"] = wallet_node.logged_in_fingerprint
    if wallet.type() in {WalletType.CAT, WalletType.CRCAT}:
        assert isinstance(wallet, CATWallet)
        expected_balance_dict["asset_id"] = "0x" + wallet.get_asset_id()
    else:
        expected_balance_dict["asset_id"] = None
    assert (
        await rpc_client.get_wallet_balance(GetWalletBalance(wallet.id()))
    ).wallet_balance.to_json_dict() == expected_balance_dict


async def tx_in_mempool(client: WalletRpcClient, transaction_id: bytes32) -> bool:
    tx = (await client.get_transaction(GetTransaction(transaction_id))).transaction
    return tx.is_in_mempool()


async def get_confirmed_balance(client: WalletRpcClient, wallet_id: int) -> uint128:
    return (
        await client.get_wallet_balance(GetWalletBalance(uint32(wallet_id)))
    ).wallet_balance.confirmed_wallet_balance


async def get_unconfirmed_balance(client: WalletRpcClient, wallet_id: int) -> uint128:
    return (
        await client.get_wallet_balance(GetWalletBalance(uint32(wallet_id)))
    ).wallet_balance.unconfirmed_wallet_balance


@pytest.mark.parametrize(
    "wallet_environments",
    [
        {
            "num_environments": 2,
            "blocks_needed": [1, 1],
        }
    ],
    indirect=True,
)
@pytest.mark.limit_consensus_modes(reason="irrelevant")
@pytest.mark.anyio
async def test_send_transaction(wallet_environments: WalletTestFramework) -> None:
    env = wallet_environments.environments[0]
    env_2 = wallet_environments.environments[1]
    wallet_2: Wallet = env_2.xch_wallet
    wallet_node: WalletNode = env.node
    full_node_api: FullNodeSimulator = wallet_environments.full_node
    client: WalletRpcClient = env.rpc_client

    INITIAL_FUNDS = await env.xch_wallet.get_confirmed_balance()
    async with wallet_2.wallet_state_manager.new_action_scope(wallet_environments.tx_config, push=True) as action_scope:
        addr = encode_puzzle_hash(await action_scope.get_puzzle_hash(wallet_2.wallet_state_manager), "txch")
    tx_amount = uint64(15600000)
    with pytest.raises(ValueError):
        await client.send_transaction(
            SendTransaction(wallet_id=uint32(1), amount=uint64(100000000000000001), address=addr, push=True),
            wallet_environments.tx_config,
        )

    # Tests sending a basic transaction
    extra_conditions = (Remark(Program.to(("test", None))),)
    non_existent_coin = Coin(bytes32.zeros, bytes32.zeros, uint64(0))
    tx_no_push = (
        await client.send_transaction(
            SendTransaction(
                wallet_id=uint32(1), amount=tx_amount, address=addr, memos=["this is a basic tx"], push=False
            ),
            tx_config=wallet_environments.tx_config.override(
                excluded_coin_amounts=[uint64(250000000000)],
                excluded_coin_ids=[non_existent_coin.name()],
                reuse_puzhash=True,
            ),
            extra_conditions=extra_conditions,
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
    tx = TransactionRecord.from_json_dict(response["transactions"][0])
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
    await time_out_assert(20, get_unconfirmed_balance, INITIAL_FUNDS - tx_amount, client, 1)

    await farm_transaction(full_node_api, wallet_node, spend_bundle)

    # Checks that the memo can be retrieved
    tx_confirmed = (await client.get_transaction(GetTransaction(transaction_id))).transaction
    assert tx_confirmed.confirmed
    assert len(tx_confirmed.memos) == 1
    assert [b"this is a basic tx"] in tx_confirmed.memos.values()
    assert next(iter(tx_confirmed.memos.keys())) in [a.name() for a in spend_bundle.additions()]

    await time_out_assert(20, get_confirmed_balance, INITIAL_FUNDS - tx_amount, client, 1)


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
@pytest.mark.limit_consensus_modes(reason="irrelevant")
@pytest.mark.anyio
async def test_push_transactions(wallet_environments: WalletTestFramework) -> None:
    env = wallet_environments.environments[0]

    wallet: Wallet = env.xch_wallet
    wallet_node: WalletNode = env.node
    full_node_api: FullNodeSimulator = wallet_environments.full_node
    client: WalletRpcClient = env.rpc_client

    outputs = await create_tx_outputs(wallet, wallet_environments.tx_config, [(1234321, None)])

    tx = (
        await client.create_signed_transactions(
            outputs,
            tx_config=wallet_environments.tx_config,
            fee=uint64(100),
        )
    ).signed_tx

    resp_client = await client.push_transactions(
        PushTransactions(transactions=[tx], fee=uint64(10)),
        wallet_environments.tx_config,
    )
    resp = await client.fetch("push_transactions", {"transactions": [tx.to_json_dict()], "fee": 10})
    assert resp["success"]
    resp = await client.fetch("push_transactions", {"transactions": [bytes(tx).hex()], "fee": 10})
    assert resp["success"]

    spend_bundle = WalletSpendBundle.aggregate(
        [tx.spend_bundle for tx in resp_client.transactions if tx.spend_bundle is not None]
    )
    assert spend_bundle is not None
    await farm_transaction(full_node_api, wallet_node, spend_bundle)

    for tx in resp_client.transactions:
        assert (await client.get_transaction(GetTransaction(transaction_id=tx.name))).transaction.confirmed

    # Just testing NOT failure here really (parsing)
    await client.push_tx(PushTX(spend_bundle))
    resp = await client.fetch("push_tx", {"spend_bundle": bytes(spend_bundle).hex()})
    assert resp["success"]


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
@pytest.mark.limit_consensus_modes(reason="irrelevant")
@pytest.mark.anyio
async def test_get_balance(wallet_environments: WalletTestFramework) -> None:
    env = wallet_environments.environments[0]
    wallet: Wallet = env.xch_wallet
    wallet_node: WalletNode = env.node
    full_node_api: FullNodeSimulator = wallet_environments.full_node
    wallet_rpc_client = env.rpc_client
    async with wallet.wallet_state_manager.new_action_scope(wallet_environments.tx_config, push=True) as action_scope:
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


@pytest.mark.parametrize(
    "wallet_environments",
    [{"num_environments": 1, "blocks_needed": [2], "reuse_puzhash": True, "trusted": True}],
    indirect=True,
)
@pytest.mark.limit_consensus_modes(reason="irrelevant")
@pytest.mark.anyio
async def test_get_farmed_amount(wallet_environments: WalletTestFramework) -> None:
    env = wallet_environments.environments[0]
    wallet_rpc_client = env.rpc_client

    get_farmed_amount_result = await wallet_rpc_client.get_farmed_amount()
    get_timestamp_for_height_result = await wallet_rpc_client.get_timestamp_for_height(
        GetTimestampForHeight(uint32(3))
    )  # genesis + 2

    expected_result = {
        "blocks_won": 2,
        "farmed_amount": 4_000_000_000_000,
        "farmer_reward_amount": 500_000_000_000,
        "fee_amount": 0,
        "last_height_farmed": 3,
        "last_time_farmed": get_timestamp_for_height_result.timestamp,
        "pool_reward_amount": 3_500_000_000_000,
        "success": True,
    }
    assert get_farmed_amount_result == expected_result


@pytest.mark.parametrize(
    "wallet_environments",
    [{"num_environments": 1, "blocks_needed": [2], "reuse_puzhash": True, "trusted": True}],
    indirect=True,
)
@pytest.mark.limit_consensus_modes(reason="irrelevant")
@pytest.mark.anyio
async def test_get_farmed_amount_with_fee(wallet_environments: WalletTestFramework) -> None:
    env = wallet_environments.environments[0]
    wallet: Wallet = env.xch_wallet
    full_node_api: FullNodeSimulator = wallet_environments.full_node
    wallet_rpc_client = env.rpc_client
    wallet_node: WalletNode = env.node

    fee_amount = 100
    async with wallet.wallet_state_manager.new_action_scope(wallet_environments.tx_config, push=True) as action_scope:
        await wallet.generate_signed_transaction(
            amounts=[uint64(5)],
            puzzle_hashes=[bytes32.zeros],
            action_scope=action_scope,
            fee=uint64(fee_amount),
        )
        our_ph = await action_scope.get_puzzle_hash(wallet.wallet_state_manager)

    await full_node_api.wait_transaction_records_entered_mempool(records=action_scope.side_effects.transactions)
    await full_node_api.farm_blocks_to_puzzlehash(count=2, farm_to=our_ph, guarantee_transaction_blocks=True)
    await full_node_api.wait_for_wallet_synced(wallet_node=wallet_node, timeout=20)

    result = await wallet_rpc_client.get_farmed_amount()
    assert result["fee_amount"] == fee_amount


@pytest.mark.parametrize(
    "wallet_environments",
    [{"num_environments": 1, "blocks_needed": [1], "reuse_puzhash": True, "trusted": True}],
    indirect=True,
)
@pytest.mark.limit_consensus_modes(reason="irrelevant")
@pytest.mark.anyio
async def test_get_timestamp_for_height(wallet_environments: WalletTestFramework) -> None:
    env = wallet_environments.environments[0]
    client: WalletRpcClient = env.rpc_client

    # This tests that the client returns successfully, rather than raising or returning something unexpected
    await client.get_timestamp_for_height(GetTimestampForHeight(uint32(1)))


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
@pytest.mark.parametrize(
    "wallet_environments",
    [{"num_environments": 2, "blocks_needed": [2, 1], "config_overrides": {"automatically_add_unknown_cats": True}}],
    indirect=True,
)
@pytest.mark.limit_consensus_modes(reason="irrelevant")
@pytest.mark.anyio
async def test_create_signed_transaction(
    wallet_environments: WalletTestFramework,
    output_args: list[tuple[int, Optional[list[str]]]],
    fee: int,
    select_coin: bool,
    is_cat: bool,
) -> None:
    if (
        len(set(amount for amount, _ in output_args)) != len(output_args)
        and wallet_environments.tx_config.reuse_puzhash
    ):
        pytest.skip("Skipping reuse_puzhash + identical amounts for simplicity sake")
    env = wallet_environments.environments[0]
    env_2 = wallet_environments.environments[1]

    wallet_2: Wallet = env_2.xch_wallet
    wallet_1_rpc: WalletRpcClient = env.rpc_client
    full_node_rpc: FullNodeRpcClient = wallet_environments.full_node_rpc_client

    env.wallet_aliases = {"xch": 1, "cat": 2}
    env_2.wallet_aliases = {"xch": 1, "cat": 2}

    outputs = await create_tx_outputs(wallet_2, wallet_environments.tx_config, output_args)
    amount_outputs = sum(output["amount"] for output in outputs)
    amount_fee = uint64(fee)

    wallet_id = 1
    if is_cat:
        # +1 assures we'll have change
        res = await wallet_1_rpc.create_new_cat_and_wallet(uint64(amount_outputs + 1), test=True)
        assert res["success"]
        wallet_id = res["wallet_id"]

        await wallet_environments.process_pending_states(
            [
                WalletStateTransition(
                    pre_block_balance_updates={
                        "xch": {"set_remainder": True},
                        "cat": {"init": True, "set_remainder": True},
                    },
                    post_block_balance_updates={
                        "xch": {"set_remainder": True},
                        "cat": {"set_remainder": True},
                    },
                ),
                WalletStateTransition(
                    pre_block_balance_updates={},
                    post_block_balance_updates={},
                ),
            ]
        )

    if is_cat:
        amount_total = amount_outputs
    else:
        amount_total = amount_outputs + amount_fee

    selected_coin = None
    if select_coin:
        select_coins_response = await wallet_1_rpc.select_coins(
            SelectCoins.from_coin_selection_config(
                amount=amount_total,
                wallet_id=uint32(wallet_id),
                coin_selection_config=wallet_environments.tx_config.coin_selection_config,
            )
        )
        assert len(select_coins_response.coins) == 1
        selected_coin = select_coins_response.coins[0]

    txs = (
        await wallet_1_rpc.create_signed_transactions(
            outputs,
            coins=[selected_coin] if selected_coin is not None else [],
            fee=amount_fee,
            wallet_id=wallet_id,
            # shouldn't actually block it
            tx_config=wallet_environments.tx_config.override(
                excluded_coin_amounts=[uint64(selected_coin.amount)] if selected_coin is not None else [],
            ),
            push=True,
        )
    ).transactions
    change_expected = not selected_coin or selected_coin.amount - amount_total > 0
    assert_tx_amounts(txs[-1], outputs, amount_fee=amount_fee, change_expected=change_expected, is_cat=is_cat)

    # Farm the transaction and make sure the wallet balance reflects it correct
    spend_bundle = txs[0].spend_bundle
    assert spend_bundle is not None
    xch_delta = amount_total if not is_cat else amount_fee
    cat_delta = amount_total if is_cat else 0
    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={  # type: ignore[arg-type]
                    "xch": {
                        "unconfirmed_wallet_balance": -xch_delta,
                        "<=#spendable_balance": -xch_delta,
                        "<=#max_send_amount": -xch_delta,
                        ">=#pending_change": 0,
                        "pending_coin_removal_count": 1,
                    }
                }
                | (
                    {
                        "cat": {
                            "unconfirmed_wallet_balance": -cat_delta,
                            "<=#spendable_balance": -cat_delta,
                            "<=#max_send_amount": -cat_delta,
                            ">=#pending_change": 1 if is_cat else 0,
                            "pending_coin_removal_count": 1 if is_cat else 0,
                        }
                    }
                    if is_cat
                    else {}
                ),
                post_block_balance_updates={  # type: ignore[arg-type]
                    "xch": {
                        "confirmed_wallet_balance": -xch_delta,
                        ">=#spendable_balance": 0,
                        ">=#max_send_amount": 0,
                        "<=#pending_change": 0,
                        "pending_coin_removal_count": -1,
                        "<=#unspent_coin_count": 0,
                    }
                }
                | (
                    {
                        "cat": {
                            "confirmed_wallet_balance": -cat_delta,
                            ">=#spendable_balance": 1 if is_cat else 0,
                            ">=#max_send_amount": 1 if is_cat else 0,
                            "<=#pending_change": -1 if is_cat else 0,
                            "pending_coin_removal_count": -1 if is_cat else 0,
                        }
                    }
                    if is_cat
                    else {}
                ),
            ),
            WalletStateTransition(
                pre_block_balance_updates={},
                post_block_balance_updates={
                    "cat" if is_cat else "xch": {
                        "init": is_cat,
                        "confirmed_wallet_balance": amount_outputs,
                        "unconfirmed_wallet_balance": amount_outputs,
                        "spendable_balance": amount_outputs,
                        "max_send_amount": amount_outputs,
                        "unspent_coin_count": len(outputs),
                    }
                },
            ),
        ]
    )

    # Assert every coin comes from the same parent
    additions: list[Coin] = spend_bundle.additions()
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
    addition_dict: dict[bytes32, Coin] = {addition.name(): addition for addition in additions}
    memo_dictionary: dict[bytes32, list[bytes]] = compute_memos(spend_bundle)
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


@pytest.mark.parametrize(
    "wallet_environments",
    [{"num_environments": 2, "blocks_needed": [1, 1]}],
    indirect=True,
)
@pytest.mark.limit_consensus_modes(reason="irrelevant")
@pytest.mark.anyio
async def test_create_signed_transaction_with_coin_announcement(wallet_environments: WalletTestFramework) -> None:
    env = wallet_environments.environments[0]
    env_2 = wallet_environments.environments[1]

    wallet_2: Wallet = env_2.xch_wallet
    client: WalletRpcClient = env.rpc_client
    client_node: FullNodeRpcClient = wallet_environments.full_node_rpc_client

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
    outputs = await create_tx_outputs(wallet_2, wallet_environments.tx_config, [(signed_tx_amount, None)])
    tx_res: TransactionRecord = (
        await client.create_signed_transactions(
            outputs, tx_config=wallet_environments.tx_config, extra_conditions=(*tx_coin_announcements,)
        )
    ).signed_tx
    assert_tx_amounts(tx_res, outputs, amount_fee=uint64(0), change_expected=True)
    await assert_push_tx_error(client_node, tx_res)


@pytest.mark.parametrize(
    "wallet_environments",
    [{"num_environments": 2, "blocks_needed": [1, 1]}],
    indirect=True,
)
@pytest.mark.limit_consensus_modes(reason="irrelevant")
@pytest.mark.anyio
async def test_create_signed_transaction_with_puzzle_announcement(wallet_environments: WalletTestFramework) -> None:
    env = wallet_environments.environments[0]
    env_2 = wallet_environments.environments[1]

    wallet_2: Wallet = env_2.xch_wallet
    client: WalletRpcClient = env.rpc_client
    client_node: FullNodeRpcClient = wallet_environments.full_node_rpc_client

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
    outputs = await create_tx_outputs(wallet_2, wallet_environments.tx_config, [(signed_tx_amount, None)])
    tx_res = (
        await client.create_signed_transactions(
            outputs, tx_config=wallet_environments.tx_config, extra_conditions=(*tx_puzzle_announcements,)
        )
    ).signed_tx
    assert_tx_amounts(tx_res, outputs, amount_fee=uint64(0), change_expected=True)
    await assert_push_tx_error(client_node, tx_res)


@pytest.mark.parametrize(
    "wallet_environments",
    [{"num_environments": 1, "blocks_needed": [1]}],
    indirect=True,
)
@pytest.mark.limit_consensus_modes(reason="irrelevant")
@pytest.mark.anyio
async def test_create_signed_transaction_with_excluded_coins(wallet_environments: WalletTestFramework) -> None:
    env = wallet_environments.environments[0]
    wallet_1: Wallet = env.xch_wallet
    wallet_1_rpc: WalletRpcClient = env.rpc_client
    full_node_rpc: FullNodeRpcClient = wallet_environments.full_node_rpc_client

    async def it_does_not_include_the_excluded_coins() -> None:
        select_coins_response = await wallet_1_rpc.select_coins(
            SelectCoins.from_coin_selection_config(
                amount=uint64(250000000000),
                wallet_id=uint32(1),
                coin_selection_config=wallet_environments.tx_config.coin_selection_config,
            )
        )
        assert len(select_coins_response.coins) == 1
        outputs = await create_tx_outputs(wallet_1, wallet_environments.tx_config, [(uint64(250000000000), None)])

        tx = (
            await wallet_1_rpc.create_signed_transactions(
                outputs,
                wallet_environments.tx_config.override(
                    excluded_coin_ids=[c.name() for c in select_coins_response.coins],
                ),
            )
        ).signed_tx

        assert len(tx.removals) == 1
        assert tx.removals[0] != select_coins_response.coins[0]
        assert tx.removals[0].amount == uint64(1750000000000)
        await assert_push_tx_error(full_node_rpc, tx)

    async def it_throws_an_error_when_all_spendable_coins_are_excluded() -> None:
        select_coins_response = await wallet_1_rpc.select_coins(
            SelectCoins.from_coin_selection_config(
                amount=uint64(1750000000000),
                wallet_id=uint32(1),
                coin_selection_config=wallet_environments.tx_config.coin_selection_config,
            )
        )
        assert len(select_coins_response.coins) == 1
        outputs = await create_tx_outputs(wallet_1, wallet_environments.tx_config, [(uint64(1750000000000), None)])

        with pytest.raises(ValueError):
            await wallet_1_rpc.create_signed_transactions(
                outputs,
                wallet_environments.tx_config.override(
                    excluded_coin_ids=[c.name() for c in select_coins_response.coins],
                ),
            )

    await it_does_not_include_the_excluded_coins()
    await it_throws_an_error_when_all_spendable_coins_are_excluded()


@pytest.mark.parametrize(
    "wallet_environments",
    [{"num_environments": 2, "blocks_needed": [1, 1]}],
    indirect=True,
)
@pytest.mark.limit_consensus_modes(reason="irrelevant")
@pytest.mark.anyio
async def test_send_transaction_multi(wallet_environments: WalletTestFramework) -> None:
    env = wallet_environments.environments[0]
    env_2 = wallet_environments.environments[1]

    wallet_2: Wallet = env_2.xch_wallet
    wallet_node: WalletNode = env.node
    full_node_api: FullNodeSimulator = wallet_environments.full_node
    client: WalletRpcClient = env.rpc_client

    INITIAL_BALANCE = await env.xch_wallet.get_confirmed_balance()

    select_coins_response = await client.select_coins(
        SelectCoins.from_coin_selection_config(
            amount=uint64(1750000000000),
            wallet_id=uint32(1),
            coin_selection_config=wallet_environments.tx_config.coin_selection_config,
        )
    )  # we want a coin that won't be selected by default
    outputs = await create_tx_outputs(
        wallet_2, wallet_environments.tx_config, [(uint64(1), ["memo_1"]), (uint64(2), ["memo_2"])]
    )
    amount_outputs = sum(output["amount"] for output in outputs)
    amount_fee = uint64(amount_outputs + 1)

    send_tx_res: TransactionRecord = (
        await client.send_transaction_multi(
            1,
            outputs,
            wallet_environments.tx_config,
            coins=select_coins_response.coins,
            fee=amount_fee,
        )
    ).transaction
    spend_bundle = send_tx_res.spend_bundle
    assert spend_bundle is not None
    assert send_tx_res is not None

    assert_tx_amounts(send_tx_res, outputs, amount_fee=amount_fee, change_expected=True)
    assert send_tx_res.removals == select_coins_response.coins

    await farm_transaction(full_node_api, wallet_node, spend_bundle)

    await time_out_assert(20, get_confirmed_balance, INITIAL_BALANCE - amount_outputs - amount_fee, client, 1)

    # Checks that the memo can be retrieved
    tx_confirmed = (await client.get_transaction(GetTransaction(send_tx_res.name))).transaction
    assert tx_confirmed.confirmed
    memos = tx_confirmed.memos
    assert len(memos) == len(outputs)
    for output in outputs:
        assert [output["memos"][0].encode()] in memos.values()
    spend_bundle = send_tx_res.spend_bundle
    assert spend_bundle is not None
    for key in memos.keys():
        assert key in [a.name() for a in spend_bundle.additions()]


@pytest.mark.parametrize(
    "wallet_environments",
    [{"num_environments": 1, "blocks_needed": [3]}],
    indirect=True,
)
@pytest.mark.limit_consensus_modes(reason="irrelevant")
@pytest.mark.anyio
async def test_get_transactions(wallet_environments: WalletTestFramework) -> None:
    env = wallet_environments.environments[0]

    wallet: Wallet = env.xch_wallet
    wallet_node: WalletNode = env.node
    full_node_api: FullNodeSimulator = wallet_environments.full_node
    client: WalletRpcClient = env.rpc_client

    all_transactions = (await client.get_transactions(GetTransactions(uint32(1)))).transactions
    initially_farmed_blocks = 3
    # We expect 2 transactions per farmed block
    expected_initial_txs_count = initially_farmed_blocks * 2
    unconfirmed_txs_count = 0
    assert len(all_transactions) == expected_initial_txs_count
    # Test transaction pagination
    some_transactions = (await client.get_transactions(GetTransactions(uint32(1), uint16(0), uint16(5)))).transactions
    some_transactions_2 = (
        await client.get_transactions(GetTransactions(uint32(1), uint16(5), uint16(10)))
    ).transactions
    assert some_transactions == all_transactions[0:5]
    assert some_transactions_2 == all_transactions[5:10]

    # Testing sorts
    # Test the default sort (CONFIRMED_AT_HEIGHT)
    assert all_transactions == sorted(all_transactions, key=attrgetter("confirmed_at_height"))
    all_transactions = (await client.get_transactions(GetTransactions(uint32(1), reverse=True))).transactions
    assert all_transactions == sorted(all_transactions, key=attrgetter("confirmed_at_height"), reverse=True)

    # Test RELEVANCE
    async with wallet.wallet_state_manager.new_action_scope(wallet_environments.tx_config, push=True) as action_scope:
        puzhash = await action_scope.get_puzzle_hash(wallet.wallet_state_manager)
    await full_node_api.wait_for_wallet_synced(wallet_node=wallet_node, timeout=20)
    await client.send_transaction(
        SendTransaction(wallet_id=uint32(1), amount=uint64(1), address=encode_puzzle_hash(puzhash, "txch"), push=True),
        wallet_environments.tx_config,
    )  # Create a pending tx
    unconfirmed_txs_count += 1

    with pytest.raises(ValueError, match="There is no known sort foo"):
        await client.get_transactions(GetTransactions(uint32(1), sort_key="foo"))

    all_transactions = (
        await client.get_transactions(GetTransactions(uint32(1), sort_key=SortKey.RELEVANCE.name))
    ).transactions
    sorted_transactions = sorted(all_transactions, key=attrgetter("created_at_time"), reverse=True)
    sorted_transactions = sorted(sorted_transactions, key=attrgetter("confirmed_at_height"), reverse=True)
    sorted_transactions = sorted(sorted_transactions, key=attrgetter("confirmed"))
    assert all_transactions == sorted_transactions

    all_transactions = (
        await client.get_transactions(GetTransactions(uint32(1), sort_key=SortKey.RELEVANCE.name, reverse=True))
    ).transactions
    sorted_transactions = sorted(all_transactions, key=attrgetter("created_at_time"))
    sorted_transactions = sorted(sorted_transactions, key=attrgetter("confirmed_at_height"))
    sorted_transactions = sorted(sorted_transactions, key=attrgetter("confirmed"), reverse=True)
    assert all_transactions == sorted_transactions

    # Test get_transactions to address
    async with wallet.wallet_state_manager.new_action_scope(wallet_environments.tx_config, push=True) as action_scope:
        ph_by_addr = await action_scope.get_puzzle_hash(wallet.wallet_state_manager)
    await full_node_api.wait_for_wallet_synced(wallet_node=wallet_node, timeout=20)
    await client.send_transaction(
        SendTransaction(
            wallet_id=uint32(1), amount=uint64(1), address=encode_puzzle_hash(ph_by_addr, "txch"), push=True
        ),
        wallet_environments.tx_config,
    )
    unconfirmed_txs_count += 1
    await full_node_api.wait_for_wallet_synced(wallet_node=wallet_node, timeout=20)
    tx_for_address = (
        await client.get_transactions(GetTransactions(uint32(1), to_address=encode_puzzle_hash(ph_by_addr, "txch")))
    ).transactions
    assert (
        len(tx_for_address) == expected_initial_txs_count + unconfirmed_txs_count
        if wallet_environments.tx_config.reuse_puzhash
        else 1
    )
    assert tx_for_address[0].to_puzzle_hash == ph_by_addr

    # Test type filter
    all_transactions = (
        await client.get_transactions(
            GetTransactions(uint32(1), type_filter=TransactionTypeFilter.include([TransactionType.COINBASE_REWARD]))
        )
    ).transactions
    # Each farmed block creates one COINBASE_REWARD transaction
    assert len(all_transactions) == initially_farmed_blocks
    assert all(transaction.type == TransactionType.COINBASE_REWARD.value for transaction in all_transactions)
    # Test confirmed filter
    all_transactions = (await client.get_transactions(GetTransactions(uint32(1), confirmed=True))).transactions
    assert len(all_transactions) == expected_initial_txs_count
    assert all(transaction.confirmed for transaction in all_transactions)
    all_transactions = (await client.get_transactions(GetTransactions(uint32(1), confirmed=False))).transactions
    assert len(all_transactions) == unconfirmed_txs_count
    assert all(not transaction.confirmed for transaction in all_transactions)

    # Test bypass broken txs
    await wallet.wallet_state_manager.tx_store.add_transaction_record(
        dataclasses.replace(all_transactions[0], type=uint32(TransactionType.INCOMING_CLAWBACK_SEND))
    )
    all_transactions = (
        await client.get_transactions(
            GetTransactions(
                uint32(1),
                type_filter=TransactionTypeFilter.include([TransactionType.INCOMING_CLAWBACK_SEND]),
                confirmed=False,
            )
        )
    ).transactions
    assert len(all_transactions) == 1


@pytest.mark.parametrize(
    "wallet_environments",
    [{"num_environments": 1, "blocks_needed": [1]}],
    indirect=True,
)
@pytest.mark.limit_consensus_modes(reason="irrelevant")
@pytest.mark.anyio
async def test_get_transaction_count(wallet_environments: WalletTestFramework) -> None:
    env = wallet_environments.environments[0]
    client: WalletRpcClient = env.rpc_client

    all_transactions = (await client.get_transactions(GetTransactions(uint32(1)))).transactions
    assert len(all_transactions) > 0
    transaction_count_response = await client.get_transaction_count(GetTransactionCount(uint32(1)))
    assert transaction_count_response.count == len(all_transactions)
    transaction_count_response = await client.get_transaction_count(GetTransactionCount(uint32(1), confirmed=False))
    assert transaction_count_response.count == 0
    transaction_count_response = await client.get_transaction_count(
        GetTransactionCount(
            uint32(1), type_filter=TransactionTypeFilter.include([TransactionType.INCOMING_CLAWBACK_SEND])
        )
    )
    assert transaction_count_response.count == 0


@pytest.mark.parametrize(
    "wallet_environments",
    [
        {
            "num_environments": 2,
            "blocks_needed": [1, 1],
        }
    ],
    indirect=True,
)
@pytest.mark.limit_consensus_modes(reason="irrelevant")
@pytest.mark.parametrize("wallet_type", [CATWallet, RCATWallet])
@pytest.mark.anyio
async def test_cat_endpoints(wallet_environments: WalletTestFramework, wallet_type: type[CATWallet]) -> None:
    env_0 = wallet_environments.environments[0]
    env_1 = wallet_environments.environments[1]
    env_0.wallet_aliases = {
        "xch": 1,
        "cat0": 2,
        "cat1": 3,
    }
    env_1.wallet_aliases = {
        "xch": 1,
        "cat0": 2,
    }
    # Test a deprecated path
    with pytest.raises(ValueError, match="dropped"):
        await env_0.rpc_client.fetch(
            "create_new_wallet",
            {
                "wallet_type": "cat_wallet",
                "mode": "new",
            },
        )

    # Creates a CAT wallet with 100 mojos and a CAT with 20 mojos and fee=10
    await mint_cat(
        wallet_environments,
        env_0,
        "xch",
        "cat0",
        uint64(100),
        wallet_type,
        "cat0",
    )
    await mint_cat(
        wallet_environments,
        env_0,
        "xch",
        "cat1",
        uint64(20),
        wallet_type,
        "cat1",
    )

    cat_0_id = uint32(env_0.wallet_aliases["cat0"])
    # The RPC response contains more than just the balance info but all the
    # balance info should match. We're leveraging the `<=` operator to check
    # for subset on `dict` `.items()`.
    assert (
        env_0.wallet_states[uint32(env_0.wallet_aliases["cat0"])].balance.to_json_dict().items()
        <= (await env_0.rpc_client.get_wallet_balance(GetWalletBalance(cat_0_id))).wallet_balance.to_json_dict().items()
    )
    asset_id = (await env_0.rpc_client.get_cat_asset_id(CATGetAssetID(cat_0_id))).asset_id
    assert (
        await env_0.rpc_client.get_cat_name(CATGetName(cat_0_id))
    ).name == wallet_type.default_wallet_name_for_unknown_cat(asset_id.hex())
    await env_0.rpc_client.set_cat_name(CATSetName(cat_0_id, "My cat"))
    assert (await env_0.rpc_client.get_cat_name(CATGetName(cat_0_id))).name == "My cat"
    asset_to_name_response = await env_0.rpc_client.cat_asset_id_to_name(CATAssetIDToName(asset_id))
    assert asset_to_name_response.wallet_id == cat_0_id
    assert asset_to_name_response.name == "My cat"
    asset_to_name_response = await env_0.rpc_client.cat_asset_id_to_name(CATAssetIDToName(bytes32.zeros))
    assert asset_to_name_response.name is None
    verified_asset_id = next(iter(DEFAULT_CATS.items()))[1]["asset_id"]
    asset_to_name_response = await env_0.rpc_client.cat_asset_id_to_name(
        CATAssetIDToName(bytes32.from_hexstr(verified_asset_id))
    )
    assert asset_to_name_response.wallet_id is None
    assert asset_to_name_response.name == next(iter(DEFAULT_CATS.items()))[1]["name"]

    # Creates a second wallet with the same CAT
    res = await env_1.rpc_client.create_wallet_for_existing_cat(asset_id)
    assert res["success"]
    cat_1_id = res["wallet_id"]
    cat_1_asset_id = bytes.fromhex(res["asset_id"])
    assert cat_1_asset_id == asset_id

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(),
            WalletStateTransition(
                pre_block_balance_updates={
                    "cat0": {
                        "init": True,
                    }
                },
                post_block_balance_updates={},
            ),
        ]
    )

    addr_0 = (await env_0.rpc_client.get_next_address(GetNextAddress(cat_0_id, False))).address
    addr_1 = (await env_1.rpc_client.get_next_address(GetNextAddress(cat_1_id, False))).address

    assert addr_0 != addr_1

    # Test CAT spend without a fee
    with pytest.raises(ValueError):
        await env_0.rpc_client.cat_spend(
            CATSpend(
                wallet_id=cat_0_id,
                amount=uint64(4),
                inner_address=addr_1,
                fee=uint64(0),
                memos=["the cat memo"],
                push=False,
            ),
            tx_config=wallet_environments.tx_config.override(
                excluded_coin_amounts=[uint64(100)],
                excluded_coin_ids=[bytes32.zeros],
            ),
        )

    # Test some validation errors
    with pytest.raises(
        ValueError,
        match=re.escape('Must specify "additions" or "amount"+"inner_address"+"memos", but not both.'),
    ):
        await env_0.rpc_client.cat_spend(
            CATSpend(
                wallet_id=cat_0_id,
                amount=uint64(4),
                inner_address=addr_1,
                memos=["the cat memo"],
                additions=[],
            ),
            tx_config=wallet_environments.tx_config,
        )

    with pytest.raises(ValueError, match=re.escape('Must specify "amount" and "inner_address" together.')):
        await env_0.rpc_client.cat_spend(
            CATSpend(
                wallet_id=cat_0_id,
                amount=uint64(4),
                inner_address=None,
            ),
            tx_config=wallet_environments.tx_config,
        )

    with pytest.raises(
        ValueError,
        match=re.escape('Must specify \\"extra_delta\\", \\"tail_reveal\\" and \\"tail_solution\\" together.'),
    ):
        await env_0.rpc_client.cat_spend(
            CATSpend(
                wallet_id=cat_0_id,
                additions=[],
                extra_delta="1",
            ),
            tx_config=wallet_environments.tx_config,
        )

    tx_res = await env_0.rpc_client.cat_spend(
        CATSpend(
            wallet_id=cat_0_id,
            amount=uint64(4),
            inner_address=addr_1,
            fee=uint64(0),
            memos=["the cat memo"],
            push=True,
        ),
        tx_config=wallet_environments.tx_config,
    )

    spend_bundle = tx_res.transaction.spend_bundle
    assert spend_bundle is not None
    assert uncurry_puzzle(spend_bundle.coin_spends[0].puzzle_reveal).mod == CAT_MOD

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "cat0": {
                        "unconfirmed_wallet_balance": -4,
                        "spendable_balance": -100,
                        "max_send_amount": -100,
                        "pending_change": 96,
                        "pending_coin_removal_count": 1,
                    }
                },
                post_block_balance_updates={
                    "cat0": {
                        "confirmed_wallet_balance": -4,
                        "spendable_balance": 96,
                        "max_send_amount": 96,
                        "pending_change": -96,
                        "pending_coin_removal_count": -1,
                    }
                },
            ),
            WalletStateTransition(
                pre_block_balance_updates={},
                post_block_balance_updates={
                    "cat0": {
                        "confirmed_wallet_balance": 4,
                        "unconfirmed_wallet_balance": 4,
                        "spendable_balance": 4,
                        "max_send_amount": 4,
                        "unspent_coin_count": 1,
                    }
                },
            ),
        ]
    )

    # Test CAT spend with a fee
    tx_res = await env_0.rpc_client.cat_spend(
        CATSpend(
            wallet_id=cat_0_id,
            amount=uint64(1),
            inner_address=addr_1,
            fee=uint64(5_000_000),
            memos=["the cat memo"],
            push=True,
        ),
        wallet_environments.tx_config,
    )

    spend_bundle = tx_res.transaction.spend_bundle
    assert spend_bundle is not None

    cat_spend_changes = [
        WalletStateTransition(
            pre_block_balance_updates={
                "xch": {
                    "unconfirmed_wallet_balance": -5_000_000,
                    "<=#spendable_balance": -5_000_000,
                    "<=#max_send_amount": -5_000_000,
                    ">=#pending_change": 1,  # any amount increase
                    "unspent_coin_count": 0,
                    "pending_coin_removal_count": 1,
                },
                "cat0": {
                    "unconfirmed_wallet_balance": -1,
                    "<=#spendable_balance": -1,
                    "<=#max_send_amount": -1,
                    ">=#pending_change": 1,
                    "pending_coin_removal_count": 1,
                },
            },
            post_block_balance_updates={
                "xch": {
                    "confirmed_wallet_balance": -5_000_000,
                    ">=#spendable_balance": 1,  # any amount increase
                    ">=#max_send_amount": 1,  # any amount increase
                    "<=#pending_change": -1,  # any amount decrease
                    "unspent_coin_count": 0,
                    "pending_coin_removal_count": -1,
                },
                "cat0": {
                    "confirmed_wallet_balance": -1,
                    ">=#spendable_balance": 1,  # any amount increase
                    ">=#max_send_amount": 1,  # any amount increase
                    "<=#pending_change": -1,  # any amount decrease
                    "pending_coin_removal_count": -1,
                },
            },
        ),
        WalletStateTransition(
            pre_block_balance_updates={},
            post_block_balance_updates={
                "cat0": {
                    "confirmed_wallet_balance": 1,
                    "unconfirmed_wallet_balance": 1,
                    "spendable_balance": 1,
                    "max_send_amount": 1,
                    "unspent_coin_count": 1,
                },
            },
        ),
    ]
    await wallet_environments.process_pending_states(cat_spend_changes)

    # Test CAT spend with a fee and pre-specified removals / coins
    select_coins_response = await env_0.rpc_client.select_coins(
        SelectCoins.from_coin_selection_config(
            amount=uint64(2),
            wallet_id=cat_0_id,
            coin_selection_config=wallet_environments.tx_config.coin_selection_config,
        )
    )
    tx_res = await env_0.rpc_client.cat_spend(
        CATSpend(
            wallet_id=cat_0_id,
            amount=uint64(1),
            inner_address=addr_1,
            fee=uint64(5_000_000),
            memos=["the cat memo"],
            coins=select_coins_response.coins,
            push=True,
        ),
        wallet_environments.tx_config,
    )

    spend_bundle = tx_res.transaction.spend_bundle
    assert spend_bundle is not None
    assert select_coins_response.coins[0] in {removal for tx in tx_res.transactions for removal in tx.removals}

    await wallet_environments.process_pending_states(cat_spend_changes)

    # Test unacknowledged CAT
    await env_0.wallet_state_manager.interested_store.add_unacknowledged_token(
        asset_id, "Unknown", uint32(10000), bytes32(b"\00" * 32)
    )
    stray_cats_response = await env_0.rpc_client.get_stray_cats()
    assert len(stray_cats_response.stray_cats) == 1

    # Test CAT coin selection
    select_coins_response = await env_0.rpc_client.select_coins(
        SelectCoins.from_coin_selection_config(
            amount=uint64(1),
            wallet_id=cat_0_id,
            coin_selection_config=wallet_environments.tx_config.coin_selection_config,
        )
    )
    assert len(select_coins_response.coins) > 0

    # Test get_cat_list
    cat_list = (await env_0.rpc_client.get_cat_list()).cat_list
    assert len(DEFAULT_CATS) == len(cat_list)
    default_cats_set = {
        DefaultCAT(asset_id=bytes32.from_hexstr(cat["asset_id"]), name=cat["name"], symbol=cat["symbol"])
        for cat in DEFAULT_CATS.values()
    }
    assert default_cats_set == set(cat_list)


@pytest.mark.parametrize(
    "wallet_environments",
    [
        {
            "num_environments": 2,
            "blocks_needed": [1, 1],
        }
    ],
    indirect=True,
)
@pytest.mark.limit_consensus_modes(reason="irrelevant")
@pytest.mark.parametrize("wallet_type", [CATWallet, RCATWallet])
@pytest.mark.anyio
async def test_offer_endpoints(wallet_environments: WalletTestFramework, wallet_type: type[CATWallet]) -> None:
    env_1 = wallet_environments.environments[0]
    env_2 = wallet_environments.environments[1]

    env_1.wallet_aliases = {
        "xch": 1,
        "cat": 2,
    }
    env_2.wallet_aliases = {
        "xch": 1,
        "cat": 2,
    }

    # Creates a CAT wallet with 20 mojos
    cat_wallet = await mint_cat(
        wallet_environments,
        env_1,
        "xch",
        "cat",
        uint64(20),
        wallet_type,
        "cat",
    )
    cat_wallet_id = cat_wallet.id()
    cat_asset_id = cat_wallet.cat_info.limitations_program_hash

    # Creates a wallet for the same CAT on wallet_2 and send 4 CAT from wallet_1 to it
    await env_2.rpc_client.create_wallet_for_existing_cat(cat_asset_id)
    wallet_2_address = (await env_2.rpc_client.get_next_address(GetNextAddress(cat_wallet_id, False))).address
    adds = [{"puzzle_hash": decode_puzzle_hash(wallet_2_address), "amount": uint64(4), "memos": ["the cat memo"]}]
    tx_res = (
        await env_1.rpc_client.send_transaction_multi(
            cat_wallet_id, additions=adds, tx_config=wallet_environments.tx_config, fee=uint64(0)
        )
    ).transaction
    spend_bundle = tx_res.spend_bundle
    assert spend_bundle is not None

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "cat": {
                        "unconfirmed_wallet_balance": -4,
                        "spendable_balance": -20,
                        "max_send_amount": -20,
                        "pending_change": 16,
                        "pending_coin_removal_count": 1,
                    }
                },
                post_block_balance_updates={
                    "cat": {
                        "confirmed_wallet_balance": -4,
                        "spendable_balance": 16,
                        "max_send_amount": 16,
                        "pending_change": -16,
                        "pending_coin_removal_count": -1,
                    }
                },
            ),
            WalletStateTransition(
                pre_block_balance_updates={"cat": {"init": True}},
                post_block_balance_updates={
                    "cat": {
                        "confirmed_wallet_balance": 4,
                        "unconfirmed_wallet_balance": 4,
                        "spendable_balance": 4,
                        "max_send_amount": 4,
                        "unspent_coin_count": 1,
                    }
                },
            ),
        ]
    )

    test_crs: list[CoinRecord] = (
        await env_1.rpc_client.get_coin_records_by_names(
            GetCoinRecordsByNames([a.name() for a in spend_bundle.additions() if a.amount != 4])
        )
    ).coin_records
    for cr in test_crs:
        assert cr.coin in spend_bundle.additions()
    with pytest.raises(ValueError):
        await env_1.rpc_client.get_coin_records_by_names(
            GetCoinRecordsByNames([a.name() for a in spend_bundle.additions() if a.amount == 4])
        )
    # Create an offer of 5 chia for one CAT
    await env_1.rpc_client.create_offer_for_ids(
        CreateOfferForIDs(offer={str(1): "-5", cat_asset_id.hex(): "1"}, validate_only=True),
        tx_config=wallet_environments.tx_config,
    )
    all_offers = await env_1.rpc_client.get_all_offers()
    assert len(all_offers) == 0

    driver_dict = {
        cat_asset_id: PuzzleInfo(
            {
                "type": "CAT",
                "tail": "0x" + cat_asset_id.hex(),
                **(
                    {}
                    if wallet_type is CATWallet
                    else {"also": {"type": "revocation layer", "hidden_puzzle_hash": "0x" + bytes32.zeros.hex()}}
                ),
            }
        )
    }

    create_res = await env_1.rpc_client.create_offer_for_ids(
        CreateOfferForIDs(offer={str(1): "-5", cat_asset_id.hex(): "1"}, driver_dict=driver_dict, fee=uint64(1)),
        tx_config=wallet_environments.tx_config,
    )
    offer = create_res.offer

    offer_summary_response = await env_1.rpc_client.get_offer_summary(GetOfferSummary(offer.to_bech32()))
    assert offer_summary_response.id == offer.name()
    offer_summary_response_advanced = await env_1.rpc_client.get_offer_summary(
        GetOfferSummary(offer.to_bech32(), advanced=True)
    )
    assert offer_summary_response_advanced.id == offer.name()
    assert offer_summary_response_advanced.summary == OfferSummary(
        offered={"xch": "5"},
        requested={cat_asset_id.hex(): "1"},
        infos={key.hex(): info for key, info in driver_dict.items()},
        fees=uint64(1),
        additions=[c.name() for c in offer.additions()],
        removals=[c.name() for c in offer.removals()],
        valid_times=ConditionValidTimesAbsolute(),
    )
    assert offer_summary_response_advanced.summary == offer_summary_response.summary

    offer_validity_response = await env_1.rpc_client.check_offer_validity(CheckOfferValidity(offer.to_bech32()))
    assert offer_validity_response.id == offer.name()
    assert offer_validity_response.valid

    all_offers = await env_1.rpc_client.get_all_offers(file_contents=True)
    assert len(all_offers) == 1
    assert TradeStatus(all_offers[0].status) == TradeStatus.PENDING_ACCEPT
    assert all_offers[0].offer == bytes(offer)

    offer_count = await env_1.rpc_client.get_offers_count()
    assert offer_count.total == 1
    assert offer_count.my_offers_count == 1
    assert offer_count.taken_offers_count == 0

    trade_record = (
        await env_2.rpc_client.take_offer(
            TakeOffer(
                offer=offer.to_bech32(),
                fee=uint64(1),
                push=True,
            ),
            wallet_environments.tx_config,
        )
    ).trade_record
    assert TradeStatus(trade_record.status) == TradeStatus.PENDING_CONFIRM

    await env_1.rpc_client.cancel_offer(offer.name(), wallet_environments.tx_config, secure=False)

    trade_record = await env_1.rpc_client.get_offer(offer.name(), file_contents=True)
    assert trade_record.offer == bytes(offer)
    assert TradeStatus(trade_record.status) == TradeStatus.CANCELLED

    failed_cancel_res = await env_1.rpc_client.cancel_offer(
        offer.name(), wallet_environments.tx_config, fee=uint64(1), secure=True
    )

    trade_record = await env_1.rpc_client.get_offer(offer.name())
    assert TradeStatus(trade_record.status) == TradeStatus.PENDING_CANCEL

    create_res = await env_1.rpc_client.create_offer_for_ids(
        CreateOfferForIDs(offer={str(1): "-5", str(cat_wallet_id): "1"}, fee=uint64(1)),
        tx_config=wallet_environments.tx_config,
    )
    all_offers = await env_1.rpc_client.get_all_offers()
    assert len(all_offers) == 2
    offer_count = await env_1.rpc_client.get_offers_count()
    assert offer_count.total == 2
    assert offer_count.my_offers_count == 2
    assert offer_count.taken_offers_count == 0
    new_trade_record = create_res.trade_record

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {
                        "unconfirmed_wallet_balance": -1,  # The cancellation that won't complete
                        "<=#spendable_balance": -5,
                        "<=#max_send_amount": -5,
                        "unspent_coin_count": 0,
                        ">=#pending_change": 1,  # any amount increase (again, cancellation)
                        "pending_coin_removal_count": 2,  # one for each open offer
                    },
                    "cat": {},
                },
                post_block_balance_updates={
                    "xch": {
                        "confirmed_wallet_balance": -5 - 1,
                        "unconfirmed_wallet_balance": -5 - 1 + 1,  # cancellation TX now failed
                        ">=#spendable_balance": 1,  # any amount increase
                        ">=#max_send_amount": 1,  # any amount increase
                        "<=#pending_change": -1,  # any amount decrease (cancellation TX now failed)
                        "pending_coin_removal_count": -1,
                    },
                    "cat": {
                        "confirmed_wallet_balance": 1,
                        "unconfirmed_wallet_balance": 1,
                        "spendable_balance": 1,
                        "max_send_amount": 1,
                        "unspent_coin_count": 1,
                    },
                },
            ),
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {
                        "unconfirmed_wallet_balance": 5 - 1,
                        "<=#spendable_balance": -1,  # any amount decrease
                        "<=#max_send_amount": -1,  # any amount decrease
                        ">=#pending_change": 1,  # any amount increase
                        "pending_coin_removal_count": 1,
                    },
                    "cat": {
                        "unconfirmed_wallet_balance": -1,
                        "<=#spendable_balance": -1,  # any amount decrease
                        "<=#max_send_amount": -1,  # any amount decrease
                        ">=#pending_change": 1,  # any amount increase
                        "pending_coin_removal_count": 1,
                    },
                },
                post_block_balance_updates={
                    "xch": {
                        "confirmed_wallet_balance": 5 - 1,
                        ">=#spendable_balance": 1,  # any amount increase
                        ">=#max_send_amount": 1,  # any amount increase
                        "<=#pending_change": -1,  # any amount decrease
                        "pending_coin_removal_count": -1,
                        "unspent_coin_count": 1,
                    },
                    "cat": {
                        "confirmed_wallet_balance": -1,
                        ">=#spendable_balance": 1,  # any amount increase
                        ">=#max_send_amount": 1,  # any amount increase
                        "<=#pending_change": -1,  # any amount decrease
                        "pending_coin_removal_count": -1,
                    },
                },
            ),
        ],
        invalid_transactions=[tx.name for tx in failed_cancel_res.transactions],
    )

    async def is_trade_confirmed(client: WalletRpcClient, offer: Offer) -> bool:
        trade_record = await client.get_offer(offer.name())
        return TradeStatus(trade_record.status) == TradeStatus.CONFIRMED

    await time_out_assert(15, is_trade_confirmed, True, env_1.rpc_client, offer)

    # Test trade sorting
    def only_ids(trades: list[TradeRecord]) -> list[bytes32]:
        return [t.trade_id for t in trades]

    trade_record = await env_1.rpc_client.get_offer(offer.name())
    all_offers = await env_1.rpc_client.get_all_offers(include_completed=True)  # confirmed at index descending
    assert len(all_offers) == 2
    assert only_ids(all_offers) == only_ids([trade_record, new_trade_record])
    all_offers = await env_1.rpc_client.get_all_offers(
        include_completed=True, reverse=True
    )  # confirmed at index ascending
    assert only_ids(all_offers) == only_ids([new_trade_record, trade_record])
    all_offers = await env_1.rpc_client.get_all_offers(include_completed=True, sort_key="RELEVANCE")  # most relevant
    assert only_ids(all_offers) == only_ids([new_trade_record, trade_record])
    all_offers = await env_1.rpc_client.get_all_offers(
        include_completed=True, sort_key="RELEVANCE", reverse=True
    )  # least relevant
    assert only_ids(all_offers) == only_ids([trade_record, new_trade_record])
    # Test pagination
    all_offers = await env_1.rpc_client.get_all_offers(include_completed=True, start=0, end=1)
    assert len(all_offers) == 1
    all_offers = await env_1.rpc_client.get_all_offers(include_completed=True, start=50)
    assert len(all_offers) == 0
    all_offers = await env_1.rpc_client.get_all_offers(include_completed=True, start=0, end=50)
    assert len(all_offers) == 2

    await env_1.rpc_client.create_offer_for_ids(
        CreateOfferForIDs(offer={str(1): "-5", cat_asset_id.hex(): "1"}, driver_dict=driver_dict),
        tx_config=wallet_environments.tx_config,
    )
    assert (
        len([o for o in await env_1.rpc_client.get_all_offers() if o.status == TradeStatus.PENDING_ACCEPT.value]) == 2
    )
    await env_1.rpc_client.cancel_offers(wallet_environments.tx_config, batch_size=1)
    assert (
        len([o for o in await env_1.rpc_client.get_all_offers() if o.status == TradeStatus.PENDING_ACCEPT.value]) == 0
    )
    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {
                        "<=#spendable_balance": -5,
                        "<=#max_send_amount": -5,
                        ">=#pending_change": 1,  # any amount increase
                        "pending_coin_removal_count": 1,
                    },
                    "cat": {},
                },
                post_block_balance_updates={
                    "xch": {
                        ">=#spendable_balance": 1,  # any amount increase
                        ">=#max_send_amount": 1,  # any amount increase
                        "<=#pending_change": -1,  # any amount decrease
                        "pending_coin_removal_count": -2,
                    },
                    "cat": {},
                },
            ),
            WalletStateTransition(),
        ]
    )

    await env_1.rpc_client.create_offer_for_ids(
        CreateOfferForIDs(offer={str(1): "-5", cat_asset_id.hex(): "1"}, driver_dict=driver_dict),
        tx_config=wallet_environments.tx_config,
    )
    await env_1.rpc_client.create_offer_for_ids(
        CreateOfferForIDs(offer={str(1): "5", cat_asset_id.hex(): "-1"}, driver_dict=driver_dict),
        tx_config=wallet_environments.tx_config,
    )
    assert (
        len([o for o in await env_1.rpc_client.get_all_offers() if o.status == TradeStatus.PENDING_ACCEPT.value]) == 2
    )
    await env_1.rpc_client.cancel_offers(wallet_environments.tx_config, cancel_all=True)
    assert (
        len([o for o in await env_1.rpc_client.get_all_offers() if o.status == TradeStatus.PENDING_ACCEPT.value]) == 0
    )

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {
                        "<=#spendable_balance": -5,
                        "<=#max_send_amount": -5,
                        ">=#pending_change": 1,  # any amount increase
                        "pending_coin_removal_count": 1,
                    },
                    "cat": {
                        "<=#spendable_balance": -1,
                        "<=#max_send_amount": -1,
                        ">=#pending_change": 1,  # any amount increase
                        "pending_coin_removal_count": 1,
                    },
                },
                post_block_balance_updates={
                    "xch": {
                        ">=#spendable_balance": 5,
                        ">=#max_send_amount": 5,
                        "<=#pending_change": -1,  # any amount decrease
                        "pending_coin_removal_count": -1,
                    },
                    "cat": {
                        ">=#spendable_balance": 1,
                        ">=#max_send_amount": 1,
                        "<=#pending_change": -1,  # any amount decrease
                        "pending_coin_removal_count": -1,
                    },
                },
            ),
            WalletStateTransition(),
        ]
    )

    await env_1.rpc_client.create_offer_for_ids(
        CreateOfferForIDs(offer={str(1): "5", cat_asset_id.hex(): "-1"}, driver_dict=driver_dict),
        tx_config=wallet_environments.tx_config,
    )
    assert (
        len([o for o in await env_1.rpc_client.get_all_offers() if o.status == TradeStatus.PENDING_ACCEPT.value]) == 1
    )
    await env_1.rpc_client.cancel_offers(wallet_environments.tx_config, asset_id=bytes32.zeros)
    assert (
        len([o for o in await env_1.rpc_client.get_all_offers() if o.status == TradeStatus.PENDING_ACCEPT.value]) == 1
    )
    await env_1.rpc_client.cancel_offers(wallet_environments.tx_config, asset_id=cat_asset_id)
    assert (
        len([o for o in await env_1.rpc_client.get_all_offers() if o.status == TradeStatus.PENDING_ACCEPT.value]) == 0
    )

    with pytest.raises(ValueError, match="not currently supported"):
        await env_1.rpc_client.create_offer_for_ids(
            CreateOfferForIDs(
                offer={str(1): "-5", cat_asset_id.hex(): "1"},
                driver_dict=driver_dict,
            ),
            wallet_environments.tx_config,
            timelock_info=ConditionValidTimes(min_secs_since_created=uint64(1)),
        )


@pytest.mark.parametrize(
    "wallet_environments",
    [{"num_environments": 1, "blocks_needed": [5]}],
    indirect=True,
)
@pytest.mark.limit_consensus_modes(reason="irrelevant")
@pytest.mark.anyio
async def test_get_coin_records_by_names(wallet_environments: WalletTestFramework) -> None:
    env = wallet_environments.environments[0]
    wallet_node: WalletNode = env.node
    client: WalletRpcClient = env.rpc_client
    store = wallet_node.wallet_state_manager.coin_store
    full_node_api = wallet_environments.full_node

    INITIAL_BALANCE = await env.xch_wallet.get_confirmed_balance()
    async with env.wallet_state_manager.new_action_scope(wallet_environments.tx_config, push=True) as action_scope:
        address = encode_puzzle_hash(await action_scope.get_puzzle_hash(env.wallet_state_manager), "txch")
    await full_node_api.wait_for_wallet_synced(wallet_node=wallet_node, timeout=20)

    # Spend half of it back to the same wallet get some spent coins in the wallet
    tx = (
        await client.send_transaction(
            SendTransaction(wallet_id=uint32(1), amount=uint64(INITIAL_BALANCE / 2), address=address, push=True),
            wallet_environments.tx_config,
        )
    ).transaction
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
    assert (await client.get_coin_records_by_names(GetCoinRecordsByNames([]))).coin_records == []
    # 2. All coins
    rpc_result = await client.get_coin_records_by_names(GetCoinRecordsByNames(coin_ids + coin_ids_unspent))
    assert {record.coin for record in rpc_result.coin_records} == {*coins, *coins_unspent}
    # 3. All spent coins
    rpc_result = await client.get_coin_records_by_names(GetCoinRecordsByNames(coin_ids, include_spent_coins=True))
    assert {record.coin for record in rpc_result.coin_records} == coins
    # 4. All unspent coins
    rpc_result = await client.get_coin_records_by_names(
        GetCoinRecordsByNames(coin_ids_unspent, include_spent_coins=False)
    )
    assert {record.coin for record in rpc_result.coin_records} == coins_unspent
    # 5. Filter start/end height
    filter_records = result.records[:10]
    assert len(filter_records) == 10
    filter_coin_ids = [record.name() for record in filter_records]
    filter_coins = {record.coin for record in filter_records}
    min_height = min(record.confirmed_block_height for record in filter_records)
    max_height = max(record.confirmed_block_height for record in filter_records)
    assert min_height != max_height
    rpc_result = await client.get_coin_records_by_names(
        GetCoinRecordsByNames(filter_coin_ids, start_height=min_height, end_height=max_height)
    )
    assert {record.coin for record in rpc_result.coin_records} == filter_coins
    # 8. Test the failure case
    with pytest.raises(ValueError, match="not found"):
        await client.get_coin_records_by_names(GetCoinRecordsByNames(coin_ids, include_spent_coins=False))


@pytest.mark.parametrize(
    "wallet_environments",
    [{"num_environments": 2, "blocks_needed": [1, 1]}],
    indirect=True,
)
@pytest.mark.limit_consensus_modes(reason="irrelevant")
@pytest.mark.anyio
async def test_did_endpoints(wallet_environments: WalletTestFramework) -> None:
    env = wallet_environments.environments[0]
    env_2 = wallet_environments.environments[1]

    env.wallet_aliases = {
        "xch": 1,
        "did": 2,
        "nft": 3,
    }
    env_2.wallet_aliases = {
        "xch": 1,
        "did": 2,
    }

    wallet_1: Wallet = env.xch_wallet
    wallet_2: Wallet = env_2.xch_wallet
    wallet_1_node: WalletNode = env.node
    wallet_2_node: WalletNode = env_2.node
    wallet_1_rpc: WalletRpcClient = env.rpc_client
    wallet_2_rpc: WalletRpcClient = env_2.rpc_client
    wallet_1_id = wallet_1.id()

    # Create a DID wallet
    res = await wallet_1_rpc.create_new_did_wallet(amount=1, tx_config=wallet_environments.tx_config, name="Profile 1")
    assert res["success"]
    did_wallet_id_0 = res["wallet_id"]
    did_id_0 = res["my_did"]
    await env.change_balances({"did": {"init": True, "set_remainder": True}})
    await env.change_balances({"nft": {"init": True, "set_remainder": True}})

    # Get wallet name
    get_name_res = await wallet_1_rpc.did_get_wallet_name(DIDGetWalletName(did_wallet_id_0))
    assert get_name_res.name == "Profile 1"
    nft_wallet = wallet_1_node.wallet_state_manager.wallets[did_wallet_id_0 + 1]
    assert isinstance(nft_wallet, NFTWallet)
    assert nft_wallet.get_name() == "Profile 1 NFT Wallet"

    # Set wallet name
    new_wallet_name = "test name"
    await wallet_1_rpc.did_set_wallet_name(DIDSetWalletName(did_wallet_id_0, new_wallet_name))
    get_name_res = await wallet_1_rpc.did_get_wallet_name(DIDGetWalletName(did_wallet_id_0))
    assert get_name_res.name == new_wallet_name
    with pytest.raises(ValueError, match="wallet id 1 is of type Wallet but type DIDWallet is required"):
        await wallet_1_rpc.did_set_wallet_name(DIDSetWalletName(wallet_1_id, new_wallet_name))

    # Check DID ID
    did_id_res = await wallet_1_rpc.get_did_id(DIDGetDID(did_wallet_id_0))
    assert did_id_0 == did_id_res.my_did
    # Create backup file
    await wallet_1_rpc.create_did_backup_file(DIDCreateBackupFile(did_wallet_id_0))

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {"set_remainder": True},
                    "did": {"set_remainder": True},
                },
                post_block_balance_updates={
                    "xch": {"set_remainder": True},
                    "did": {"set_remainder": True},
                },
            ),
            WalletStateTransition(),
        ]
    )

    # Update metadata
    with pytest.raises(ValueError, match="wallet id 1 is of type Wallet but type DIDWallet is required"):
        await wallet_1_rpc.update_did_metadata(
            DIDUpdateMetadata(wallet_id=wallet_1_id, metadata={"Twitter": "Https://test"}, push=True),
            wallet_environments.tx_config,
        )
    await wallet_1_rpc.update_did_metadata(
        DIDUpdateMetadata(wallet_id=did_wallet_id_0, metadata={"Twitter": "Https://test"}, push=True),
        wallet_environments.tx_config,
    )

    get_metadata_res = await wallet_1_rpc.get_did_metadata(DIDGetMetadata(did_wallet_id_0))
    assert get_metadata_res.metadata["Twitter"] == "Https://test"

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {"set_remainder": True},
                    "did": {"set_remainder": True},
                },
                post_block_balance_updates={
                    "xch": {"set_remainder": True},
                    "did": {"set_remainder": True},
                },
            ),
            WalletStateTransition(),
        ]
    )

    # Transfer DID
    async with wallet_2.wallet_state_manager.new_action_scope(wallet_environments.tx_config, push=True) as action_scope:
        addr = encode_puzzle_hash(await action_scope.get_puzzle_hash(wallet_2.wallet_state_manager), "txch")
    await wallet_1_rpc.did_transfer_did(
        DIDTransferDID(
            wallet_id=did_wallet_id_0, inner_address=addr, fee=uint64(0), with_recovery_info=True, push=True
        ),
        wallet_environments.tx_config,
    )

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {"set_remainder": True},
                    "did": {"set_remainder": True},
                },
                post_block_balance_updates={
                    "xch": {"set_remainder": True},
                },
            ),
            WalletStateTransition(
                post_block_balance_updates={
                    "did": {"init": True, "set_remainder": True},
                }
            ),
        ]
    )

    async def num_wallets() -> int:
        return len(await wallet_2_node.wallet_state_manager.get_all_wallet_info_entries())

    await time_out_assert(30, num_wallets, 2)

    did_wallets = list(
        filter(
            lambda w: (w.type == WalletType.DECENTRALIZED_ID.value),
            await wallet_2_node.wallet_state_manager.get_all_wallet_info_entries(),
        )
    )
    did_wallet_2 = wallet_2_node.wallet_state_manager.wallets[did_wallets[0].id]
    assert isinstance(did_wallet_2, DIDWallet)
    assert (
        encode_puzzle_hash(bytes32.from_hexstr(did_wallet_2.get_my_DID()), AddressType.DID.hrp(wallet_2_node.config))
        == did_id_0
    )
    metadata = json.loads(did_wallet_2.did_info.metadata)
    assert metadata["Twitter"] == "Https://test"

    last_did_coin = await did_wallet_2.get_coin()
    await wallet_2_rpc.did_message_spend(
        DIDMessageSpend(wallet_id=did_wallet_2.id(), push=True), wallet_environments.tx_config
    )
    await wallet_2_node.wallet_state_manager.add_interested_coin_ids([last_did_coin.name()])

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(),
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {"set_remainder": True},
                    "did": {"set_remainder": True},
                },
                post_block_balance_updates={
                    "xch": {"set_remainder": True},
                    "did": {"set_remainder": True},
                },
            ),
        ]
    )

    next_did_coin = await did_wallet_2.get_coin()
    assert next_did_coin.parent_coin_info == last_did_coin.name()
    last_did_coin = next_did_coin

    await wallet_2_rpc.did_message_spend(
        DIDMessageSpend(wallet_id=did_wallet_2.id(), push=True),
        wallet_environments.tx_config.override(reuse_puzhash=True),
    )
    await wallet_2_node.wallet_state_manager.add_interested_coin_ids([last_did_coin.name()])

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(),
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {"set_remainder": True},
                    "did": {"set_remainder": True},
                },
                post_block_balance_updates={
                    "xch": {"set_remainder": True},
                    "did": {"set_remainder": True},
                },
            ),
        ]
    )

    next_did_coin = await did_wallet_2.get_coin()
    assert next_did_coin.parent_coin_info == last_did_coin.name()
    assert next_did_coin.puzzle_hash == last_did_coin.puzzle_hash

    # Test did_get_pubkey
    pubkey_res = await wallet_2_rpc.get_did_pubkey(DIDGetPubkey(did_wallet_2.id()))
    assert isinstance(pubkey_res.pubkey, G1Element)


@pytest.mark.parametrize(
    "wallet_environments",
    [{"num_environments": 2, "blocks_needed": [1, 1]}],
    indirect=True,
)
@pytest.mark.limit_consensus_modes(reason="irrelevant")
@pytest.mark.anyio
async def test_nft_endpoints(wallet_environments: WalletTestFramework) -> None:
    env = wallet_environments.environments[0]
    env_2 = wallet_environments.environments[1]
    wallet_1_node: WalletNode = env.node
    wallet_1_rpc: WalletRpcClient = env.rpc_client
    wallet_2: Wallet = env_2.xch_wallet
    wallet_2_node: WalletNode = env_2.node
    wallet_2_rpc: WalletRpcClient = env_2.rpc_client

    env.wallet_aliases = {
        "xch": 1,
        "nft": 2,
    }
    env_2.wallet_aliases = {
        "xch": 1,
        "nft": 2,
    }

    res = await wallet_1_rpc.create_new_nft_wallet(None)
    nft_wallet_id = res["wallet_id"]
    await wallet_1_rpc.mint_nft(
        request=NFTMintNFTRequest(
            wallet_id=nft_wallet_id,
            royalty_address=None,
            target_address=None,
            hash=bytes32.from_hexstr("0xD4584AD463139FA8C0D9F68F4B59F185D4584AD463139FA8C0D9F68F4B59F185"),
            uris=["https://www.chia.net/img/branding/chia-logo.svg"],
            push=True,
        ),
        tx_config=wallet_environments.tx_config,
    )

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {"set_remainder": True},
                    "nft": {"init": True, "set_remainder": True},
                },
                post_block_balance_updates={
                    "xch": {"set_remainder": True},
                    "nft": {"set_remainder": True},
                },
            ),
            WalletStateTransition(),
        ]
    )

    nft_wallet = wallet_1_node.wallet_state_manager.wallets[nft_wallet_id]
    assert isinstance(nft_wallet, NFTWallet)

    async def have_nfts() -> bool:
        return await nft_wallet.get_nft_count() > 0

    await time_out_assert(15, have_nfts, True)

    # Test with the hex version of nft_id
    nft_id = (await nft_wallet.get_current_nfts())[0].coin.name().hex()
    with pytest.raises(ResponseFailureError, match="Invalid Coin ID format for 'coin_id'"):
        await wallet_1_rpc.get_nft_info(NFTGetInfo("error"))
    nft_info = (await wallet_1_rpc.get_nft_info(NFTGetInfo(nft_id))).nft_info
    assert nft_info.nft_coin_id == (await nft_wallet.get_current_nfts())[0].coin.name()
    # Test with the bech32m version of nft_id
    hmr_nft_id = encode_puzzle_hash(
        (await nft_wallet.get_current_nfts())[0].coin.name(), AddressType.NFT.hrp(wallet_1_node.config)
    )
    nft_info = (await wallet_1_rpc.get_nft_info(NFTGetInfo(hmr_nft_id))).nft_info
    assert nft_info.nft_coin_id == (await nft_wallet.get_current_nfts())[0].coin.name()

    async with wallet_2.wallet_state_manager.new_action_scope(wallet_environments.tx_config, push=True) as action_scope:
        addr = encode_puzzle_hash(await action_scope.get_puzzle_hash(wallet_2.wallet_state_manager), "txch")
    await wallet_1_rpc.transfer_nft(
        NFTTransferNFT(wallet_id=nft_wallet_id, nft_coin_id=nft_id, target_address=addr, push=True),
        wallet_environments.tx_config,
    )

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {"set_remainder": True},
                    "nft": {"set_remainder": True},
                },
                post_block_balance_updates={
                    "xch": {"set_remainder": True},
                    "nft": {"set_remainder": True},
                },
            ),
            WalletStateTransition(
                pre_block_balance_updates={},
                post_block_balance_updates={
                    "xch": {"set_remainder": True},
                    "nft": {"init": True, "set_remainder": True},
                },
            ),
        ]
    )

    nft_wallet_id_1 = (
        await wallet_2_node.wallet_state_manager.get_all_wallet_info_entries(wallet_type=WalletType.NFT)
    )[0].id
    nft_wallet_1 = wallet_2_node.wallet_state_manager.wallets[nft_wallet_id_1]
    assert isinstance(nft_wallet_1, NFTWallet)
    nft_info_1 = (await wallet_1_rpc.get_nft_info(NFTGetInfo(nft_id, False))).nft_info
    assert nft_info_1 == nft_info
    nft_info_1 = (await wallet_1_rpc.get_nft_info(NFTGetInfo(nft_id))).nft_info
    assert nft_info_1.nft_coin_id == (await nft_wallet_1.get_current_nfts())[0].coin.name()
    # Cross-check NFT
    nft_info_2 = (await wallet_2_rpc.list_nfts(NFTGetNFTs(nft_wallet_id_1))).nft_list[0]
    assert nft_info_1 == nft_info_2
    nft_info_2 = (await wallet_2_rpc.list_nfts(NFTGetNFTs())).nft_list[0]
    assert nft_info_1 == nft_info_2

    # Test royalty endpoint
    with pytest.raises(ValueError, match="Multiple royalty assets with same name specified"):
        await wallet_1_rpc.nft_calculate_royalties(
            NFTCalculateRoyalties(
                [
                    RoyaltyAsset(
                        "my asset",
                        "my address",
                        uint16(10000),
                    ),
                    RoyaltyAsset(
                        "my asset",
                        "some other address",
                        uint16(11111),
                    ),
                ],
                [],
            )
        )
    with pytest.raises(ValueError, match="Multiple fungible assets with same name specified"):
        await wallet_1_rpc.nft_calculate_royalties(
            NFTCalculateRoyalties(
                [],
                [
                    FungibleAsset(
                        None,
                        uint64(10000),
                    ),
                    FungibleAsset(
                        None,
                        uint64(11111),
                    ),
                ],
            )
        )
    royalty_summary = await wallet_1_rpc.nft_calculate_royalties(
        NFTCalculateRoyalties(
            [
                RoyaltyAsset(
                    "my asset",
                    "my address",
                    uint16(10000),
                )
            ],
            [
                FungibleAsset(
                    None,
                    uint64(10000),
                )
            ],
        )
    )
    assert royalty_summary.to_json_dict() == {
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
    farmer_ph = puzzle_hash_for_pk(create_sk(sk, uint32(0)).get_g1())

    sk = await wallet_node.get_key_for_fingerprint(pool_fp, private=True)
    assert sk is not None
    pool_ph = puzzle_hash_for_pk(create_sk(sk, uint32(0)).get_g1())

    with lock_and_load_config(wallet_node.root_path, "config.yaml") as test_config:
        test_config["farmer"]["xch_target_address"] = encode_puzzle_hash(farmer_ph, "txch")
        test_config["pool"]["xch_target_address"] = encode_puzzle_hash(pool_ph, "txch")
        save_config(wallet_node.root_path, "config.yaml", test_config)

    # Check farmer_fp key
    resp = await client.check_delete_key(CheckDeleteKey(uint32(farmer_fp)))
    assert resp.fingerprint == farmer_fp
    assert resp.used_for_farmer_rewards is True
    assert resp.used_for_pool_rewards is False

    # Check pool_fp key
    resp = await client.check_delete_key(CheckDeleteKey(uint32(pool_fp)))
    assert resp.fingerprint == pool_fp
    assert resp.used_for_farmer_rewards is False
    assert resp.used_for_pool_rewards is True

    # Check unknown key
    resp = await client.check_delete_key(CheckDeleteKey(uint32(123456), uint16(10)))
    assert resp.fingerprint == 123456
    assert resp.used_for_farmer_rewards is False
    assert resp.used_for_pool_rewards is False


@pytest.mark.parametrize(
    "wallet_environments",
    [{"num_environments": 1, "blocks_needed": [1]}],
    indirect=True,
)
@pytest.mark.limit_consensus_modes(reason="irrelevant")
@pytest.mark.anyio
async def test_key_and_address_endpoints(wallet_environments: WalletTestFramework) -> None:
    env = wallet_environments.environments[0]

    wallet: Wallet = env.xch_wallet
    wallet_node: WalletNode = env.node
    client: WalletRpcClient = env.rpc_client

    address = (await client.get_next_address(GetNextAddress(uint32(1), True))).address
    assert len(address) > 10

    pks = (await client.get_public_keys()).pk_fingerprints
    assert len(pks) == 1

    assert (await client.get_height_info()).height > 0

    async with wallet.wallet_state_manager.new_action_scope(wallet_environments.tx_config, push=True) as action_scope:
        ph = await action_scope.get_puzzle_hash(wallet.wallet_state_manager)
    addr = encode_puzzle_hash(ph, "txch")
    tx_amount = uint64(15600000)
    created_tx = (
        await client.send_transaction(
            SendTransaction(wallet_id=uint32(1), amount=tx_amount, address=addr, push=True),
            wallet_environments.tx_config,
        )
    ).transaction

    await time_out_assert(20, tx_in_mempool, True, client, created_tx.name)
    assert len(await wallet.wallet_state_manager.tx_store.get_unconfirmed_for_wallet(1)) == 1
    await client.delete_unconfirmed_transactions(DeleteUnconfirmedTransactions(uint32(1)))
    assert len(await wallet.wallet_state_manager.tx_store.get_unconfirmed_for_wallet(1)) == 0

    sk_resp = await client.get_private_key(GetPrivateKey(pks[0]))
    assert sk_resp.private_key.fingerprint == pks[0]
    assert sk_resp.private_key.seed is not None

    resp = await client.generate_mnemonic()
    assert len(resp.mnemonic) == 24

    await client.add_key(AddKey(resp.mnemonic))

    pks = (await client.get_public_keys()).pk_fingerprints
    assert len(pks) == 2

    await client.log_in(LogIn(pks[1]))
    sk_resp = await client.get_private_key(GetPrivateKey(pks[1]))
    assert sk_resp.private_key.fingerprint == pks[1]

    # test hardened keys
    await _check_delete_key(client=client, wallet_node=wallet_node, farmer_fp=pks[0], pool_fp=pks[1], observer=False)

    # test observer keys
    await _check_delete_key(client=client, wallet_node=wallet_node, farmer_fp=pks[0], pool_fp=pks[1], observer=True)

    # set farmer to empty string
    with lock_and_load_config(wallet_node.root_path, "config.yaml") as test_config:
        test_config["farmer"]["xch_target_address"] = ""
        save_config(wallet_node.root_path, "config.yaml", test_config)

    # Check key
    delete_key_resp = await client.check_delete_key(CheckDeleteKey(pks[1]))
    assert delete_key_resp.fingerprint == pks[1]
    assert delete_key_resp.used_for_farmer_rewards is False
    assert delete_key_resp.used_for_pool_rewards is True

    # set farmer and pool to empty string
    with lock_and_load_config(wallet_node.root_path, "config.yaml") as test_config:
        test_config["farmer"]["xch_target_address"] = ""
        test_config["pool"]["xch_target_address"] = ""
        save_config(wallet_node.root_path, "config.yaml", test_config)

    # Check key
    delete_key_resp = await client.check_delete_key(CheckDeleteKey(pks[0]))
    assert delete_key_resp.fingerprint == pks[0]
    assert delete_key_resp.used_for_farmer_rewards is False
    assert delete_key_resp.used_for_pool_rewards is False

    assert get_wallet_db_path(wallet_node.root_path, wallet_node.config, str(pks[0])).exists()
    await client.delete_key(DeleteKey(pks[0]))
    assert not get_wallet_db_path(wallet_node.root_path, wallet_node.config, str(pks[0])).exists()
    await client.log_in(LogIn(uint32(pks[1])))
    assert len((await client.get_public_keys()).pk_fingerprints) == 1

    assert not (await client.get_sync_status()).synced

    wallets = (await client.get_wallets(GetWallets())).wallets
    assert len(wallets) == 1
    assert await get_unconfirmed_balance(client, int(wallets[0].id)) == 0

    with pytest.raises(ValueError):
        await client.send_transaction(
            SendTransaction(wallet_id=uint32(wallets[0].id), amount=uint64(100), address=addr, push=True),
            wallet_environments.tx_config,
        )

    # Delete all keys
    resp = await client.generate_mnemonic()
    add_key_resp = await client.add_key(AddKey(resp.mnemonic))
    assert get_wallet_db_path(wallet_node.root_path, wallet_node.config, str(pks[1])).exists()
    assert get_wallet_db_path(wallet_node.root_path, wallet_node.config, str(add_key_resp.fingerprint)).exists()
    await client.delete_all_keys()
    assert not get_wallet_db_path(wallet_node.root_path, wallet_node.config, str(pks[1])).exists()
    assert not get_wallet_db_path(wallet_node.root_path, wallet_node.config, str(add_key_resp.fingerprint)).exists()
    assert len((await client.get_public_keys()).pk_fingerprints) == 0


@pytest.mark.parametrize(
    "wallet_environments",
    [{"num_environments": 2, "blocks_needed": [1, 0]}],
    indirect=True,
)
@pytest.mark.limit_consensus_modes(reason="irrelevant")
@pytest.mark.anyio
async def test_select_coins_rpc(wallet_environments: WalletTestFramework) -> None:
    env = wallet_environments.environments[0]
    env_2 = wallet_environments.environments[1]

    env.wallet_aliases = {"xch": 1}
    env_2.wallet_aliases = {"xch": 1}

    wallet_2: Wallet = env_2.xch_wallet
    client: WalletRpcClient = env.rpc_client
    client_2: WalletRpcClient = env_2.rpc_client

    funds: int = await env.xch_wallet.get_confirmed_balance()

    # since this wallet farms no blocks, this first request will always make a new puzzle hash
    with wallet_environments.new_puzzle_hashes_allowed():
        async with wallet_2.wallet_state_manager.new_action_scope(
            wallet_environments.tx_config, push=True
        ) as action_scope:
            addr = encode_puzzle_hash(await action_scope.get_puzzle_hash(wallet_2.wallet_state_manager), "txch")
    coin_300: list[Coin]
    tx_amounts: list[uint64] = [uint64(1000), uint64(300), uint64(1000), uint64(1000), uint64(10000)]
    for tx_amount in tx_amounts:
        funds -= tx_amount
        # create coins for tests
        tx = (
            await client.send_transaction(
                SendTransaction(wallet_id=uint32(1), amount=tx_amount, address=addr, push=True),
                wallet_environments.tx_config,
            )
        ).transaction
        spend_bundle = tx.spend_bundle
        assert spend_bundle is not None
        for coin in spend_bundle.additions():
            if coin.amount == uint64(300):
                coin_300 = [coin]

        await wallet_environments.process_pending_states(
            [
                WalletStateTransition(
                    pre_block_balance_updates={"xch": {"set_remainder": True}},
                    post_block_balance_updates={"xch": {"set_remainder": True}},
                ),
                WalletStateTransition(
                    pre_block_balance_updates={},
                    post_block_balance_updates={"xch": {"set_remainder": True}},
                ),
            ]
        )

    # test min coin amount
    min_coins_response = await client_2.select_coins(
        SelectCoins.from_coin_selection_config(
            amount=uint64(1000),
            wallet_id=uint32(1),
            coin_selection_config=wallet_environments.tx_config.coin_selection_config.override(
                min_coin_amount=uint64(1001)
            ),
        )
    )
    assert len(min_coins_response.coins) == 1
    assert min_coins_response.coins[0].amount == uint64(10_000)

    # test max coin amount
    max_coins_reponse = await client_2.select_coins(
        SelectCoins.from_coin_selection_config(
            amount=uint64(2000),
            wallet_id=uint32(1),
            coin_selection_config=wallet_environments.tx_config.coin_selection_config.override(
                min_coin_amount=uint64(999), max_coin_amount=uint64(9999)
            ),
        )
    )
    assert len(max_coins_reponse.coins) == 2
    assert max_coins_reponse.coins[0].amount == uint64(1000)

    # test excluded coin amounts
    non_1000_amt: int = sum(a for a in tx_amounts if a != 1000)
    excluded_amt_coins_response = await client_2.select_coins(
        SelectCoins.from_coin_selection_config(
            amount=uint64(non_1000_amt),
            wallet_id=uint32(1),
            coin_selection_config=wallet_environments.tx_config.coin_selection_config.override(
                excluded_coin_amounts=[uint64(1000)]
            ),
        )
    )
    assert len(excluded_amt_coins_response.coins) == len([a for a in tx_amounts if a != 1000])
    assert sum(c.amount for c in excluded_amt_coins_response.coins) == non_1000_amt

    # test excluded coins
    with pytest.raises(ValueError):
        await client_2.select_coins(
            SelectCoins.from_coin_selection_config(
                amount=uint64(5000),
                wallet_id=uint32(1),
                coin_selection_config=wallet_environments.tx_config.coin_selection_config.override(
                    excluded_coin_ids=[c.name() for c in min_coins_response.coins]
                ),
            )
        )
    excluded_test_response = await client_2.select_coins(
        SelectCoins.from_coin_selection_config(
            amount=uint64(1300),
            wallet_id=uint32(1),
            coin_selection_config=wallet_environments.tx_config.coin_selection_config.override(
                excluded_coin_ids=[c.name() for c in coin_300]
            ),
        )
    )
    assert len(excluded_test_response.coins) == 2
    for coin in excluded_test_response.coins:
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
    spendable_coins_response = await client_2.get_spendable_coins(
        GetSpendableCoins.from_coin_selection_config(
            wallet_id=uint32(1),
            coin_selection_config=wallet_environments.tx_config.coin_selection_config.override(
                excluded_coin_ids=[c.name() for c in excluded_amt_coins_response.coins]
            ),
        ),
    )
    assert (
        set(excluded_amt_coins_response.coins).intersection(
            {rec.coin for rec in spendable_coins_response.confirmed_records}
        )
        == set()
    )
    spendable_coins_response = await client_2.get_spendable_coins(
        GetSpendableCoins.from_coin_selection_config(
            wallet_id=uint32(1),
            coin_selection_config=wallet_environments.tx_config.coin_selection_config.override(
                excluded_coin_amounts=[uint64(1000)]
            ),
        )
    )
    assert len([rec for rec in spendable_coins_response.confirmed_records if rec.coin.amount == 1000]) == 0
    spendable_coins_response = await client_2.get_spendable_coins(
        GetSpendableCoins.from_coin_selection_config(
            wallet_id=uint32(1),
            coin_selection_config=wallet_environments.tx_config.coin_selection_config.override(
                max_coin_amount=uint64(999)
            ),
        )
    )
    assert spendable_coins_response.confirmed_records[0].coin == coin_300[0]
    with pytest.raises(ValueError):  # validate fail on invalid coin id.
        await client_2.get_spendable_coins(
            GetSpendableCoins.from_coin_selection_config(
                wallet_id=uint32(1),
                coin_selection_config=wallet_environments.tx_config.coin_selection_config.override(
                    excluded_coin_ids=[b"a"]
                ),
            )
        )


@pytest.mark.parametrize(
    "wallet_environments",
    [{"num_environments": 1, "blocks_needed": [0], "reuse_puzhash": True, "trusted": True}],
    indirect=True,
)
@pytest.mark.limit_consensus_modes(reason="irrelevant")
@pytest.mark.anyio
async def test_get_coin_records_rpc(wallet_environments: WalletTestFramework) -> None:
    env = wallet_environments.environments[0]
    wallet_node: WalletNode = env.node
    client: WalletRpcClient = env.rpc_client
    store = wallet_node.wallet_state_manager.coin_store

    for record in [record_1, record_2, record_3, record_4, record_5, record_6, record_7, record_8, record_9]:
        await store.add_coin_record(record)

    async def run_test_case(
        test_case: str,
        test_request: GetCoinRecords,
        test_total_count: Optional[int],
        test_records: list[WalletCoinRecord],
    ) -> None:
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


@pytest.mark.parametrize(
    "wallet_environments",
    [{"num_environments": 1, "blocks_needed": [0], "reuse_puzhash": True, "trusted": True}],
    indirect=True,
)
@pytest.mark.limit_consensus_modes(reason="irrelevant")
@pytest.mark.anyio
async def test_get_coin_records_rpc_limits(wallet_environments: WalletTestFramework) -> None:
    env = wallet_environments.environments[0]
    wallet_node: WalletNode = env.node
    client: WalletRpcClient = env.rpc_client
    store = wallet_node.wallet_state_manager.coin_store

    # Adjust the limits for faster testing
    WalletRpcApi.max_get_coin_records_limit = uint32(5)
    WalletRpcApi.max_get_coin_records_filter_items = uint32(5)

    max_coins = WalletRpcApi.max_get_coin_records_limit * 10
    coin_records = [
        WalletCoinRecord(
            Coin(bytes32(bytes([i] * 32)), bytes32(bytes([i] * 32)), uint64(i)),
            uint32(i),
            uint32(0),
            False,
            False,
            WalletType.STANDARD_WALLET,
            uint32(0),
            CoinType.NORMAL,
            None,
        )
        for i in range(max_coins)
    ]
    for record in coin_records:
        await store.add_coin_record(record)

    limit = WalletRpcApi.max_get_coin_records_limit
    response_records = []
    for i in range(int(max_coins / WalletRpcApi.max_get_coin_records_limit)):
        offset = uint32(WalletRpcApi.max_get_coin_records_limit * i)
        response = await client.get_coin_records(GetCoinRecords(limit=limit, offset=offset, include_total_count=True))
        response_records.extend(list(response["coin_records"]))

    assert len(response_records) == max_coins
    # Make sure we got all expected records
    parsed_records = [coin.to_json_dict_parsed_metadata() for coin in coin_records]
    for expected_record in parsed_records:
        assert expected_record in response_records

    # Request coins with the max number of filter items
    max_filter_items = WalletRpcApi.max_get_coin_records_filter_items
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


@pytest.mark.parametrize(
    "wallet_environments",
    [{"num_environments": 1, "blocks_needed": [0], "reuse_puzhash": True, "trusted": True}],
    indirect=True,
)
@pytest.mark.limit_consensus_modes(reason="irrelevant")
@pytest.mark.anyio
async def test_get_coin_records_rpc_failures(wallet_environments: WalletTestFramework) -> None:
    env = wallet_environments.environments[0]
    client: WalletRpcClient = env.rpc_client

    too_many_hashes = [bytes32.secret() for i in range(WalletRpcApi.max_get_coin_records_filter_items + 1)]
    too_many_amounts = [uint64(i) for i in range(WalletRpcApi.max_get_coin_records_filter_items + 1)]
    # Run requests which exceeds the allowed limit and contain too much filter items
    for name, request in {
        "limit": GetCoinRecords(limit=uint32(WalletRpcApi.max_get_coin_records_limit + 1)),
        "coin_id_filter": GetCoinRecords(coin_id_filter=HashFilter.include(too_many_hashes)),
        "puzzle_hash_filter": GetCoinRecords(puzzle_hash_filter=HashFilter.include(too_many_hashes)),
        "parent_coin_id_filter": GetCoinRecords(parent_coin_id_filter=HashFilter.include(too_many_hashes)),
        "amount_filter": GetCoinRecords(amount_filter=AmountFilter.include(too_many_amounts)),
    }.items():
        with pytest.raises(ValueError, match=name):
            await client.get_coin_records(request)


@pytest.mark.parametrize(
    "wallet_environments",
    [
        {
            "num_environments": 2,
            "blocks_needed": [1, 1],
            "config_overrides": {"enable_notifications": True, "required_notification_amount": 100000000000},
        }
    ],
    indirect=True,
)
@pytest.mark.limit_consensus_modes(reason="irrelevant")
@pytest.mark.anyio
async def test_notification_rpcs(wallet_environments: WalletTestFramework) -> None:
    env = wallet_environments.environments[0]
    env_2 = wallet_environments.environments[1]

    env.wallet_aliases = {"xch": 1}
    env_2.wallet_aliases = {"xch": 1}

    wallet_2: Wallet = env_2.xch_wallet
    client: WalletRpcClient = env.rpc_client
    client_2: WalletRpcClient = env_2.rpc_client

    async with wallet_2.wallet_state_manager.new_action_scope(wallet_environments.tx_config, push=True) as action_scope:
        await client.send_notification(
            SendNotification(
                target=(await action_scope.get_puzzle_hash(wallet_2.wallet_state_manager)),
                message=b"hello",
                amount=uint64(100000000000),
                fee=uint64(100000000000),
                push=True,
            ),
            tx_config=wallet_environments.tx_config,
        )

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {"set_remainder": True},
                },
                post_block_balance_updates={
                    "xch": {"set_remainder": True},
                },
            ),
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {"set_remainder": True},
                },
                post_block_balance_updates={
                    "xch": {"set_remainder": True},
                },
            ),
        ]
    )

    notification = (await client_2.get_notifications(GetNotifications())).notifications[0]
    assert [notification] == (await client_2.get_notifications(GetNotifications([notification.id]))).notifications
    assert [] == (await client_2.get_notifications(GetNotifications(None, uint32(0), uint32(0)))).notifications
    assert [notification] == (await client_2.get_notifications(GetNotifications(None, None, uint32(1)))).notifications
    assert [] == (await client_2.get_notifications(GetNotifications(None, uint32(1), None))).notifications
    assert [notification] == (await client_2.get_notifications(GetNotifications(None, None, None))).notifications
    await client_2.delete_notifications(DeleteNotifications())
    assert [] == (await client_2.get_notifications(GetNotifications([notification.id]))).notifications

    async with wallet_2.wallet_state_manager.new_action_scope(wallet_environments.tx_config, push=True) as action_scope:
        await client.send_notification(
            SendNotification(
                target=(await action_scope.get_puzzle_hash(wallet_2.wallet_state_manager)),
                message=b"hello",
                amount=uint64(100000000000),
                fee=uint64(100000000000),
                push=True,
            ),
            tx_config=wallet_environments.tx_config,
        )

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {"set_remainder": True},
                },
                post_block_balance_updates={
                    "xch": {"set_remainder": True},
                },
            ),
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {"set_remainder": True},
                },
                post_block_balance_updates={
                    "xch": {"set_remainder": True},
                },
            ),
        ]
    )

    notification = (await client_2.get_notifications(GetNotifications())).notifications[0]
    await client_2.delete_notifications(DeleteNotifications([notification.id]))
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
                    "89d8e2a225c2ff543222bd0f2ba457a44acbdd147e4dfa02eadaef73eae49450dc708fd7c86800b60e8bc456e77563e4"
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
                    "8e156d106f1b0ff0ebbe5ab27b1797a19cf3e895a7a435b003a1df2dd477d622be928379625b759ef3b388b286ee8658"
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
                    "8e156d106f1b0ff0ebbe5ab27b1797a19cf3e895a7a435b003a1df2dd477d622be928379625b759ef3b388b286ee8658"
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
                    "8fba5482e6c798a06ee1fd95deaaa83f11c46da06006ab3524e917f4e116c2bdec69d6098043ca568290ac366e5e2dc5"
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
                    "89d8e2a225c2ff543222bd0f2ba457a44acbdd147e4dfa02eadaef73eae49450dc708fd7c86800b60e8bc456e77563e4"
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
                    "8e156d106f1b0ff0ebbe5ab27b1797a19cf3e895a7a435b003a1df2dd477d622be928379625b759ef3b388b286ee8658"
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
                    "8fba5482e6c798a06ee1fd95deaaa83f11c46da06006ab3524e917f4e116c2bdec69d6098043ca568290ac366e5e2dc5"
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
@pytest.mark.parametrize(
    "wallet_environments",
    [
        {
            "num_environments": 1,
            "blocks_needed": [1],
            "reuse_puzhash": True,
            "trusted": True,
        }
    ],
    indirect=True,
)
@pytest.mark.anyio
@pytest.mark.limit_consensus_modes(reason="irrelevant")
async def test_verify_signature(
    wallet_environments: WalletTestFramework,
    rpc_request: dict[str, Any],
    rpc_response: VerifySignatureResponse,
    prefix_hex_strings: bool,
) -> None:
    updated_request = rpc_request.copy()
    updated_request["pubkey"] = ("0x" if prefix_hex_strings else "") + updated_request["pubkey"]
    updated_request["signature"] = ("0x" if prefix_hex_strings else "") + updated_request["signature"]
    res = await wallet_environments.environments[0].rpc_client.verify_signature(
        VerifySignature.from_json_dict(updated_request)
    )
    assert res == rpc_response


@pytest.mark.parametrize(
    "wallet_environments",
    [{"num_environments": 2, "blocks_needed": [1, 0]}],
    indirect=True,
)
@pytest.mark.limit_consensus_modes(reason="irrelevant")
@pytest.mark.anyio
async def test_set_wallet_resync_on_startup(wallet_environments: WalletTestFramework) -> None:
    env = wallet_environments.environments[0]
    env_2 = wallet_environments.environments[1]
    client: WalletRpcClient = env.rpc_client
    wc = env.rpc_client

    env.wallet_aliases = {
        "xch": 1,
        "did": 2,
        "nft1": 3,
        "nft0": 4,
    }

    await wc.create_new_did_wallet(1, wallet_environments.tx_config, 0)

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {"set_remainder": True},
                    "did": {"init": True, "set_remainder": True},
                    "nft1": {"init": True, "set_remainder": True},
                },
                post_block_balance_updates={
                    "xch": {"set_remainder": True},
                    "did": {"set_remainder": True},
                    "nft1": {"set_remainder": True},
                },
            ),
            WalletStateTransition(),
        ]
    )

    nft_wallet = await wc.create_new_nft_wallet(None)
    nft_wallet_id = nft_wallet["wallet_id"]
    address = (await wc.get_next_address(GetNextAddress(env.xch_wallet.id(), True))).address
    await wc.mint_nft(
        request=NFTMintNFTRequest(
            wallet_id=nft_wallet_id,
            royalty_address=address,
            target_address=address,
            hash=bytes32.from_hexstr("0xD4584AD463139FA8C0D9F68F4B59F185D4584AD463139FA8C0D9F68F4B59F185"),
            uris=["http://test.nft"],
            push=True,
        ),
        tx_config=wallet_environments.tx_config,
    )

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {"set_remainder": True},
                    "did": {"set_remainder": True},
                    "nft1": {"set_remainder": True},
                    "nft0": {"init": True, "set_remainder": True},
                },
                post_block_balance_updates={
                    "xch": {"set_remainder": True},
                    "did": {"set_remainder": True},
                    "nft1": {"set_remainder": True},
                    "nft0": {"set_remainder": True},
                },
            ),
            WalletStateTransition(),
        ]
    )

    wallet_node: WalletNode = env.node
    wallet_node_2: WalletNode = env_2.node
    # Test Clawback resync
    tx = (
        await wc.send_transaction(
            SendTransaction(
                wallet_id=uint32(1),
                amount=uint64(500),
                address=address,
                puzzle_decorator=[ClawbackPuzzleDecoratorOverride(decorator="CLAWBACK", clawback_timelock=uint64(5))],
                push=True,
            ),
            tx_config=wallet_environments.tx_config,
        )
    ).transaction
    clawback_coin_id = tx.additions[0].name()

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {"set_remainder": True},
                    "did": {"set_remainder": True},
                    "nft1": {"set_remainder": True},
                    "nft0": {"set_remainder": True},
                },
                post_block_balance_updates={
                    "xch": {"set_remainder": True},
                    "did": {"set_remainder": True},
                    "nft1": {"set_remainder": True},
                    "nft0": {"set_remainder": True},
                },
            ),
            WalletStateTransition(),
        ]
    )

    resp = await wc.spend_clawback_coins(
        SpendClawbackCoins(coin_ids=[clawback_coin_id], fee=uint64(0), push=True),
        tx_config=wallet_environments.tx_config,
    )
    assert len(resp.transaction_ids) == 1

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {"set_remainder": True},
                    "did": {"set_remainder": True},
                    "nft1": {"set_remainder": True},
                    "nft0": {"set_remainder": True},
                },
                post_block_balance_updates={
                    "xch": {"set_remainder": True},
                    "did": {"set_remainder": True},
                    "nft1": {"set_remainder": True},
                    "nft0": {"set_remainder": True},
                },
            ),
            WalletStateTransition(),
        ]
    )

    wallet_node_2._close()
    await wallet_node_2._await_closed()
    # set flag to reset wallet sync data on start
    await client.set_wallet_resync_on_startup(SetWalletResyncOnStartup())
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


@pytest.mark.parametrize(
    "wallet_environments",
    [{"num_environments": 2, "blocks_needed": [1, 0]}],
    indirect=True,
)
@pytest.mark.limit_consensus_modes(reason="irrelevant")
@pytest.mark.anyio
async def test_set_wallet_resync_on_startup_disable(wallet_environments: WalletTestFramework) -> None:
    env = wallet_environments.environments[0]
    env_2 = wallet_environments.environments[1]
    client: WalletRpcClient = env.rpc_client
    wallet_node: WalletNode = env.node
    wallet_node_2: WalletNode = env_2.node
    wallet_node_2._close()
    await wallet_node_2._await_closed()
    # set flag to reset wallet sync data on start
    await client.set_wallet_resync_on_startup(SetWalletResyncOnStartup())
    fingerprint = wallet_node.logged_in_fingerprint
    assert wallet_node._wallet_state_manager
    assert len(await wallet_node._wallet_state_manager.coin_store.get_all_unspent_coins()) == 2
    before_txs = await wallet_node.wallet_state_manager.tx_store.get_all_transactions()
    await client.set_wallet_resync_on_startup(SetWalletResyncOnStartup(False))
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


@pytest.mark.parametrize(
    "wallet_environments",
    [{"num_environments": 1, "blocks_needed": [0]}],
    indirect=True,
)
@pytest.mark.limit_consensus_modes(reason="irrelevant")
@pytest.mark.anyio
async def test_set_wallet_resync_schema(wallet_environments: WalletTestFramework) -> None:
    env = wallet_environments.environments[0]
    wallet_node: WalletNode = env.node
    fingerprint = wallet_node.logged_in_fingerprint
    assert fingerprint is not None
    db_path = wallet_node.wallet_state_manager.db_path
    assert await wallet_node.reset_sync_db(db_path, fingerprint), (
        "Schema has been changed, reset sync db won't work, please update WalletNode.reset_sync_db function"
    )
    dbw: DBWrapper2 = wallet_node.wallet_state_manager.db_wrapper
    conn: aiosqlite.Connection
    async with dbw.writer() as conn:
        await conn.execute("CREATE TABLE blah(temp int)")
    await wallet_node.reset_sync_db(db_path, fingerprint)
    assert (
        len(list(await conn.execute_fetchall("SELECT name FROM sqlite_master WHERE type='table' AND name='blah'"))) == 0
    )


@pytest.mark.parametrize(
    "wallet_environments",
    [{"num_environments": 1, "blocks_needed": [1]}],
    indirect=True,
)
@pytest.mark.limit_consensus_modes(reason="irrelevant")
@pytest.mark.anyio
async def test_cat_spend_run_tail(wallet_environments: WalletTestFramework) -> None:
    env = wallet_environments.environments[0]

    wallet_node: WalletNode = env.node
    client: WalletRpcClient = env.rpc_client
    full_node_api: FullNodeSimulator = wallet_environments.full_node
    full_node_rpc: FullNodeRpcClient = wallet_environments.full_node_rpc_client

    env.wallet_aliases = {
        "xch": 1,
        "cat": 2,
    }

    # Send to a CAT with an anyone can spend TAIL
    async with env.wallet_state_manager.new_action_scope(wallet_environments.tx_config, push=True) as action_scope:
        our_ph = await action_scope.get_puzzle_hash(env.wallet_state_manager)
    cat_puzzle: Program = construct_cat_puzzle(CAT_MOD, Program.NIL.get_tree_hash(), Program.to(1))
    addr = encode_puzzle_hash(
        cat_puzzle.get_tree_hash(),
        "txch",
    )
    tx_amount = uint64(100)

    tx = (
        await client.send_transaction(
            SendTransaction(wallet_id=uint32(1), amount=tx_amount, address=addr, push=True),
            wallet_environments.tx_config,
        )
    ).transaction
    spend_bundle = tx.spend_bundle
    assert spend_bundle is not None

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {"set_remainder": True},
                },
                post_block_balance_updates={
                    "xch": {"set_remainder": True},
                },
            )
        ]
    )

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
    res = await client.create_wallet_for_existing_cat(Program.NIL.get_tree_hash())
    assert res["success"]
    cat_wallet_id = res["wallet_id"]

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "cat": {"init": True, "set_remainder": True},
                },
                post_block_balance_updates={},
            )
        ]
    )

    # Attempt to melt it fully
    tx = (
        await client.cat_spend(
            CATSpend(
                wallet_id=cat_wallet_id,
                amount=uint64(0),
                inner_address=encode_puzzle_hash(our_ph, "txch"),
                extra_delta=str(tx_amount * -1),
                tail_reveal=b"\x80",
                tail_solution=b"\x80",
                push=True,
            ),
            tx_config=wallet_environments.tx_config,
        )
    ).transaction

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {},
                    "cat": {
                        "unconfirmed_wallet_balance": -tx_amount,
                        "spendable_balance": -tx_amount,
                        "max_send_amount": -tx_amount,
                        "pending_coin_removal_count": 1,
                    },
                },
                post_block_balance_updates={
                    "xch": {},
                    "cat": {
                        "confirmed_wallet_balance": -tx_amount,
                        "pending_coin_removal_count": -1,
                    },
                },
            )
        ]
    )


@pytest.mark.parametrize(
    "wallet_environments",
    [{"num_environments": 1, "blocks_needed": [1]}],
    indirect=True,
)
@pytest.mark.limit_consensus_modes(reason="irrelevant")
@pytest.mark.anyio
async def test_get_balances(wallet_environments: WalletTestFramework) -> None:
    env = wallet_environments.environments[0]
    client: WalletRpcClient = env.rpc_client

    env.wallet_aliases = {
        "xch": 1,
        "cat": 2,
        "cat2": 3,
    }

    # Creates a CAT wallet with 100 mojos and a CAT with 20 mojos
    await client.create_new_cat_and_wallet(uint64(100), test=True)
    await client.create_new_cat_and_wallet(uint64(20), test=True)

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {"set_remainder": True},
                    "cat": {"init": True, "set_remainder": True},
                    "cat2": {"init": True, "set_remainder": True},
                },
                post_block_balance_updates={
                    "xch": {"set_remainder": True},
                    "cat": {"set_remainder": True},
                    "cat2": {"set_remainder": True},
                },
            ),
            WalletStateTransition(),
        ]
    )

    bals_response = await client.get_wallet_balances(GetWalletBalances())
    assert len(bals_response.wallet_balances) == 3
    assert bals_response.wallet_balances[uint32(1)].confirmed_wallet_balance == 1999999999880
    assert bals_response.wallet_balances[uint32(2)].confirmed_wallet_balance == 100
    assert bals_response.wallet_balances[uint32(3)].confirmed_wallet_balance == 20
    bals_response = await client.get_wallet_balances(GetWalletBalances([uint32(3), uint32(2)]))
    assert len(bals_response.wallet_balances) == 2
    assert bals_response.wallet_balances[uint32(2)].confirmed_wallet_balance == 100
    assert bals_response.wallet_balances[uint32(3)].confirmed_wallet_balance == 20


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
@pytest.mark.limit_consensus_modes(reason="irrelevant")
@pytest.mark.anyio
async def test_split_coins(wallet_environments: WalletTestFramework, capsys: pytest.CaptureFixture[str]) -> None:
    env = wallet_environments.environments[0]
    env.wallet_aliases = {
        "xch": 1,
        "cat": 2,
    }

    # Test XCH first
    async with env.wallet_state_manager.new_action_scope(wallet_environments.tx_config) as action_scope:
        target_coin = next(iter(await env.xch_wallet.select_coins(uint64(250_000_000_000), action_scope)))
        assert target_coin.amount == 250_000_000_000

    xch_request = SplitCMD(
        **{
            **wallet_environments.cmd_tx_endpoint_args(env),
            **dict(
                id=env.wallet_aliases["xch"],
                number_of_coins=100,
                amount_per_coin=CliAmount(amount=uint64(100), mojos=True),
                target_coin_id=target_coin.name(),
                fee=uint64(1_000_000_000_000),  # 1 XCH
                push=True,
            ),
        }
    )

    with pytest.raises(ResponseFailureError, match="501 coins is greater then the maximum limit of 500 coins"):
        await dataclasses.replace(xch_request, number_of_coins=501).run()

    with pytest.raises(ResponseFailureError, match="Could not find coin with ID 00000000000000000"):
        await dataclasses.replace(xch_request, target_coin_id=bytes32.zeros).run()

    with pytest.raises(ResponseFailureError, match="is less than the total amount of the split"):
        await dataclasses.replace(
            xch_request, amount_per_coin=CliAmount(amount=uint64(1_000_000_000_000), mojos=True)
        ).run()

    # We catch this one
    capsys.readouterr()
    await dataclasses.replace(xch_request, id=50).run()
    output = (capsys.readouterr()).out
    assert "Wallet id: 50 not found" in output

    # This one only "works" on the RPC
    env.wallet_state_manager.wallets[uint32(42)] = object()  # type: ignore[assignment]
    with pytest.raises(ResponseFailureError, match="Cannot split coins from non-fungible wallet types"):
        assert xch_request.amount_per_coin is not None  # hey there mypy
        rpc_request = SplitCoins(
            wallet_id=uint32(42),
            number_of_coins=uint16(xch_request.number_of_coins),
            amount_per_coin=xch_request.amount_per_coin.convert_amount(1),
            target_coin_id=xch_request.target_coin_id,
            fee=xch_request.fee,
            push=xch_request.push,
        )
        await env.rpc_client.split_coins(rpc_request, wallet_environments.tx_config)

    del env.wallet_state_manager.wallets[uint32(42)]

    await dataclasses.replace(xch_request, number_of_coins=0).run()
    output = (capsys.readouterr()).out
    assert "Transaction sent" not in output

    with wallet_environments.new_puzzle_hashes_allowed():
        await xch_request.run()

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
        target_coin = next(iter(await cat_wallet.select_coins(uint64(50), action_scope)))
        assert target_coin.amount == 50

    cat_request = SplitCMD(
        **{
            **wallet_environments.cmd_tx_endpoint_args(env),
            **dict(
                id=env.wallet_aliases["cat"],
                number_of_coins=50,
                amount_per_coin=CliAmount(amount=uint64(1), mojos=True),
                target_coin_id=target_coin.name(),
                push=True,
            ),
        }
    )

    with wallet_environments.new_puzzle_hashes_allowed():
        await dataclasses.replace(cat_request).run()

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

    # Test a not synced error
    assert xch_request.rpc_info.client_info is not None

    async def not_synced() -> GetSyncStatusResponse:
        return GetSyncStatusResponse(False, False)

    xch_request.rpc_info.client_info.client.get_sync_status = not_synced  # type: ignore[method-assign]
    await xch_request.run()
    output = (capsys.readouterr()).out
    assert "Wallet not synced. Please wait." in output


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
@pytest.mark.limit_consensus_modes(reason="irrelevant")
@pytest.mark.anyio
async def test_combine_coins(wallet_environments: WalletTestFramework, capsys: pytest.CaptureFixture[str]) -> None:
    env = wallet_environments.environments[0]
    env.wallet_aliases = {
        "xch": 1,
        "cat": 2,
    }

    # Should have 4 coins, two 1.75 XCH, two 0.25 XCH

    # Grab one of the 0.25 ones to specify
    async with env.wallet_state_manager.new_action_scope(wallet_environments.tx_config) as action_scope:
        target_coin = next(iter(await env.xch_wallet.select_coins(uint64(250_000_000_000), action_scope)))
        assert target_coin.amount == 250_000_000_000

    # These parameters will give us the maximum amount of behavior coverage
    # - More amount than the coin we specify
    # - Less amount than will have to be selected in order create it
    # - Higher # coins than necessary to create it
    fee = uint64(100)
    xch_combine_request = CombineCMD(
        **{
            **wallet_environments.cmd_tx_endpoint_args(env),
            **dict(
                id=env.wallet_aliases["xch"],
                target_amount=CliAmount(amount=uint64(1_000_000_000_000), mojos=True),
                number_of_coins=uint16(3),
                input_coins=(target_coin.name(),),
                fee=fee,
                push=True,
            ),
        }
    )

    # Test some error cases first
    with pytest.raises(ResponseFailureError, match="greater then the maximum limit"):
        await dataclasses.replace(xch_combine_request, number_of_coins=uint16(501)).run()

    with pytest.raises(ResponseFailureError, match="You need at least two coins to combine"):
        await dataclasses.replace(xch_combine_request, number_of_coins=uint16(0)).run()

    with pytest.raises(ResponseFailureError, match="More coin IDs specified than desired number of coins to combine"):
        await dataclasses.replace(xch_combine_request, input_coins=(bytes32.zeros,) * 100).run()

    # We catch this one
    capsys.readouterr()
    await dataclasses.replace(xch_combine_request, id=50).run()
    output = (capsys.readouterr()).out
    assert "Wallet id: 50 not found" in output

    # This one only "works" on the RPC
    env.wallet_state_manager.wallets[uint32(42)] = object()  # type: ignore[assignment]
    with pytest.raises(ResponseFailureError, match="Cannot combine coins from non-fungible wallet types"):
        assert xch_combine_request.target_amount is not None  # hey there mypy
        rpc_request = CombineCoins(
            wallet_id=uint32(42),
            target_coin_amount=xch_combine_request.target_amount.convert_amount(1),
            number_of_coins=uint16(xch_combine_request.number_of_coins),
            target_coin_ids=list(xch_combine_request.input_coins),
            fee=xch_combine_request.fee,
            push=xch_combine_request.push,
        )
        await env.rpc_client.combine_coins(rpc_request, wallet_environments.tx_config)

    del env.wallet_state_manager.wallets[uint32(42)]

    # Now push the request
    with patch("sys.stdin", new=io.StringIO("y\n")):
        await xch_combine_request.run()

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
            [await action_scope.get_puzzle_hash(env.wallet_state_manager)] * 3,
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
    cat_combine_request = CombineCMD(
        **{
            **wallet_environments.cmd_tx_endpoint_args(env),
            **dict(
                id=env.wallet_aliases["cat"],
                target_amount=None,
                number_of_coins=uint16(2),
                input_coins=(),
                largest_first=False,
                fee=fee,
                push=True,
            ),
        }
    )

    with patch("sys.stdin", new=io.StringIO("y\n")):
        await cat_combine_request.run()

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

    # Test a not synced error
    assert xch_combine_request.rpc_info.client_info is not None

    async def not_synced() -> GetSyncStatusResponse:
        return GetSyncStatusResponse(False, False)

    xch_combine_request.rpc_info.client_info.client.get_sync_status = not_synced  # type: ignore[method-assign]
    await xch_combine_request.run()
    output = (capsys.readouterr()).out
    assert "Wallet not synced. Please wait." in output


@pytest.mark.parametrize(
    "wallet_environments",
    [
        {
            "num_environments": 1,
            "blocks_needed": [2],
            "trusted": True,  # irrelevant
            "reuse_puzhash": True,  # irrelevant
        }
    ],
    indirect=True,
)
@pytest.mark.limit_consensus_modes(reason="irrelevant")
@pytest.mark.anyio
async def test_fee_bigger_than_selection_coin_combining(wallet_environments: WalletTestFramework) -> None:
    """
    This tests the case where the coins we would otherwise select are not enough to pay the fee.
    """

    env = wallet_environments.environments[0]
    env.wallet_aliases = {
        "xch": 1,
        "cat": 2,
    }

    # Should have 4 coins, two 1.75 XCH, two 0.25 XCH

    # Grab one of the 0.25 ones to specify
    async with env.wallet_state_manager.new_action_scope(wallet_environments.tx_config) as action_scope:
        target_coin = next(iter(await env.xch_wallet.select_coins(uint64(250_000_000_000), action_scope)))
        assert target_coin.amount == 250_000_000_000

    fee = uint64(1_750_000_000_000)
    # Under standard circumstances we would select the small coins, but this is not enough to pay the fee
    # Instead, we will grab the big coin first and combine it with one of the smaller coins
    xch_combine_request = CombineCMD(
        **{
            **wallet_environments.cmd_tx_endpoint_args(env),
            **dict(
                id=env.wallet_aliases["xch"],
                number_of_coins=uint16(2),
                input_coins=(),
                fee=fee,
                push=True,
                largest_first=False,
            ),
        }
    )

    # First test an error where fee selection causes too many coins to be selected
    with pytest.raises(ResponseFailureError, match="without selecting more coins than specified: 3"):
        await dataclasses.replace(xch_combine_request, fee=uint64(2_250_000_000_000)).run()

    with patch("sys.stdin", new=io.StringIO("y\n")):
        await xch_combine_request.run()

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {
                        "unconfirmed_wallet_balance": -fee,
                        "spendable_balance": -2_000_000_000_000,
                        "pending_change": 250_000_000_000,
                        "max_send_amount": -2_000_000_000_000,
                        "pending_coin_removal_count": 2,
                    }
                },
                post_block_balance_updates={
                    "xch": {
                        "confirmed_wallet_balance": -fee,
                        "spendable_balance": 250_000_000_000,
                        "pending_change": -250_000_000_000,
                        "max_send_amount": 250_000_000_000,
                        "pending_coin_removal_count": -2,
                        "unspent_coin_count": -1,  # combine 2 into 1
                    }
                },
            )
        ]
    )
