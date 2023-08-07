from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

from blspy import G2Element
from chia_rs import Coin

from chia.server.outbound_message import NodeType
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.signing_mode import SigningMode
from chia.types.spend_bundle import SpendBundle
from chia.util.bech32m import encode_puzzle_hash
from chia.util.ints import uint8, uint32, uint64
from chia.wallet.puzzle_drivers import PuzzleInfo
from chia.wallet.trade_record import TradeRecord
from chia.wallet.trading.offer import NotarizedPayment, Offer
from chia.wallet.trading.trade_status import TradeStatus
from chia.wallet.transaction_record import TransactionRecord
from chia.wallet.transaction_sorting import SortKey
from chia.wallet.util.query_filter import HashFilter, TransactionTypeFilter
from chia.wallet.util.transaction_type import TransactionType
from chia.wallet.util.wallet_types import WalletType
from chia.wallet.wallet_coin_store import GetCoinRecords
from tests.cmds.cmd_test_utils import TestRpcClients, TestWalletRpcClient, cli_assert_shortcut, logType, run_cli_command

FINGERPRINT: str = "123456"
FINGERPRINT_ARG: str = f"-f{FINGERPRINT}"
CAT_FINGERPRINT: str = "789101"
CAT_FINGERPRINT_ARG: str = f"-f{CAT_FINGERPRINT}"
WALLET_ID: int = 1
WALLET_ID_ARG: str = f"-i{WALLET_ID}"
bytes32_hexstr = "0x6262626262626262626262626262626262626262626262626262626262626262"

test_offer_file_path: Path = Path("tests") / "cmds" / "test_offer.toffer"
test_offer_file_name: str = str(test_offer_file_path)
test_offer_file_bech32: str = open(test_offer_file_name, "r").read()
test_offer_id: str = "0xdfb7e8643376820ec995b0bcdb3fc1f764c16b814df5e074631263fcf1e00839"
test_offer_id_bytes: bytes32 = bytes32.from_hexstr(test_offer_id)


