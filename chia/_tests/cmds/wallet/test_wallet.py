from __future__ import annotations

import datetime
import os
from pathlib import Path
from typing import Any, Optional, Union

import importlib_resources
import pytest
from chia_rs import Coin, G2Element
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint8, uint16, uint32, uint64
from click.testing import CliRunner

from chia._tests.cmds.cmd_test_utils import TestRpcClients, TestWalletRpcClient, logType, run_cli_command_and_assert
from chia._tests.cmds.wallet.test_consts import (
    CAT_FINGERPRINT_ARG,
    FINGERPRINT,
    FINGERPRINT_ARG,
    STD_TX,
    STD_UTX,
    WALLET_ID,
    WALLET_ID_ARG,
    bytes32_hexstr,
    get_bytes32,
)
from chia.cmds.cmds_util import TransactionBundle
from chia.protocols.outbound_message import NodeType
from chia.types.blockchain_format.program import Program
from chia.types.signing_mode import SigningMode
from chia.util.bech32m import encode_puzzle_hash
from chia.wallet.conditions import ConditionValidTimes
from chia.wallet.trade_record import TradeRecord
from chia.wallet.trading.offer import Offer
from chia.wallet.trading.trade_status import TradeStatus
from chia.wallet.transaction_record import TransactionRecord
from chia.wallet.transaction_sorting import SortKey
from chia.wallet.util.query_filter import HashFilter, TransactionTypeFilter
from chia.wallet.util.transaction_type import TransactionType
from chia.wallet.util.tx_config import DEFAULT_TX_CONFIG, TXConfig
from chia.wallet.util.wallet_types import WalletType
from chia.wallet.wallet_coin_store import GetCoinRecords
from chia.wallet.wallet_request_types import (
    CancelOfferResponse,
    CATSpendResponse,
    CreateOfferForIDsResponse,
    FungibleAsset,
    GetHeightInfoResponse,
    NFTCalculateRoyalties,
    NFTGetWalletDID,
    NFTGetWalletDIDResponse,
    RoyaltyAsset,
    SendTransactionResponse,
    TakeOfferResponse,
)
from chia.wallet.wallet_spend_bundle import WalletSpendBundle

test_offer_file_path = importlib_resources.files(__name__.rpartition(".")[0]).joinpath("test_offer.toffer")
test_offer_file_bech32 = test_offer_file_path.read_text(encoding="utf-8")
test_offer_id: str = "0xdfb7e8643376820ec995b0bcdb3fc1f764c16b814df5e074631263fcf1e00839"
test_offer_id_bytes: bytes32 = bytes32.from_hexstr(test_offer_id)
test_condition_valid_times: ConditionValidTimes = ConditionValidTimes(min_time=uint64(100), max_time=uint64(150))


def test_get_transaction(capsys: object, get_test_cli_clients: tuple[TestRpcClients, Path]) -> None:
    test_rpc_clients, root_dir = get_test_cli_clients
    # set RPC Client
    inst_rpc_client = TestWalletRpcClient()
    test_rpc_clients.wallet_rpc_client = inst_rpc_client
    # get output with all options but verbose
    command_args = ["wallet", "get_transaction", WALLET_ID_ARG, "-tx", bytes32_hexstr]
    assert_list = [
        "Transaction 0202020202020202020202020202020202020202020202020202020202020202",
        "Status: In mempool",
        "Amount sent: 0.000012345678 XCH",
        "To address: xch1qyqszqgpqyqszqgpqyqszqgpqyqszqgpqyqszqgpqyqszqgpqyqs0wg4qq",
    ]
    v_assert_list = [
        "0x0303030303030303030303030303030303030303030303030303030303030303",
        "'amount': 12345678",
        "'to_puzzle_hash': '0x0101010101010101010101010101010101010101010101010101010101010101',",
    ]
    cat_assert_list = [
        "Transaction 0202020202020202020202020202020202020202020202020202020202020202",
        "Status: In mempool",
        "Amount sent: 12345.678 test1",
        "To address: xch1qyqszqgpqyqszqgpqyqszqgpqyqszqgpqyqszqgpqyqszqgpqyqs0wg4qq",
    ]
    run_cli_command_and_assert(capsys, root_dir, [*command_args, FINGERPRINT_ARG], assert_list)
    run_cli_command_and_assert(capsys, root_dir, [*command_args, FINGERPRINT_ARG, "-v"], v_assert_list)
    run_cli_command_and_assert(capsys, root_dir, [*command_args, CAT_FINGERPRINT_ARG], cat_assert_list)
    # these are various things that should be in the output
    expected_calls: logType = {
        "get_wallets": [(None,), (None,), (None,)],
        "get_cat_name": [(1,)],
        "get_transaction": [
            (bytes32.from_hexstr(bytes32_hexstr),),
            (bytes32.from_hexstr(bytes32_hexstr),),
            (bytes32.from_hexstr(bytes32_hexstr),),
        ],
    }
    test_rpc_clients.wallet_rpc_client.check_log(expected_calls)


