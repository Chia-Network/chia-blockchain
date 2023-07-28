from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from blspy import G2Element
from chia_rs import Coin

from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.spend_bundle import SpendBundle
from chia.util.ints import uint8, uint32, uint64
from chia.wallet.transaction_record import TransactionRecord
from chia.wallet.transaction_sorting import SortKey
from chia.wallet.util.query_filter import HashFilter, TransactionTypeFilter
from chia.wallet.util.transaction_type import TransactionType
from chia.wallet.wallet_coin_store import GetCoinRecords
from tests.cmds.cmd_test_utils import TestRpcClients, TestWalletRpcClient, cli_assert_shortcut, logType, run_cli_command

FINGERPRINT = "123456"
FINGERPRINT_ARG = f"-f{FINGERPRINT}"
CAT_FINGERPRINT = "789101"
CAT_FINGERPRINT_ARG = f"-f{CAT_FINGERPRINT}"
WALLET_ID = 1
WALLET_ID_ARG = f"-i{WALLET_ID}"
bytes32_hexstr = "0x6262626262626262626262626262626262626262626262626262626262626262"


def test_get_transaction(capsys: object, get_test_cli_clients: Tuple[TestRpcClients, Path]) -> None:
    test_rpc_clients, root_dir = get_test_cli_clients
    # set RPC Client
    inst_rpc_client = TestWalletRpcClient()  # pylint: disable=no-value-for-parameter
    test_rpc_clients.wallet_rpc_client = inst_rpc_client
    # get output with all options but verbose
    command_args = ["wallet", "get_transaction", FINGERPRINT_ARG, WALLET_ID_ARG, "-tx", bytes32_hexstr]
    success, output = run_cli_command(capsys, root_dir, command_args)
    v_success, v_output = run_cli_command(capsys, root_dir, command_args + ["-v"])
    assert success, v_success
    # these are various things that should be in the output
    assert_list = [
        "Transaction 0202020202020202020202020202020202020202020202020202020202020202",
        "Status: In mempool",
        "Amount sent: 0.000012345678 XCH",
        "To address: xch1qyqszqgpqyqszqgpqyqszqgpqyqszqgpqyqszqgpqyqszqgpqyqs0wg4qq",
    ]
    cli_assert_shortcut(output, assert_list)
    v_assert_list = [
        "0x0303030303030303030303030303030303030303030303030303030303030303",
        "'amount': 12345678",
        "'to_puzzle_hash': '0x0101010101010101010101010101010101010101010101010101010101010101',",
    ]
    cli_assert_shortcut(v_output, v_assert_list)
    expected_calls: logType = {
        "get_wallets": [(), ()],
        "get_transaction": [(37, bytes32.from_hexstr(bytes32_hexstr)), (37, bytes32.from_hexstr(bytes32_hexstr))],
    }
    test_rpc_clients.wallet_rpc_client.check_log(expected_calls)


def test_get_transactions(capsys: object, get_test_cli_clients: Tuple[TestRpcClients, Path]) -> None:
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
        ) -> List[TransactionRecord]:
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
                    spend_bundle=SpendBundle([], G2Element()),
                    additions=[Coin(bytes32([1 + i] * 32), bytes32([2 + i] * 32), uint64(12345678))],
                    removals=[Coin(bytes32([2 + i] * 32), bytes32([4 + i] * 32), uint64(12345678))],
                    wallet_id=uint32(1),
                    sent_to=[("aaaaa", uint8(1), None)],
                    trade_id=None,
                    type=uint32(t_type.value),
                    name=bytes32([2 + i] * 32),
                    memos=[(bytes32([3 + i] * 32), [bytes([4 + i] * 32)])],
                )
                l_tx_rec.append(tx_rec)

            return l_tx_rec

        async def get_coin_records(self, request: GetCoinRecords) -> Dict[str, Any]:
            self.add_to_log("get_coin_records", (request,))
            return {
                "coin_records": [{"metadata": {"time_lock": 12345678}}],
                "total_count": 1,
            }

    inst_rpc_client = GetTransactionsWalletRpcClient()  # pylint: disable=no-value-for-parameter
    test_rpc_clients.wallet_rpc_client = inst_rpc_client
    # get output with all options but verbose
    command_args = [
        "wallet",
        "get_transactions",
        FINGERPRINT_ARG,
        WALLET_ID_ARG,
        "--no-paginate",
        "--testing",
        "--reverse",
        "-o2",
        "-l2",
    ]
    success, output = run_cli_command(capsys, root_dir, command_args)
    v_success, v_output = run_cli_command(capsys, root_dir, command_args + ["-v"])
    assert success, v_success
    # these are various things that should be in the output
    assert_list = [
        "Transaction 0404040404040404040404040404040404040404040404040404040404040404",
        "Transaction 0505050505050505050505050505050505050505050505050505050505050505",
        "Amount received: 0.00001234568 XCH",
        "Amount received in clawback as sender: 0.000012345681 XCH",
        "To address: xch1qvpsxqcrqvpsxqcrqvpsxqcrqvpsxqcrqvpsxqcrqvpsxqcrqvps82kgr2",
        "To address: xch1qszqgpqyqszqgpqyqszqgpqyqszqgpqyqszqgpqyqszqgpqyqszqkxck8d",
    ]
    cli_assert_shortcut(output, assert_list)
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
    cli_assert_shortcut(v_output, v_assert_list)
    expected_coin_id = Coin(bytes32([4] * 32), bytes32([5] * 32), uint64(12345678)).name()
    expected_calls: logType = {
        "get_wallets": [(), ()],
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