def test_get_transaction(capsys: object, get_test_cli_clients: Tuple[TestRpcClients, Path]) -> None:
    test_rpc_clients, root_dir = get_test_cli_clients
    # set RPC Client
    inst_rpc_client = TestWalletRpcClient()  # pylint: disable=no-value-for-parameter
    test_rpc_clients.wallet_rpc_client = inst_rpc_client
    # get output with all options but verbose
    command_args = ["wallet", "get_transaction", WALLET_ID_ARG, "-tx", bytes32_hexstr]
    success, output = run_cli_command(capsys, root_dir, command_args + [FINGERPRINT_ARG])
    v_success, v_output = run_cli_command(capsys, root_dir, command_args + [FINGERPRINT_ARG, "-v"])
    cat_success, cat_output = run_cli_command(capsys, root_dir, command_args + [CAT_FINGERPRINT_ARG])
    assert success and v_success and cat_success
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
    cat_assert_list = [
        "Transaction 0202020202020202020202020202020202020202020202020202020202020202",
        "Status: In mempool",
        "Amount sent: 12345.678 test1",
        "To address: xch1qyqszqgpqyqszqgpqyqszqgpqyqszqgpqyqszqgpqyqszqgpqyqs0wg4qq",
    ]
    cli_assert_shortcut(cat_output, cat_assert_list)
    expected_calls: logType = {
        "get_wallets": [(None,), (None,), (None,)],
        "get_cat_name": [(1,)],
        "get_transaction": [
            (37, bytes32.from_hexstr(bytes32_hexstr)),
            (37, bytes32.from_hexstr(bytes32_hexstr)),
            (37, bytes32.from_hexstr(bytes32_hexstr)),
        ],
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
    assert success and v_success
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


def test_show(capsys: object, get_test_cli_clients: Tuple[TestRpcClients, Path]) -> None:
    test_rpc_clients, root_dir = get_test_cli_clients

    # set RPC Client
    class ShowRpcClient(TestWalletRpcClient):
        async def get_wallets(self, wallet_type: Optional[WalletType] = None) -> List[Dict[str, Union[str, int]]]:
            self.add_to_log("get_wallets", (wallet_type,))
            wallet_list: List[Dict[str, Union[str, int]]] = [
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

        async def get_sync_status(self) -> bool:
            self.add_to_log("get_sync_status", ())
            return False

        async def get_synced(self) -> bool:
            self.add_to_log("get_synced", ())
            return True

        async def get_height_info(self) -> uint32:
            self.add_to_log("get_height_info", ())
            return uint32(10)

        async def get_wallet_balance(self, wallet_id: int) -> Dict[str, uint64]:
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

        async def get_nft_wallet_did(self, wallet_id: uint8) -> dict[str, Optional[str]]:
            self.add_to_log("get_nft_wallet_did", (wallet_id,))
            return {"did_id": "0xcee228b8638c67cb66a55085be99fa3b457ae5b56915896f581990f600b2c652"}

        async def get_connections(
            self, node_type: Optional[NodeType] = None
        ) -> List[Dict[str, Union[str, int, float, bytes32]]]:
            self.add_to_log("get_connections", (node_type,))
            return [
                {
                    "bytes_read": 10000,
                    "bytes_written": 100,
                    "creation_time": 169140000.0,
                    "last_message_time": 169141001.0,
                    "local_port": 19411,
                    "node_id": bytes32([1] * 32),
                    "peer_host": "127.0.0.1",
                    "peer_port": 47482,
                    "peer_server_port": 47482,
                    "type": 1,
                }
            ]

    inst_rpc_client = ShowRpcClient()  # pylint: disable=no-value-for-parameter
    test_rpc_clients.wallet_rpc_client = inst_rpc_client
    command_args = ["wallet", "show", FINGERPRINT_ARG]
    success, output = run_cli_command(capsys, root_dir, command_args)
    other_success, other_output = run_cli_command(capsys, root_dir, command_args + ["--wallet_type", "cat"])
    assert success and other_success
    # these are various things that should be in the output
    assert_list = [
        "Chia Wallet:\n   -Total Balance:         0.001 xch (1000000000 mojo)",
        "test2:\n   -Total Balance:         2000000.0  (2000000000 mojo)",
        "   -Asset ID:              dc59bcd60ce5fc9c93a5d3b11875486b03efb53a53da61e453f5cf61a7746860",
        "NFT Wallet:\n   -Total Balance:         1.0",
        "   -DID ID:                0xcee228b8638c67cb66a55085be99fa3b457ae5b56915896f581990f600b2c652",
        "FULL_NODE 127.0.0.1",
        "47482/47482 01010101... May 12",
    ]
    other_assert_list = [
        "test2:\n   -Total Balance:         2000000.0  (2000000000 mojo)",
        "   -Asset ID:              dc59bcd60ce5fc9c93a5d3b11875486b03efb53a53da61e453f5cf61a7746860",
        "FULL_NODE 127.0.0.1",
        "47482/47482 01010101... May 12",
    ]
    cli_assert_shortcut(output, assert_list)
    cli_assert_shortcut(other_output, other_assert_list)
    expected_calls: logType = {
        "get_wallets": [(None,), (WalletType.CAT,)],
        "get_synced": [(), ()],
        "get_sync_status": [(), ()],
        "get_height_info": [(), ()],
        "get_wallet_balance": [(1,), (2,), (3,), (2,)],
        "get_nft_wallet_did": [(3,)],
        "get_connections": [(None,), (None,)],
    }
    test_rpc_clients.wallet_rpc_client.check_log(expected_calls)


def test_send(capsys: object, get_test_cli_clients: Tuple[TestRpcClients, Path]) -> None:
    test_rpc_clients, root_dir = get_test_cli_clients

    # set RPC Client
    class SendWalletRpcClient(TestWalletRpcClient):
        async def send_transaction(
            self,
            wallet_id: int,
            amount: uint64,
            address: str,
            fee: uint64 = uint64(0),
            memos: Optional[List[str]] = None,
            min_coin_amount: uint64 = uint64(0),
            max_coin_amount: uint64 = uint64(0),
            excluded_amounts: Optional[List[uint64]] = None,
            excluded_coin_ids: Optional[Sequence[str]] = None,
            puzzle_decorator_override: Optional[List[Dict[str, Union[str, int, bool]]]] = None,
            reuse_puzhash: Optional[bool] = None,
        ) -> TransactionRecord:
            self.add_to_log(
                "send_transaction",
                (
                    wallet_id,
                    amount,
                    address,
                    fee,
                    memos,
                    min_coin_amount,
                    max_coin_amount,
                    excluded_amounts,
                    excluded_coin_ids,
                    puzzle_decorator_override,
                    reuse_puzhash,
                ),
            )
            tx_rec = TransactionRecord(
                confirmed_at_height=uint32(1),
                created_at_time=uint64(1234),
                to_puzzle_hash=bytes32([1] * 32),
                amount=uint64(12345678),
                fee_amount=uint64(1234567),
                confirmed=False,
                sent=uint32(0),
                spend_bundle=SpendBundle([], G2Element()),
                additions=[Coin(bytes32([1] * 32), bytes32([2] * 32), uint64(12345678))],
                removals=[Coin(bytes32([2] * 32), bytes32([4] * 32), uint64(12345678))],
                wallet_id=uint32(1),
                sent_to=[("aaaaa", uint8(1), None)],
                trade_id=None,
                type=uint32(TransactionType.OUTGOING_CLAWBACK.value),
                name=bytes32([2] * 32),
                memos=[(bytes32([3] * 32), [bytes([4] * 32)])],
            )
            return tx_rec

        async def cat_spend(
            self,
            wallet_id: int,
            amount: Optional[uint64] = None,
            inner_address: Optional[str] = None,
            fee: uint64 = uint64(0),
            memos: Optional[List[str]] = None,
            min_coin_amount: uint64 = uint64(0),
            max_coin_amount: uint64 = uint64(0),
            excluded_amounts: Optional[List[uint64]] = None,
            excluded_coin_ids: Optional[Sequence[str]] = None,
            additions: Optional[List[Dict[str, Any]]] = None,
            removals: Optional[List[Coin]] = None,
            cat_discrepancy: Optional[Tuple[int, Program, Program]] = None,  # (extra_delta, tail_reveal, tail_solution)
            reuse_puzhash: Optional[bool] = None,
        ) -> TransactionRecord:
            self.add_to_log(
                "cat_spend",
                (
                    wallet_id,
                    amount,
                    inner_address,
                    fee,
                    memos,
                    min_coin_amount,
                    max_coin_amount,
                    excluded_amounts,
                    excluded_coin_ids,
                    additions,
                    removals,
                    cat_discrepancy,
                    reuse_puzhash,
                ),
            )
            tx_rec = TransactionRecord(
                confirmed_at_height=uint32(2),
                created_at_time=uint64(1235),
                to_puzzle_hash=bytes32([2] * 32),
                amount=uint64(12345679),
                fee_amount=uint64(1234568),
                confirmed=False,
                sent=uint32(0),
                spend_bundle=SpendBundle([], G2Element()),
                additions=[Coin(bytes32([2] * 32), bytes32([4] * 32), uint64(12345678))],
                removals=[Coin(bytes32([3] * 32), bytes32([5] * 32), uint64(12345678))],
                wallet_id=uint32(1),
                sent_to=[("aaaaa", uint8(1), None)],
                trade_id=None,
                type=uint32(TransactionType.OUTGOING_TX.value),
                name=bytes32([3] * 32),
                memos=[(bytes32([5] * 32), [bytes([6] * 32)])],
            )
            return tx_rec

    inst_rpc_client = SendWalletRpcClient()  # pylint: disable=no-value-for-parameter
    test_rpc_clients.wallet_rpc_client = inst_rpc_client
    # get output with all options but verbose
    addr = encode_puzzle_hash(bytes32([3] * 32), "xch")
    command_args = [
        "wallet",
        "send",
        "-a1",
        "-m1",
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
    ]
    success, output = run_cli_command(capsys, root_dir, command_args + [FINGERPRINT_ARG])
    c_success, c_output = run_cli_command(capsys, root_dir, command_args + [CAT_FINGERPRINT_ARG])
    assert success and c_success
    # these are various things that should be in the output
    assert_list = ["Transaction submitted to nodes: [{'peer_id': 'aaaaa'", f"-f 123456 -tx 0x{bytes32([2] * 32).hex()}"]
    cli_assert_shortcut(output, assert_list)
    cat_assert_list = [
        "Transaction submitted to nodes: [{'peer_id': 'aaaaa'",
        f"-f 789101 -tx 0x{bytes32([3] * 32).hex()}",
    ]
    cli_assert_shortcut(c_output, cat_assert_list)
    expected_calls: logType = {
        "get_wallets": [(None,), (None,)],
        "send_transaction": [
            (
                1,
                1000000000000,
                "xch1qvpsxqcrqvpsxqcrqvpsxqcrqvpsxqcrqvpsxqcrqvpsxqcrqvps82kgr2",
                1000000000000,
                ["0x6262626262626262626262626262626262626262626262626262626262626262"],
                0,
                10000000000000,
                None,
                ("0x6262626262626262626262626262626262626262626262626262626262626262",),
                [{"decorator": "CLAWBACK", "clawback_timelock": 60}],
                True,
            )
        ],
        "cat_spend": [
            (
                1,
                1000,
                "xch1qvpsxqcrqvpsxqcrqvpsxqcrqvpsxqcrqvpsxqcrqvpsxqcrqvps82kgr2",
                1000000000000,
                ["0x6262626262626262626262626262626262626262626262626262626262626262"],
                0,
                10000,
                None,
                ("0x6262626262626262626262626262626262626262626262626262626262626262",),
                None,
                None,
                None,
                True,
            )
        ],
        "get_transaction": [(1, bytes32([2] * 32)), (1, bytes32([3] * 32))],
    }
    test_rpc_clients.wallet_rpc_client.check_log(expected_calls)


def test_get_address(capsys: object, get_test_cli_clients: Tuple[TestRpcClients, Path]) -> None:
    test_rpc_clients, root_dir = get_test_cli_clients

    # set RPC Client
    class GetAddressWalletRpcClient(TestWalletRpcClient):
        async def get_next_address(self, wallet_id: int, new_address: bool) -> str:
            self.add_to_log("get_next_address", (wallet_id, new_address))
            if new_address:
                return encode_puzzle_hash(bytes32([3] * 32), "xch")
            return encode_puzzle_hash(bytes32([4] * 32), "xch")

    inst_rpc_client = GetAddressWalletRpcClient()  # pylint: disable=no-value-for-parameter
    test_rpc_clients.wallet_rpc_client = inst_rpc_client
    # get output with all options but verbose
    addr1 = encode_puzzle_hash(bytes32([3] * 32), "xch")
    addr2 = encode_puzzle_hash(bytes32([4] * 32), "xch")
    command_args = [
        "wallet",
        "get_address",
        WALLET_ID_ARG,
        FINGERPRINT_ARG,
    ]
    success, output = run_cli_command(capsys, root_dir, command_args + ["-n"])
    other_success, other_output = run_cli_command(capsys, root_dir, command_args + ["-l"])
    assert success and other_success
    # these are various things that should be in the output
    assert_list = [addr1]
    cli_assert_shortcut(output, assert_list)
    other_assert_list = [addr2]
    cli_assert_shortcut(other_output, other_assert_list)
    expected_calls: logType = {
        "get_next_address": [(1, True), (1, False)],
    }
    test_rpc_clients.wallet_rpc_client.check_log(expected_calls)


def test_clawback(capsys: object, get_test_cli_clients: Tuple[TestRpcClients, Path]) -> None:
    test_rpc_clients, root_dir = get_test_cli_clients

    # set RPC Client
    class ClawbackWalletRpcClient(TestWalletRpcClient):
        async def spend_clawback_coins(
            self,
            coin_ids: List[bytes32],
            fee: int = 0,
            force: bool = False,
        ) -> Dict[str, Any]:
            self.add_to_log("spend_clawback_coins", (coin_ids, fee, force))
            tx_hex_list = [bytes32([6] * 32).hex(), bytes32([7] * 32).hex(), bytes32([8] * 32).hex()]
            return {"transaction_ids": tx_hex_list}

    inst_rpc_client = ClawbackWalletRpcClient()  # pylint: disable=no-value-for-parameter
    test_rpc_clients.wallet_rpc_client = inst_rpc_client
    tx_ids = [bytes32([3] * 32), bytes32([4] * 32), bytes32([5] * 32)]
    r_tx_ids_hex = [bytes32([6] * 32).hex(), bytes32([7] * 32).hex(), bytes32([8] * 32).hex()]
    command_args = [
        "wallet",
        "clawback",
        WALLET_ID_ARG,
        FINGERPRINT_ARG,
        "-m1",
        "--tx_ids",
        f"{tx_ids[0].hex()},{tx_ids[1].hex()}, {tx_ids[2].hex()}",
    ]
    success, output = run_cli_command(capsys, root_dir, command_args)
    assert success
    # these are various things that should be in the output
    assert_list = ["transaction_ids", str(r_tx_ids_hex)]
    cli_assert_shortcut(output, assert_list)
    expected_calls: logType = {
        "spend_clawback_coins": [(tx_ids, 1000000000000, False)],
    }
    test_rpc_clients.wallet_rpc_client.check_log(expected_calls)


def test_del_unconfirmed_tx(capsys: object, get_test_cli_clients: Tuple[TestRpcClients, Path]) -> None:
    test_rpc_clients, root_dir = get_test_cli_clients

    # set RPC Client
    class UnconfirmedTxRpcClient(TestWalletRpcClient):
        async def delete_unconfirmed_transactions(self, wallet_id: int) -> None:
            self.add_to_log("delete_unconfirmed_transactions", (wallet_id,))
            return None

    inst_rpc_client = UnconfirmedTxRpcClient()  # pylint: disable=no-value-for-parameter
    test_rpc_clients.wallet_rpc_client = inst_rpc_client
    command_args = [
        "wallet",
        "delete_unconfirmed_transactions",
        WALLET_ID_ARG,
        FINGERPRINT_ARG,
    ]
    success, output = run_cli_command(capsys, root_dir, command_args)
    assert success
    # these are various things that should be in the output
    assert_list = [f"Successfully deleted all unconfirmed transactions for wallet id {WALLET_ID} on key {FINGERPRINT}"]
    cli_assert_shortcut(output, assert_list)
    expected_calls: logType = {
        "delete_unconfirmed_transactions": [(1,)],
    }
    test_rpc_clients.wallet_rpc_client.check_log(expected_calls)


def test_get_derivation_index(capsys: object, get_test_cli_clients: Tuple[TestRpcClients, Path]) -> None:
    test_rpc_clients, root_dir = get_test_cli_clients

    # set RPC Client
    class GetDerivationIndexRpcClient(TestWalletRpcClient):
        async def get_current_derivation_index(self) -> str:
            self.add_to_log("get_current_derivation_index", ())
            return str(520)

    inst_rpc_client = GetDerivationIndexRpcClient()  # pylint: disable=no-value-for-parameter
    test_rpc_clients.wallet_rpc_client = inst_rpc_client
    command_args = [
        "wallet",
        "get_derivation_index",
        FINGERPRINT_ARG,
    ]
    success, output = run_cli_command(capsys, root_dir, command_args)
    assert success
    # these are various things that should be in the output
    assert_list = ["Last derivation index: 520"]
    cli_assert_shortcut(output, assert_list)
    expected_calls: logType = {
        "get_current_derivation_index": [()],
    }
    test_rpc_clients.wallet_rpc_client.check_log(expected_calls)


def test_sign_message(capsys: object, get_test_cli_clients: Tuple[TestRpcClients, Path]) -> None:
    test_rpc_clients, root_dir = get_test_cli_clients

    # set RPC Client

    inst_rpc_client = TestWalletRpcClient()  # pylint: disable=no-value-for-parameter
    test_rpc_clients.wallet_rpc_client = inst_rpc_client
    xch_addr = encode_puzzle_hash(bytes32([1] * 32), "xch")
    message = b"hello world"
    command_args = ["wallet", "sign_message", FINGERPRINT_ARG, f"-m{message.hex()}"]
    success, output = run_cli_command(capsys, root_dir, command_args + [f"-a{xch_addr}"])
    assert success
    # these are various things that should be in the output
    assert_list = [
        f"Message: {message.hex()}",
        f"Public Key: {bytes([3] * 48).hex()}",
        f"Signature: {bytes([6] * 576).hex()}",
        f"Signing Mode: {SigningMode.CHIP_0002.value}",
    ]
    cli_assert_shortcut(output, assert_list)
    expected_calls: logType = {
        "sign_message_by_address": [(xch_addr, message.hex())],  # xch std
    }
    test_rpc_clients.wallet_rpc_client.check_log(expected_calls)


def test_update_derivation_index(capsys: object, get_test_cli_clients: Tuple[TestRpcClients, Path]) -> None:
    test_rpc_clients, root_dir = get_test_cli_clients

    # set RPC Client
    class UpdateDerivationIndexRpcClient(TestWalletRpcClient):
        async def extend_derivation_index(self, index: int) -> str:
            self.add_to_log("extend_derivation_index", (index,))
            return str(index)

    inst_rpc_client = UpdateDerivationIndexRpcClient()  # pylint: disable=no-value-for-parameter
    test_rpc_clients.wallet_rpc_client = inst_rpc_client
    index = 600
    command_args = ["wallet", "update_derivation_index", FINGERPRINT_ARG, "--index", str(index)]
    success, output = run_cli_command(capsys, root_dir, command_args)
    assert success
    # these are various things that should be in the output
    assert_list = [f"Updated derivation index: {index}"]
    cli_assert_shortcut(output, assert_list)
    expected_calls: logType = {
        "extend_derivation_index": [(index,)],
    }
    test_rpc_clients.wallet_rpc_client.check_log(expected_calls)


def test_add_token(capsys: object, get_test_cli_clients: Tuple[TestRpcClients, Path]) -> None:
    test_rpc_clients, root_dir = get_test_cli_clients

    # set RPC Client
    class AddTokenRpcClient(TestWalletRpcClient):
        async def create_wallet_for_existing_cat(self, asset_id: bytes) -> Dict[str, int]:
            self.add_to_log("create_wallet_for_existing_cat", (asset_id,))
            return {"wallet_id": 3}

        async def set_cat_name(self, wallet_id: int, name: str) -> None:
            self.add_to_log("set_cat_name", (wallet_id, name))
            return None  # we don't need to do anything here

    inst_rpc_client = AddTokenRpcClient()  # pylint: disable=no-value-for-parameter
    test_rpc_clients.wallet_rpc_client = inst_rpc_client
    command_args = ["wallet", "add_token", FINGERPRINT_ARG, "-nexamplecat"]
    success, output = run_cli_command(capsys, root_dir, command_args + ["--asset-id", bytes32([1] * 32).hex()])
    other_success, other_output = run_cli_command(
        capsys, root_dir, command_args + ["--asset-id", bytes32([3] * 32).hex()]
    )
    assert success and other_success
    # these are various things that should be in the output
    assert_list = [f"Successfully renamed test1 with wallet_id 2 on key {FINGERPRINT} to examplecat"]
    other_assert_list = [f"Successfully added examplecat with wallet id 3 on key {FINGERPRINT}"]
    cli_assert_shortcut(output, assert_list)
    cli_assert_shortcut(other_output, other_assert_list)
    expected_calls: logType = {
        "cat_asset_id_to_name": [(bytes32([1] * 32),), (bytes32([3] * 32),)],
        "create_wallet_for_existing_cat": [(bytes32([3] * 32),)],
        "set_cat_name": [(2, "examplecat"), (3, "examplecat")],
    }
    test_rpc_clients.wallet_rpc_client.check_log(expected_calls)


def test_make_offer(capsys: object, get_test_cli_clients: Tuple[TestRpcClients, Path]) -> None:
    test_rpc_clients, root_dir = get_test_cli_clients

    # set RPC Client
    class MakeOfferRpcClient(TestWalletRpcClient):
        async def create_offer_for_ids(
            self,
            offer_dict: Dict[Union[uint32, str], int],
            driver_dict: Optional[Dict[str, Any]] = None,
            solver: Optional[Dict[str, Any]] = None,
            fee: uint64 = uint64(0),
            validate_only: bool = False,
            min_coin_amount: uint64 = uint64(0),
            max_coin_amount: uint64 = uint64(0),
            reuse_puzhash: Optional[bool] = None,
        ) -> Tuple[Optional[Offer], TradeRecord]:
            self.add_to_log(
                "create_offer_for_ids",
                (offer_dict, driver_dict, solver, fee, validate_only, min_coin_amount, max_coin_amount, reuse_puzhash),
            )
            r_payments = {}
            for id, amount in offer_dict.items():
                if amount < 0:
                    if isinstance(id, uint32):
                        if id == 1:
                            asset_id = None
                        else:
                            asset_id = bytes32([id] * 32)
                    else:
                        asset_id = bytes32.from_hexstr(id)
                    r_payments[asset_id] = [NotarizedPayment(bytes32([1] * 32), uint64(abs(amount)), [])]
            assert driver_dict is not None
            c_driver_dict: Dict[bytes32, PuzzleInfo] = {bytes32([3] * 32): PuzzleInfo(list(driver_dict.values())[0])}
            created_offer: Offer = Offer(
                requested_payments=r_payments,
                _bundle=SpendBundle([], G2Element()),
                driver_dict=c_driver_dict,
            )
            trade_offer: TradeRecord = TradeRecord(
                confirmed_at_index=uint32(0),
                accepted_at_time=None,
                created_at_time=uint64(12345678),
                is_my_offer=True,
                sent=uint32(0),
                sent_to=[],
                offer=bytes(SpendBundle([], G2Element())),
                taken_offer=None,
                coins_of_interest=created_offer.get_involved_coins(),
                trade_id=bytes32([2] * 32),
                status=uint32(TradeStatus.PENDING_ACCEPT.value),
            )

            return created_offer, trade_offer

    inst_rpc_client = MakeOfferRpcClient()  # pylint: disable=no-value-for-parameter
    test_rpc_clients.wallet_rpc_client = inst_rpc_client
    request_cat_id = bytes32([2] * 32)
    request_nft_id = bytes32([2] * 32)
    request_nft_addr = encode_puzzle_hash(request_nft_id, "nft")
    # we offer xch and a random cat via wallet id and request a random cat, nft via coin and tail
    command_args = [
        "wallet",
        "make_offer",
        FINGERPRINT_ARG,
        "--reuse",
        "-m1",
        "--no-confirm",
        "--no-file",
        "--offer",
        "1:10",
        "--offer",
        "3:100",
        "--request",
        f"{request_cat_id.hex()}:10",
        "--request",
        f"{request_nft_addr}:1",
    ]
    success, output = run_cli_command(capsys, root_dir, command_args)
    assert success
    # these are various things that should be in the output
    assert_list = [
        "OFFERING:\n  - 10 XCH (10000000000000 mojos)\n  - 100 test3 (100000 mojos)",
        "REQUESTING:\n  - 10 test2 (10000 mojos)\n"
        "  - 1 nft1qgpqyqszqgpqyqszqgpqyqszqgpqyqszqgpqyqszqgpqyqszqgpqyql4ft (1 mojos)",
        "Including Fees: 1 XCH, 1000000000000 mojos",
        "Created offer with ID 0202020202020202020202020202020202020202020202020202020202020202",
    ]
    cli_assert_shortcut(output, assert_list)
    expected_calls: logType = {
        "cat_asset_id_to_name": [(request_cat_id,)],
        "get_nft_info": [(request_nft_id.hex(), True)],
        "get_cat_name": [(3,)],
        "nft_calculate_royalties": [
            (
                {
                    "nft1qgpqyqszqgpqyqszqgpqyqszqgpqyqszqgpqyqszqgpqyqszqgpqyql4ft": (
                        "xch1qvpsxqcrqvpsxqcrqvpsxqcrqvpsxqcrqvpsxqcrqvpsxqcrqvps82kgr2",
                        1000,
                    )
                },
                {"XCH": 10000000000000, "test3": 100000},
            )
        ],
        "create_offer_for_ids": [
            (
                {
                    1: -10000000000000,
                    3: -100000,
                    "0202020202020202020202020202020202020202020202020202020202020202": 10000,
                    "0101010101010101010101010101010101010101010101010101010101010101": 1,
                },
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
                1000000000000,
                False,
                0,
                0,
                True,
            )
        ],
    }
    test_rpc_clients.wallet_rpc_client.check_log(expected_calls)


def test_get_offers(capsys: object, get_test_cli_clients: Tuple[TestRpcClients, Path]) -> None:
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
        ) -> List[TradeRecord]:
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
            records: List[TradeRecord] = []
            for i in reversed(range(start, end - 1)):  # reversed to match the sort order
                trade_offer = TradeRecord(
                    confirmed_at_index=uint32(0),
                    accepted_at_time=None,
                    created_at_time=uint64(12345678 + i),
                    is_my_offer=True,
                    sent=uint32(0),
                    sent_to=[],
                    offer=bytes(SpendBundle([], G2Element())),
                    taken_offer=None,
                    coins_of_interest=[
                        Coin(bytes32([2 + i] * 32), bytes32([3 + i] * 32), uint64(1000)),
                        Coin(bytes32([4 + i] * 32), bytes32([5 + i] * 32), uint64(1000)),
                    ],
                    trade_id=bytes32([1 + i] * 32),
                    status=uint32(TradeStatus.PENDING_ACCEPT.value),
                )
                records.append(trade_offer)
            return records

    inst_rpc_client = GetOffersRpcClient()  # pylint: disable=no-value-for-parameter
    test_rpc_clients.wallet_rpc_client = inst_rpc_client
    command_args = [
        "wallet",
        "get_offers",
        FINGERPRINT_ARG,
        "--exclude-my-offers",
        "--exclude-taken-offers",
        "--include-completed",
        "--reverse",
    ]
    success, output = run_cli_command(capsys, root_dir, command_args)
    assert success
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
    cli_assert_shortcut(output, assert_list)
    expected_calls: logType = {"get_all_offers": [(0, 10, None, True, False, True, True, True)]}
    test_rpc_clients.wallet_rpc_client.check_log(expected_calls)


def test_take_offer(capsys: object, get_test_cli_clients: Tuple[TestRpcClients, Path]) -> None:
    test_rpc_clients, root_dir = get_test_cli_clients

    # set RPC Client
    class TakeOfferRpcClient(TestWalletRpcClient):
        async def take_offer(
            self,
            offer: Offer,
            solver: Optional[Dict[str, Any]] = None,
            fee: uint64 = uint64(0),
            min_coin_amount: uint64 = uint64(0),
            reuse_puzhash: Optional[bool] = None,
        ) -> TradeRecord:
            self.add_to_log("take_offer", (offer, solver, fee, min_coin_amount, reuse_puzhash))
            return TradeRecord(
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
            )

    inst_rpc_client = TakeOfferRpcClient()  # pylint: disable=no-value-for-parameter
    test_rpc_clients.wallet_rpc_client = inst_rpc_client
    command_args = ["wallet", "take_offer", test_offer_file_name, "--no-confirm", FINGERPRINT_ARG, "-m1", "--reuse"]
    success, output = run_cli_command(capsys, root_dir, command_args)
    assert success
    # these are various things that should be in the output
    cat1 = bytes32.from_hexstr("fd6a341ed39c05c31157d5bfea395a0e142398ced24deea1e82f836d7ec2909c")
    cat2 = bytes32.from_hexstr("dc59bcd60ce5fc9c93a5d3b11875486b03efb53a53da61e453f5cf61a7746860")
    assert_list = [
        "  OFFERED:\n"
        "    - XCH (Wallet ID: 1): 10.0 (10000000000000 mojos)\n"
        f"    - {cat1.hex()}: 100.0 (100000 mojos)",
        "  REQUESTED:\n"
        f"    - {cat2.hex()}: 10.0 (10000 mojos)\n"
        "    - accce8e1c71b56624f2ecaeff5af57eac41365080449904d0717bd333c04806d: 0.001 (1 mojo)",
        "Accepted offer with ID dfb7e8643376820ec995b0bcdb3fc1f764c16b814df5e074631263fcf1e00839",
    ]
    cli_assert_shortcut(output, assert_list)
    expected_calls: logType = {
        "cat_asset_id_to_name": [
            (cat1,),
            (cat2,),
            (bytes32.from_hexstr("accce8e1c71b56624f2ecaeff5af57eac41365080449904d0717bd333c04806d"),),
        ],
        "take_offer": [(Offer.from_bech32(test_offer_file_bech32), None, 1000000000000, uint64(0), None)],
    }
    test_rpc_clients.wallet_rpc_client.check_log(expected_calls)


def test_cancel_offer(capsys: object, get_test_cli_clients: Tuple[TestRpcClients, Path]) -> None:
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
            )

        async def cancel_offer(self, trade_id: bytes32, fee: uint64 = uint64(0), secure: bool = True) -> None:
            self.add_to_log("cancel_offer", (trade_id, fee, secure))
            return None

    inst_rpc_client = CancelOfferRpcClient()  # pylint: disable=no-value-for-parameter
    test_rpc_clients.wallet_rpc_client = inst_rpc_client
    command_args = ["wallet", "cancel_offer", FINGERPRINT_ARG, "--no-confirm", "-m1", "--id", test_offer_id]
    success, output = run_cli_command(capsys, root_dir, command_args)
    assert success
    # these are various things that should be in the output
    cat1 = bytes32.from_hexstr("fd6a341ed39c05c31157d5bfea395a0e142398ced24deea1e82f836d7ec2909c")
    cat2 = bytes32.from_hexstr("dc59bcd60ce5fc9c93a5d3b11875486b03efb53a53da61e453f5cf61a7746860")
    assert_list = [
        "  OFFERED:\n"
        "    - XCH (Wallet ID: 1): 10.0 (10000000000000 mojos)\n"
        f"    - {cat1.hex()}: 100.0 (100000 mojos)",
        "  REQUESTED:\n"
        f"    - {cat2.hex()}: 10.0 (10000 mojos)\n"
        "    - accce8e1c71b56624f2ecaeff5af57eac41365080449904d0717bd333c04806d: 0.001 (1 mojo)",
        "Cancelled offer with ID dfb7e8643376820ec995b0bcdb3fc1f764c16b814df5e074631263fcf1e00839",
    ]
    cli_assert_shortcut(output, assert_list)
    expected_calls: logType = {
        "get_offer": [(test_offer_id_bytes, True)],
        "cancel_offer": [(test_offer_id_bytes, 1000000000000, True)],
        "cat_asset_id_to_name": [
            (cat1,),
            (cat2,),
            (bytes32.from_hexstr("accce8e1c71b56624f2ecaeff5af57eac41365080449904d0717bd333c04806d"),),
            (cat1,),
        ],
    }
    test_rpc_clients.wallet_rpc_client.check_log(expected_calls)