def test_get_transactions(capsys: object, get_test_cli_clients: tuple[TestRpcClients, Path]) -> None:
    test_rpc_clients, root_dir = get_test_cli_clients

    # set RPC Client
    class GetTransactionsWalletRpcClient(TestWalletRpcClient):
        async def get_transactions(
            self,
            wallet_id: int,
            start: int,
            end: int,
            sort_key: Optional[SortKey] = None,
            reverse: bool = False,
            to_address: Optional[str] = None,
            type_filter: Optional[TransactionTypeFilter] = None,
            confirmed: Optional[bool] = None,
        ) -> list[TransactionRecord]:
            self.add_to_log(
                "get_transactions", (wallet_id, start, end, sort_key, reverse, to_address, type_filter, confirmed)
            )
            l_tx_rec = []
            for i in range(start, end):
                t_type = TransactionType.INCOMING_CLAWBACK_SEND if i == end - 1 else TransactionType.INCOMING_TX
                tx_rec = TransactionRecord(
                    confirmed_at_height=uint32(1 + i),
                    created_at_time=uint64(1234 + i),
                    to_puzzle_hash=bytes32([1 + i] * 32),
                    amount=uint64(12345678 + i),
                    fee_amount=uint64(1234567 + i),
                    confirmed=False,
                    sent=uint32(0),
                    spend_bundle=WalletSpendBundle([], G2Element()),
                    additions=[Coin(bytes32([1 + i] * 32), bytes32([2 + i] * 32), uint64(12345678))],
                    removals=[Coin(bytes32([2 + i] * 32), bytes32([4 + i] * 32), uint64(12345678))],
                    wallet_id=uint32(1),
                    sent_to=[("aaaaa", uint8(1), None)],
                    trade_id=None,
                    type=uint32(t_type.value),
                    name=bytes32([2 + i] * 32),
                    memos=[(bytes32([3 + i] * 32), [bytes([4 + i] * 32)])],
                    valid_times=ConditionValidTimes(),
                )
                l_tx_rec.append(tx_rec)

            return l_tx_rec

        async def get_coin_records(self, request: GetCoinRecords) -> dict[str, Any]:
            self.add_to_log("get_coin_records", (request,))
            return {
                "coin_records": [{"metadata": {"time_lock": 12345678}}],
                "total_count": 1,
            }

    inst_rpc_client = GetTransactionsWalletRpcClient()
    test_rpc_clients.wallet_rpc_client = inst_rpc_client
    # get output with all options but verbose
    command_args = [
        "wallet",
        "get_transactions",
        FINGERPRINT_ARG,
        WALLET_ID_ARG,
        "--no-paginate",
        "--reverse",
        "-o2",
        "-l2",
    ]
    assert_list = [
        "Transaction 0404040404040404040404040404040404040404040404040404040404040404",
        "Transaction 0505050505050505050505050505050505050505050505050505050505050505",
        "Amount received: 0.00001234568 XCH",
        "Amount received in clawback as sender: 0.000012345681 XCH",
        "To address: xch1qvpsxqcrqvpsxqcrqvpsxqcrqvpsxqcrqvpsxqcrqvpsxqcrqvps82kgr2",
        "To address: xch1qszqgpqyqszqgpqyqszqgpqyqszqgpqyqszqgpqyqszqgpqyqszqkxck8d",
    ]
    v_assert_list = [
        "'amount': 12345680",
        "'fee_amount': 1234569",
        "'amount': 12345681",
        "'fee_amount': 1234570",
        "'name': '0x0404040404040404040404040404040404040404040404040404040404040404'",
        "'name': '0x0505050505050505050505050505050505050505050505050505050505050505'",
        "'to_puzzle_hash': '0x0303030303030303030303030303030303030303030303030303030303030303'",
        "'to_puzzle_hash': '0x0404040404040404040404040404040404040404040404040404040404040404'",
        "'type': 0",  # normal tx
        "'type': 7",  # clawback tx
    ]
    run_cli_command_and_assert(capsys, root_dir, command_args, assert_list)
    run_cli_command_and_assert(capsys, root_dir, [*command_args, "-v"], v_assert_list)
    # these are various things that should be in the output
    expected_coin_id = Coin(get_bytes32(4), get_bytes32(5), uint64(12345678)).name()
    expected_calls: logType = {
        "get_wallets": [(None,), (None,)],
        "get_transactions": [
            (1, 2, 4, SortKey.RELEVANCE, True, None, None, None),
            (1, 2, 4, SortKey.RELEVANCE, True, None, None, None),
        ],
        "get_coin_records": [
            (GetCoinRecords(coin_id_filter=HashFilter.include([expected_coin_id])),),
            (GetCoinRecords(coin_id_filter=HashFilter.include([expected_coin_id])),),
        ],
    }
    test_rpc_clients.wallet_rpc_client.check_log(expected_calls)


def test_show(capsys: object, get_test_cli_clients: tuple[TestRpcClients, Path]) -> None:
    test_rpc_clients, root_dir = get_test_cli_clients

    # set RPC Client
    class ShowRpcClient(TestWalletRpcClient):
        async def get_wallets(self, wallet_type: Optional[WalletType] = None) -> list[dict[str, Union[str, int]]]:
            self.add_to_log("get_wallets", (wallet_type,))
            wallet_list: list[dict[str, Union[str, int]]] = [
                {"data": "", "id": 1, "name": "Chia Wallet", "type": WalletType.STANDARD_WALLET},
                {
                    "data": "dc59bcd60ce5fc9c93a5d3b11875486b03efb53a53da61e453f5cf61a774686001ff02ffff01ff02ffff03ff2f"
                    "ffff01ff0880ffff01ff02ffff03ffff09ff2dff0280ff80ffff01ff088080ff018080ff0180ffff04ffff01a09848f0ef"
                    "6587565c48ee225cc837abbe406b91946c938e1739da49fc26c04286ff018080",
                    "id": 2,
                    "name": "test2",
                    "type": WalletType.CAT,
                },
                {
                    "data": '{"did_id": "0xcee228b8638c67cb66a55085be99fa3b457ae5b56915896f581990f600b2c652"}',
                    "id": 3,
                    "name": "NFT Wallet",
                    "type": WalletType.NFT,
                },
            ]
            if wallet_type is WalletType.CAT:
                return [wallet_list[1]]
            return wallet_list

        async def get_height_info(self) -> GetHeightInfoResponse:
            self.add_to_log("get_height_info", ())
            return GetHeightInfoResponse(uint32(10))

        async def get_wallet_balance(self, wallet_id: int) -> dict[str, uint64]:
            self.add_to_log("get_wallet_balance", (wallet_id,))
            if wallet_id == 1:
                amount = uint64(1000000000)
            elif wallet_id == 2:
                amount = uint64(2000000000)
            else:
                amount = uint64(1)
            return {
                "confirmed_wallet_balance": amount,
                "spendable_balance": amount,
                "unconfirmed_wallet_balance": uint64(0),
            }

        async def get_nft_wallet_did(self, request: NFTGetWalletDID) -> NFTGetWalletDIDResponse:
            self.add_to_log("get_nft_wallet_did", (request.wallet_id,))
            return NFTGetWalletDIDResponse("did:chia:1qgpqyqszqgpqyqszqgpqyqszqgpqyqszqgpqyqszqgpqyqszqgpq4msw0c")

        async def get_connections(
            self, node_type: Optional[NodeType] = None
        ) -> list[dict[str, Union[str, int, float, bytes32]]]:
            self.add_to_log("get_connections", (node_type,))
            return [
                {
                    "bytes_read": 10000,
                    "bytes_written": 100,
                    "creation_time": 169140000.0,
                    "last_message_time": 169141001.0,
                    "local_port": 19411,
                    "node_id": get_bytes32(1),
                    "peer_host": "127.0.0.1",
                    "peer_port": 47482,
                    "peer_server_port": 47482,
                    "type": 1,
                }
            ]

    inst_rpc_client = ShowRpcClient()
    test_rpc_clients.wallet_rpc_client = inst_rpc_client
    command_args = ["wallet", "show", FINGERPRINT_ARG]
    assert_list = [
        "Chia Wallet:\n   -Total Balance:         0.001 xch (1000000000 mojo)",
        "test2:\n   -Total Balance:         2000000.0  (2000000000 mojo)",
        "   -Asset ID:              dc59bcd60ce5fc9c93a5d3b11875486b03efb53a53da61e453f5cf61a7746860",
        "NFT Wallet:\n   -Total Balance:         1.0",
        "   -DID ID:                did:chia:1qgpqyqszqgpqyqszqgpqyqszqgpqyqszqgpqyqszqgpqyqszqgpq4msw0c",
        "FULL_NODE 127.0.0.1",
        "47482/47482 01010101... May 12",
    ]
    other_assert_list = [
        "test2:\n   -Total Balance:         2000000.0  (2000000000 mojo)",
        "   -Asset ID:              dc59bcd60ce5fc9c93a5d3b11875486b03efb53a53da61e453f5cf61a7746860",
        "FULL_NODE 127.0.0.1",
        "47482/47482 01010101... May 12",
    ]
    run_cli_command_and_assert(capsys, root_dir, command_args, assert_list)
    run_cli_command_and_assert(capsys, root_dir, [*command_args, "--wallet_type", "cat"], other_assert_list)
    # these are various things that should be in the output
    expected_calls: logType = {
        "get_wallets": [(None,), (WalletType.CAT,)],
        "get_sync_status": [(), ()],
        "get_height_info": [(), ()],
        "get_wallet_balance": [(1,), (2,), (3,), (2,)],
        "get_nft_wallet_did": [(3,)],
        "get_connections": [(None,), (None,)],
    }
    test_rpc_clients.wallet_rpc_client.check_log(expected_calls)


def test_send(capsys: object, get_test_cli_clients: tuple[TestRpcClients, Path]) -> None:
    test_rpc_clients, root_dir = get_test_cli_clients

    # set RPC Client
    class SendWalletRpcClient(TestWalletRpcClient):
        async def send_transaction(
            self,
            wallet_id: int,
            amount: uint64,
            address: str,
            tx_config: TXConfig,
            fee: uint64 = uint64(0),
            memos: Optional[list[str]] = None,
            puzzle_decorator_override: Optional[list[dict[str, Union[str, int, bool]]]] = None,
            push: bool = True,
            timelock_info: ConditionValidTimes = ConditionValidTimes(),
        ) -> SendTransactionResponse:
            self.add_to_log(
                "send_transaction",
                (wallet_id, amount, address, tx_config, fee, memos, puzzle_decorator_override, push, timelock_info),
            )
            name = get_bytes32(2)
            tx_rec = TransactionRecord(
                confirmed_at_height=uint32(1),
                created_at_time=uint64(1234),
                to_puzzle_hash=get_bytes32(1),
                amount=uint64(12345678),
                fee_amount=uint64(1234567),
                confirmed=False,
                sent=uint32(0),
                spend_bundle=WalletSpendBundle([], G2Element()),
                additions=[Coin(get_bytes32(1), get_bytes32(2), uint64(12345678))],
                removals=[Coin(get_bytes32(2), get_bytes32(4), uint64(12345678))],
                wallet_id=uint32(1),
                sent_to=[("aaaaa", uint8(1), None)],
                trade_id=None,
                type=uint32(TransactionType.OUTGOING_CLAWBACK.value),
                name=name,
                memos=[(get_bytes32(3), [bytes([4] * 32)])],
                valid_times=ConditionValidTimes(),
            )
            return SendTransactionResponse([STD_UTX], [STD_TX], tx_rec, name)

        async def cat_spend(
            self,
            wallet_id: int,
            tx_config: TXConfig,
            amount: Optional[uint64] = None,
            inner_address: Optional[str] = None,
            fee: uint64 = uint64(0),
            memos: Optional[list[str]] = None,
            additions: Optional[list[dict[str, Any]]] = None,
            removals: Optional[list[Coin]] = None,
            cat_discrepancy: Optional[tuple[int, Program, Program]] = None,  # (extra_delta, tail_reveal, tail_solution)
            push: bool = True,
            timelock_info: ConditionValidTimes = ConditionValidTimes(),
        ) -> CATSpendResponse:
            self.add_to_log(
                "cat_spend",
                (
                    wallet_id,
                    tx_config,
                    amount,
                    inner_address,
                    fee,
                    memos,
                    additions,
                    removals,
                    cat_discrepancy,
                    push,
                    timelock_info,
                ),
            )
            return CATSpendResponse([STD_UTX], [STD_TX], STD_TX, STD_TX.name)

    inst_rpc_client = SendWalletRpcClient()
    test_rpc_clients.wallet_rpc_client = inst_rpc_client
    # get output with all options but verbose
    addr = encode_puzzle_hash(get_bytes32(3), "xch")
    command_args = [
        "wallet",
        "send",
        "-a1",
        "-m0.5",
        "-o",
        WALLET_ID_ARG,
        f"-e{bytes32_hexstr}",
        f"-t{addr}",
        "--reuse",
        "--clawback_time",
        "60",
        "--max-coin-amount",
        "1",
        "-l10",
        "--exclude-coin",
        bytes32_hexstr,
        "--valid-at",
        "100",
        "--expires-at",
        "150",
    ]
    assert_list = ["Transaction submitted to nodes: [{'peer_id': 'aaaaa'", f"-f 123456 -tx 0x{get_bytes32(2).hex()}"]
    cat_assert_list = [
        "Transaction submitted to nodes: [{'peer_id': 'aaaaa'",
        f"-f 789101 -tx 0x{get_bytes32(2).hex()}",
    ]
    with CliRunner().isolated_filesystem():
        run_cli_command_and_assert(
            capsys, root_dir, [*command_args, FINGERPRINT_ARG, "--transaction-file-out=temp"], assert_list
        )
        run_cli_command_and_assert(
            capsys, root_dir, [*command_args, CAT_FINGERPRINT_ARG, "--transaction-file-out=temp2"], cat_assert_list
        )

        with open("temp", "rb") as file:
            assert TransactionBundle.from_bytes(file.read()) == TransactionBundle([STD_TX])
        with open("temp2", "rb") as file:
            assert TransactionBundle.from_bytes(file.read()) == TransactionBundle([STD_TX])

    # these are various things that should be in the output
    expected_calls: logType = {
        "get_wallets": [(None,), (None,)],
        "send_transaction": [
            (
                1,
                1000000000000,
                "xch1qvpsxqcrqvpsxqcrqvpsxqcrqvpsxqcrqvpsxqcrqvpsxqcrqvps82kgr2",
                TXConfig(
                    min_coin_amount=uint64(0),
                    max_coin_amount=uint64(10000000000000),
                    excluded_coin_amounts=[],
                    excluded_coin_ids=[bytes32([98] * 32)],
                    reuse_puzhash=True,
                ),
                500000000000,
                ["0x6262626262626262626262626262626262626262626262626262626262626262"],
                [{"decorator": "CLAWBACK", "clawback_timelock": 60}],
                True,
                test_condition_valid_times,
            )
        ],
        "cat_spend": [
            (
                1,
                TXConfig(
                    min_coin_amount=uint64(0),
                    max_coin_amount=uint64(10000),
                    excluded_coin_amounts=[],
                    excluded_coin_ids=[bytes32([98] * 32)],
                    reuse_puzhash=True,
                ),
                1000,
                "xch1qvpsxqcrqvpsxqcrqvpsxqcrqvpsxqcrqvpsxqcrqvpsxqcrqvps82kgr2",
                500000000000,
                ["0x6262626262626262626262626262626262626262626262626262626262626262"],
                None,
                None,
                None,
                True,
                test_condition_valid_times,
            )
        ],
        "get_transaction": [(get_bytes32(2),), (get_bytes32(2),)],
    }
    test_rpc_clients.wallet_rpc_client.check_log(expected_calls)


def test_get_address(capsys: object, get_test_cli_clients: tuple[TestRpcClients, Path]) -> None:
    test_rpc_clients, root_dir = get_test_cli_clients

    # set RPC Client
    class GetAddressWalletRpcClient(TestWalletRpcClient):
        async def get_next_address(self, wallet_id: int, new_address: bool) -> str:
            self.add_to_log("get_next_address", (wallet_id, new_address))
            if new_address:
                return encode_puzzle_hash(get_bytes32(3), "xch")
            return encode_puzzle_hash(get_bytes32(4), "xch")

    inst_rpc_client = GetAddressWalletRpcClient()
    test_rpc_clients.wallet_rpc_client = inst_rpc_client
    # get output with all options but verbose
    addr1 = encode_puzzle_hash(get_bytes32(3), "xch")
    addr2 = encode_puzzle_hash(get_bytes32(4), "xch")
    command_args = [
        "wallet",
        "get_address",
        WALLET_ID_ARG,
        FINGERPRINT_ARG,
    ]
    run_cli_command_and_assert(capsys, root_dir, [*command_args, "-n"], [addr1])
    run_cli_command_and_assert(capsys, root_dir, [*command_args, "-l"], [addr2])
    # these are various things that should be in the output
    expected_calls: logType = {
        "get_next_address": [(1, True), (1, False)],
    }
    test_rpc_clients.wallet_rpc_client.check_log(expected_calls)


def test_clawback(capsys: object, get_test_cli_clients: tuple[TestRpcClients, Path]) -> None:
    test_rpc_clients, root_dir = get_test_cli_clients

    # set RPC Client
    class ClawbackWalletRpcClient(TestWalletRpcClient):
        async def spend_clawback_coins(
            self,
            coin_ids: list[bytes32],
            fee: int = 0,
            force: bool = False,
            push: bool = True,
            timelock_info: ConditionValidTimes = ConditionValidTimes(),
        ) -> dict[str, Any]:
            self.add_to_log("spend_clawback_coins", (coin_ids, fee, force, push, timelock_info))
            tx_hex_list = [get_bytes32(6).hex(), get_bytes32(7).hex(), get_bytes32(8).hex()]
            return {
                "transaction_ids": tx_hex_list,
                "transactions": [
                    STD_TX.to_json_dict_convenience(
                        {
                            "selected_network": "mainnet",
                            "network_overrides": {"config": {"mainnet": {"address_prefix": "xch"}}},
                        }
                    )
                ],
            }

    inst_rpc_client = ClawbackWalletRpcClient()
    test_rpc_clients.wallet_rpc_client = inst_rpc_client
    tx_ids = [get_bytes32(3), get_bytes32(4), get_bytes32(5)]
    r_tx_ids_hex = [get_bytes32(6).hex(), get_bytes32(7).hex(), get_bytes32(8).hex()]
    command_args = [
        "wallet",
        "clawback",
        WALLET_ID_ARG,
        FINGERPRINT_ARG,
        "-m0.5",
        "--tx_ids",
        f"{tx_ids[0].hex()},{tx_ids[1].hex()}, {tx_ids[2].hex()}",
        "--valid-at",
        "100",
        "--expires-at",
        "150",
    ]
    run_cli_command_and_assert(capsys, root_dir, command_args, ["transaction_ids", str(r_tx_ids_hex)])
    # these are various things that should be in the output
    expected_calls: logType = {
        "spend_clawback_coins": [(tx_ids, 500000000000, False, True, test_condition_valid_times)],
    }
    test_rpc_clients.wallet_rpc_client.check_log(expected_calls)


def test_del_unconfirmed_tx(capsys: object, get_test_cli_clients: tuple[TestRpcClients, Path]) -> None:
    test_rpc_clients, root_dir = get_test_cli_clients

    # set RPC Client
    class UnconfirmedTxRpcClient(TestWalletRpcClient):
        async def delete_unconfirmed_transactions(self, wallet_id: int) -> None:
            self.add_to_log("delete_unconfirmed_transactions", (wallet_id,))

    inst_rpc_client = UnconfirmedTxRpcClient()
    test_rpc_clients.wallet_rpc_client = inst_rpc_client
    command_args = [
        "wallet",
        "delete_unconfirmed_transactions",
        WALLET_ID_ARG,
        FINGERPRINT_ARG,
    ]
    assert_list = [f"Successfully deleted all unconfirmed transactions for wallet id {WALLET_ID} on key {FINGERPRINT}"]
    run_cli_command_and_assert(capsys, root_dir, command_args, assert_list)
    # these are various things that should be in the output
    expected_calls: logType = {
        "delete_unconfirmed_transactions": [(1,)],
    }
    test_rpc_clients.wallet_rpc_client.check_log(expected_calls)


def test_get_derivation_index(capsys: object, get_test_cli_clients: tuple[TestRpcClients, Path]) -> None:
    test_rpc_clients, root_dir = get_test_cli_clients

    # set RPC Client
    class GetDerivationIndexRpcClient(TestWalletRpcClient):
        async def get_current_derivation_index(self) -> str:
            self.add_to_log("get_current_derivation_index", ())
            return str(520)

    inst_rpc_client = GetDerivationIndexRpcClient()
    test_rpc_clients.wallet_rpc_client = inst_rpc_client
    command_args = [
        "wallet",
        "get_derivation_index",
        FINGERPRINT_ARG,
    ]
    run_cli_command_and_assert(capsys, root_dir, command_args, ["Last derivation index: 520"])
    # these are various things that should be in the output
    expected_calls: logType = {
        "get_current_derivation_index": [()],
    }
    test_rpc_clients.wallet_rpc_client.check_log(expected_calls)


def test_sign_message(capsys: object, get_test_cli_clients: tuple[TestRpcClients, Path]) -> None:
    test_rpc_clients, root_dir = get_test_cli_clients

    # set RPC Client
    inst_rpc_client = TestWalletRpcClient()
    test_rpc_clients.wallet_rpc_client = inst_rpc_client
    xch_addr = encode_puzzle_hash(get_bytes32(1), "xch")
    message = b"hello world"
    command_args = ["wallet", "sign_message", FINGERPRINT_ARG, f"-m{message.hex()}"]
    # these are various things that should be in the output
    assert_list = [
        f"Message: {message.hex()}",
        f"Public Key: {bytes([3] * 48).hex()}",
        f"Signature: {bytes([6] * 576).hex()}",
        f"Signing Mode: {SigningMode.CHIP_0002.value}",
    ]
    run_cli_command_and_assert(capsys, root_dir, [*command_args, f"-a{xch_addr}"], assert_list)
    expected_calls: logType = {
        "sign_message_by_address": [(xch_addr, message.hex())],  # xch std
    }
    test_rpc_clients.wallet_rpc_client.check_log(expected_calls)


def test_update_derivation_index(capsys: object, get_test_cli_clients: tuple[TestRpcClients, Path]) -> None:
    test_rpc_clients, root_dir = get_test_cli_clients

    # set RPC Client
    class UpdateDerivationIndexRpcClient(TestWalletRpcClient):
        async def extend_derivation_index(self, index: int) -> str:
            self.add_to_log("extend_derivation_index", (index,))
            return str(index)

    inst_rpc_client = UpdateDerivationIndexRpcClient()
    test_rpc_clients.wallet_rpc_client = inst_rpc_client
    index = 600
    command_args = ["wallet", "update_derivation_index", FINGERPRINT_ARG, "--index", str(index)]
    run_cli_command_and_assert(capsys, root_dir, command_args, [f"Updated derivation index: {index}"])
    expected_calls: logType = {
        "extend_derivation_index": [(index,)],
    }
    test_rpc_clients.wallet_rpc_client.check_log(expected_calls)


def test_add_token(capsys: object, get_test_cli_clients: tuple[TestRpcClients, Path]) -> None:
    test_rpc_clients, root_dir = get_test_cli_clients

    # set RPC Client
    class AddTokenRpcClient(TestWalletRpcClient):
        async def create_wallet_for_existing_cat(self, asset_id: bytes) -> dict[str, int]:
            self.add_to_log("create_wallet_for_existing_cat", (asset_id,))
            return {"wallet_id": 3}

        async def set_cat_name(self, wallet_id: int, name: str) -> None:
            self.add_to_log("set_cat_name", (wallet_id, name))

    inst_rpc_client = AddTokenRpcClient()
    test_rpc_clients.wallet_rpc_client = inst_rpc_client
    command_args = ["wallet", "add_token", FINGERPRINT_ARG, "-nexamplecat"]
    assert_list = [f"Successfully renamed test1 with wallet_id 2 on key {FINGERPRINT} to examplecat"]
    other_assert_list = [f"Successfully added examplecat with wallet id 3 on key {FINGERPRINT}"]
    run_cli_command_and_assert(capsys, root_dir, [*command_args, "--asset-id", get_bytes32(1).hex()], assert_list)
    run_cli_command_and_assert(
        capsys, root_dir, [*command_args, "--asset-id", bytes32([1, 2] * 16).hex()], other_assert_list
    )
    # these are various things that should be in the output

    expected_calls: logType = {
        "cat_asset_id_to_name": [(get_bytes32(1),), (bytes32([1, 2] * 16),)],
        "create_wallet_for_existing_cat": [(bytes32([1, 2] * 16),)],
        "set_cat_name": [(2, "examplecat"), (3, "examplecat")],
    }
    test_rpc_clients.wallet_rpc_client.check_log(expected_calls)


def test_make_offer_bad_filename(
    capsys: object, get_test_cli_clients: tuple[TestRpcClients, Path], tmp_path: Path
) -> None:
    _, root_dir = get_test_cli_clients

    request_cat_id = get_bytes32(2)
    request_nft_id = get_bytes32(2)
    request_nft_addr = encode_puzzle_hash(request_nft_id, "nft")
    # we offer xch and a random cat via wallet id and request a random cat, nft via coin and tail
    command_args_dir = [
        "wallet",
        "make_offer",
        FINGERPRINT_ARG,
        f"-p{tmp_path!s}",
        "--reuse",
        "-m0.5",
        "--offer",
        "1:10",
        "--offer",
        "3:100",
        "--request",
        f"{request_cat_id.hex()}:10",
        "--request",
        f"{request_nft_addr}:1",
    ]

    test_file: Path = tmp_path / "test.offer"
    test_file.touch(mode=0o400)

    command_args_unwritable = [
        "wallet",
        "make_offer",
        FINGERPRINT_ARG,
        f"-p{test_file!s}",
        "--reuse",
        "-m0.5",
        "--offer",
        "1:10",
        "--offer",
        "3:100",
        "--request",
        f"{request_cat_id.hex()}:10",
        "--request",
        f"{request_nft_addr}:1",
    ]

    with pytest.raises(AssertionError, match=r".*Invalid value for '-p' / '--filepath.*is a directory.*"):
        run_cli_command_and_assert(capsys, root_dir, command_args_dir, [""])

    with pytest.raises(AssertionError, match=r".*Invalid value for '-p' / '--filepath.*is not writable.*"):
        run_cli_command_and_assert(capsys, root_dir, command_args_unwritable, [""])


def test_make_offer(capsys: object, get_test_cli_clients: tuple[TestRpcClients, Path], tmp_path: Path) -> None:
    test_rpc_clients, root_dir = get_test_cli_clients

    # set RPC Client
    class MakeOfferRpcClient(TestWalletRpcClient):
        async def create_offer_for_ids(
            self,
            offer_dict: dict[uint32, int],
            tx_config: TXConfig,
            driver_dict: Optional[dict[str, Any]] = None,
            solver: Optional[dict[str, Any]] = None,
            fee: uint64 = uint64(0),
            validate_only: bool = False,
            timelock_info: ConditionValidTimes = ConditionValidTimes(),
        ) -> CreateOfferForIDsResponse:
            self.add_to_log(
                "create_offer_for_ids",
                (offer_dict, tx_config, driver_dict, solver, fee, validate_only, timelock_info),
            )

            created_offer = Offer({}, WalletSpendBundle([], G2Element()), {})
            trade_offer: TradeRecord = TradeRecord(
                confirmed_at_index=uint32(0),
                accepted_at_time=None,
                created_at_time=uint64(12345678),
                is_my_offer=True,
                sent=uint32(0),
                sent_to=[],
                offer=bytes(WalletSpendBundle([], G2Element())),
                taken_offer=None,
                coins_of_interest=[],
                trade_id=get_bytes32(2),
                status=uint32(TradeStatus.PENDING_ACCEPT.value),
                valid_times=ConditionValidTimes(),
            )

            return CreateOfferForIDsResponse([STD_UTX], [STD_TX], created_offer, trade_offer)

    inst_rpc_client = MakeOfferRpcClient()
    test_rpc_clients.wallet_rpc_client = inst_rpc_client
    offer_cat_id = get_bytes32(4)
    request_cat_id = get_bytes32(2)
    request_nft_id = get_bytes32(2)
    request_nft_addr = encode_puzzle_hash(request_nft_id, "nft")
    # we offer xch and a random cat via wallet id and request a random cat, nft via coin and tail
    command_args = [
        "wallet",
        "make_offer",
        FINGERPRINT_ARG,
        f"-p{tmp_path / 'test.offer'!s}",
        "--reuse",
        "-m0.5",
        "--offer",
        "1:10",
        "--offer",
        "3:100",
        "--offer",
        f"{offer_cat_id.hex()}:100",
        "--request",
        f"{request_cat_id.hex()}:10",
        "--request",
        f"{request_nft_addr}:1",
        "--valid-at",
        "100",
        "--expires-at",
        "150",
    ]
    assert_list = [
        "OFFERING:\n  - 10 XCH (10000000000000 mojos)\n  - 100 test3 (100000 mojos)\n  - 100 test4 (100000 mojos)",
        "REQUESTING:\n  - 10 test2 (10000 mojos)\n"
        "  - 1 nft1qgpqyqszqgpqyqszqgpqyqszqgpqyqszqgpqyqszqgpqyqszqgpqyql4ft (1 mojos)",
        "Including Fees: 0.5 XCH, 500000000000 mojos",
        "Created offer with ID 0202020202020202020202020202020202020202020202020202020202020202",
    ]
    run_cli_command_and_assert(capsys, root_dir, command_args[:-8], ["without --override"])
    run_cli_command_and_assert(capsys, root_dir, command_args, assert_list)
    expected_calls: logType = {
        "cat_asset_id_to_name": [(offer_cat_id,), (request_cat_id,)],
        "get_nft_info": [(request_nft_id.hex(), True)],
        "get_cat_name": [(3,)],
        "nft_calculate_royalties": [
            (
                NFTCalculateRoyalties(
                    [
                        RoyaltyAsset(
                            "nft1qgpqyqszqgpqyqszqgpqyqszqgpqyqszqgpqyqszqgpqyqszqgpqyql4ft",
                            "xch1qvpsxqcrqvpsxqcrqvpsxqcrqvpsxqcrqvpsxqcrqvpsxqcrqvps82kgr2",
                            uint16(1000),
                        )
                    ],
                    [
                        FungibleAsset(
                            "XCH",
                            uint64(10000000000000),
                        ),
                        FungibleAsset(
                            "test3",
                            uint64(100000),
                        ),
                        FungibleAsset(
                            "test4",
                            uint64(100000),
                        ),
                    ],
                ),
            )
        ],
        "create_offer_for_ids": [
            (
                {
                    1: -10000000000000,
                    3: -100000,
                    "0404040404040404040404040404040404040404040404040404040404040404": -100000,
                    "0202020202020202020202020202020202020202020202020202020202020202": 10000,
                    "0101010101010101010101010101010101010101010101010101010101010101": 1,
                },
                DEFAULT_TX_CONFIG.override(reuse_puzhash=True),
                {
                    "0101010101010101010101010101010101010101010101010101010101010101": {
                        "type": "singleton",
                        "launcher_id": "0x0101010101010101010101010101010101010101010101010101010101010101",
                        "launcher_ph": "0xeff07522495060c066f66f32acc2a77e3a3e737aca8baea4d1a64ea4cdc13da9",
                        "also": {
                            "type": "metadata",
                            "metadata": "",
                            "updater_hash": "0x0707070707070707070707070707070707070707070707070707070707070707",
                            "also": {
                                "type": "ownership",
                                "owner": "()",
                                "transfer_program": {
                                    "type": "royalty transfer program",
                                    "launcher_id": "0x0101010101010101010101010101010101010101010101010101010101010101",
                                    "royalty_address": "0x0303030303030303030303030303030303030303030"
                                    "303030303030303030303",
                                    "royalty_percentage": "1000",
                                },
                            },
                        },
                    }
                },
                None,
                500000000000,
                False,
                test_condition_valid_times,
            )
        ],
    }
    test_rpc_clients.wallet_rpc_client.check_log(expected_calls)


def test_get_offers(capsys: object, get_test_cli_clients: tuple[TestRpcClients, Path]) -> None:
    test_rpc_clients, root_dir = get_test_cli_clients

    # set RPC Client
    class GetOffersRpcClient(TestWalletRpcClient):
        async def get_all_offers(
            self,
            start: int = 0,
            end: int = 50,
            sort_key: Optional[str] = None,
            reverse: bool = False,
            file_contents: bool = False,
            exclude_my_offers: bool = False,
            exclude_taken_offers: bool = False,
            include_completed: bool = False,
        ) -> list[TradeRecord]:
            self.add_to_log(
                "get_all_offers",
                (
                    start,
                    end,
                    sort_key,
                    reverse,
                    file_contents,
                    exclude_my_offers,
                    exclude_taken_offers,
                    include_completed,
                ),
            )
            records: list[TradeRecord] = []
            for i in reversed(range(start, end - 1)):  # reversed to match the sort order
                trade_offer = TradeRecord(
                    confirmed_at_index=uint32(0),
                    accepted_at_time=None,
                    created_at_time=uint64(12345678 + i),
                    is_my_offer=True,
                    sent=uint32(0),
                    sent_to=[],
                    offer=bytes(WalletSpendBundle([], G2Element())),
                    taken_offer=None,
                    coins_of_interest=[
                        Coin(bytes32([2 + i] * 32), bytes32([3 + i] * 32), uint64(1000)),
                        Coin(bytes32([4 + i] * 32), bytes32([5 + i] * 32), uint64(1000)),
                    ],
                    trade_id=bytes32([1 + i] * 32),
                    status=uint32(TradeStatus.PENDING_ACCEPT.value),
                    valid_times=ConditionValidTimes(
                        min_time=uint64(0),
                        max_time=uint64(100),
                        min_height=uint32(0),
                        max_height=uint32(100),
                    ),
                )
                records.append(trade_offer)
            return records

    inst_rpc_client = GetOffersRpcClient()
    test_rpc_clients.wallet_rpc_client = inst_rpc_client
    command_args = [
        "wallet",
        "get_offers",
        FINGERPRINT_ARG,
        "--exclude-my-offers",
        "--exclude-taken-offers",
        "--include-completed",
        "--reverse",
        "--sort-by-relevance",
    ]
    # these are various things that should be in the output
    assert_list = [
        "Confirmed at: Not confirmed",
        "Accepted at: N/A",
        "Status: PENDING_ACCEPT",
        "Record with id: 0909090909090909090909090909090909090909090909090909090909090909",
        "Record with id: 0808080808080808080808080808080808080808080808080808080808080808",
        "Record with id: 0707070707070707070707070707070707070707070707070707070707070707",
        "Record with id: 0606060606060606060606060606060606060606060606060606060606060606",
        "Record with id: 0505050505050505050505050505050505050505050505050505050505050505",
        "Record with id: 0404040404040404040404040404040404040404040404040404040404040404",
        "Record with id: 0303030303030303030303030303030303030303030303030303030303030303",
        "Record with id: 0202020202020202020202020202020202020202020202020202020202020202",
        "Record with id: 0101010101010101010101010101010101010101010101010101010101010101",
    ]
    run_cli_command_and_assert(capsys, root_dir, command_args, assert_list)
    expected_calls: logType = {"get_all_offers": [(0, 10, "RELEVANCE", True, False, True, True, True)]}
    command_args = [
        "wallet",
        "get_offers",
        FINGERPRINT_ARG,
        "--summaries",
    ]
    tzinfo = datetime.datetime.now(datetime.timezone.utc).astimezone().tzinfo
    # these are various things that should be in the output
    assert_list = [
        "Timelock information:",
        "  - Not valid until ",
        "  - Expires at ",
        f"{datetime.datetime.fromtimestamp(0, tz=tzinfo).strftime('%Y-%m-%d %H:%M %Z')}",
        f"{datetime.datetime.fromtimestamp(100, tz=tzinfo).strftime('%Y-%m-%d %H:%M %Z')}",
        "height 0",
        "height 100",
    ]
    run_cli_command_and_assert(capsys, root_dir, command_args, assert_list)
    assert expected_calls["get_all_offers"] is not None
    expected_calls["get_all_offers"].append((0, 10, "CONFIRMED_AT_HEIGHT", False, True, False, False, False))
    test_rpc_clients.wallet_rpc_client.check_log(expected_calls)


def test_take_offer(capsys: object, get_test_cli_clients: tuple[TestRpcClients, Path]) -> None:
    test_rpc_clients, root_dir = get_test_cli_clients

    # set RPC Client
    class TakeOfferRpcClient(TestWalletRpcClient):
        async def take_offer(
            self,
            offer: Offer,
            tx_config: TXConfig,
            solver: Optional[dict[str, Any]] = None,
            fee: uint64 = uint64(0),
            push: bool = True,
            timelock_info: ConditionValidTimes = ConditionValidTimes(),
        ) -> TakeOfferResponse:
            self.add_to_log("take_offer", (offer, tx_config, solver, fee, push, timelock_info))
            return TakeOfferResponse(
                [STD_UTX],
                [STD_TX],
                offer,
                TradeRecord(
                    confirmed_at_index=uint32(0),
                    accepted_at_time=uint64(123456789),
                    created_at_time=uint64(12345678),
                    is_my_offer=False,
                    sent=uint32(1),
                    sent_to=[("aaaaa", uint8(1), None)],
                    offer=bytes(offer),
                    taken_offer=None,
                    coins_of_interest=offer.get_involved_coins(),
                    trade_id=offer.name(),
                    status=uint32(TradeStatus.PENDING_ACCEPT.value),
                    valid_times=ConditionValidTimes(),
                ),
            )

        async def cat_asset_id_to_name(self, asset_id: bytes32) -> Optional[tuple[Optional[uint32], str]]:
            self.add_to_log("cat_asset_id_to_name", (asset_id,))
            if asset_id == cat_offered_id:
                return uint32(2), "offered cat"
            elif asset_id == cat_requested_id:
                return uint32(3), "requested cat"
            else:
                return None

    inst_rpc_client = TakeOfferRpcClient()
    test_rpc_clients.wallet_rpc_client = inst_rpc_client
    # these are various things that should be in the output
    nft_offered_id = bytes32.from_hexstr("6bc2c2a27c0f04b9e1e57933d2efe08f5b9e156652a374436b70c067b03c444c")
    cat_offered_id = bytes32.from_hexstr("06e4136cb7295cec5265c5e49cc32fa69aede779532f2b7542a2456589a53f2f")
    cat_requested_id = bytes32.from_hexstr("13a52e5efb1ee80a24c94b36bbda2b473094353614ced1c2938ba5ef6097431e")
    nft_requested_id_1 = bytes32.from_hexstr("7657b5f1cdee70459052c314f839bb1b76b8c3f444671da71ad7dfcb6c47f243")
    nft_requested_id_2 = bytes32.from_hexstr("5f03cdb94c96325f49f4abf1d4d10cabd5ea583632fbf20f251b7fad73645a14")
    assert_list = [
        "  OFFERED:\n"
        f"    - {nft_offered_id.hex()}: 0.001 (1 mojo)\n"
        f"    - offered cat (Wallet ID: 2): 100.0 (100000 mojos)\n",
        "  REQUESTED:\n"
        "    - XCH (Wallet ID: 1): 2.0 (2000000000000 mojos)\n"
        f"    - {nft_requested_id_1.hex()}: 0.001 (1 mojo)\n"
        f"    - {nft_requested_id_2.hex()}: 0.001 (1 mojo)\n",
        "    - requested cat (Wallet ID: 3): 100.0 (100000 mojos)\n",
        "Royalties Summary:\n"
        f"  - For {encode_puzzle_hash(nft_offered_id, 'nft')}:\n"
        "    - 0.2 XCH (200000000000 mojos) to xch1qvpsxqcrqvpsxqcrqvpsxqcrqvpsxqcrqvpsxqcrqvpsxqcrqvps82kgr2\n"
        "    - 10 requested cat (10000 mojos) to xch1qvpsxqcrqvpsxqcrqvpsxqcrqvpsxqcrqvpsxqcrqvpsxqcrqvps82kgr2\n",
        "Total Amounts Requested:\n",
        "  - 2.2 XCH (2200000000000 mojos)\n  - 110 requested cat (110000 mojos)\n",
        "Accepted offer with ID 71fd6de245d896c691b0115cdb9b47904cb60858ae87b86bfd648b23208b6cc1",
    ]

    with importlib_resources.as_file(test_offer_file_path) as test_offer_file_name:
        command_args = [
            "wallet",
            "take_offer",
            os.fspath(test_offer_file_name),
            FINGERPRINT_ARG,
            "-m0.5",
            "--reuse",
            "--valid-at",
            "100",
            "--expires-at",
            "150",
        ]
        run_cli_command_and_assert(capsys, root_dir, command_args, assert_list)

    expected_calls: logType = {
        "cat_asset_id_to_name": [
            (nft_offered_id,),
            (cat_offered_id,),
            (nft_requested_id_1,),
            (nft_requested_id_2,),
            (cat_requested_id,),
            (cat_requested_id,),
        ],
        "take_offer": [
            (
                Offer.from_bech32(test_offer_file_bech32),
                DEFAULT_TX_CONFIG,
                None,
                500000000000,
                True,
                test_condition_valid_times,
            )
        ],
    }
    test_rpc_clients.wallet_rpc_client.check_log(expected_calls)


def test_cancel_offer(capsys: object, get_test_cli_clients: tuple[TestRpcClients, Path]) -> None:
    test_rpc_clients, root_dir = get_test_cli_clients

    # set RPC Client
    class CancelOfferRpcClient(TestWalletRpcClient):
        async def get_offer(self, trade_id: bytes32, file_contents: bool = False) -> TradeRecord:
            self.add_to_log("get_offer", (trade_id, file_contents))
            offer = Offer.from_bech32(test_offer_file_bech32)
            return TradeRecord(
                confirmed_at_index=uint32(0),
                accepted_at_time=uint64(0),
                created_at_time=uint64(12345678),
                is_my_offer=True,
                sent=uint32(0),
                sent_to=[],
                offer=bytes(offer),
                taken_offer=None,
                coins_of_interest=offer.get_involved_coins(),
                trade_id=offer.name(),
                status=uint32(TradeStatus.PENDING_ACCEPT.value),
                valid_times=ConditionValidTimes(),
            )

        async def cancel_offer(
            self,
            trade_id: bytes32,
            tx_config: TXConfig,
            fee: uint64 = uint64(0),
            secure: bool = True,
            push: bool = True,
            timelock_info: ConditionValidTimes = ConditionValidTimes(),
        ) -> CancelOfferResponse:
            self.add_to_log("cancel_offer", (trade_id, tx_config, fee, secure, push, timelock_info))
            return CancelOfferResponse([STD_UTX], [STD_TX])

    inst_rpc_client = CancelOfferRpcClient()
    test_rpc_clients.wallet_rpc_client = inst_rpc_client
    command_args = [
        "wallet",
        "cancel_offer",
        FINGERPRINT_ARG,
        "-m0.5",
        "--id",
        test_offer_id,
        "--valid-at",
        "100",
        "--expires-at",
        "150",
    ]
    # these are various things that should be in the output
    nft_offered_id = bytes32.from_hexstr("6bc2c2a27c0f04b9e1e57933d2efe08f5b9e156652a374436b70c067b03c444c")
    cat_offered_id = bytes32.from_hexstr("06e4136cb7295cec5265c5e49cc32fa69aede779532f2b7542a2456589a53f2f")
    cat_requested_id = bytes32.from_hexstr("13a52e5efb1ee80a24c94b36bbda2b473094353614ced1c2938ba5ef6097431e")
    nft_requested_id_1 = bytes32.from_hexstr("7657b5f1cdee70459052c314f839bb1b76b8c3f444671da71ad7dfcb6c47f243")
    nft_requested_id_2 = bytes32.from_hexstr("5f03cdb94c96325f49f4abf1d4d10cabd5ea583632fbf20f251b7fad73645a14")
    assert_list = [
        "Cancelled offer with ID 71fd6de245d896c691b0115cdb9b47904cb60858ae87b86bfd648b23208b6cc1",
    ]
    run_cli_command_and_assert(capsys, root_dir, command_args, assert_list)
    expected_calls: logType = {
        "get_offer": [(test_offer_id_bytes, True)],
        "cancel_offer": [
            (test_offer_id_bytes, DEFAULT_TX_CONFIG, 500000000000, True, True, test_condition_valid_times)
        ],
        "cat_asset_id_to_name": [
            (nft_offered_id,),
            (cat_offered_id,),
            (nft_requested_id_1,),
            (nft_requested_id_2,),
            (cat_requested_id,),
            (nft_offered_id,),
            (cat_offered_id,),
        ],
    }
    test_rpc_clients.wallet_rpc_client.check_log(expected_calls)
