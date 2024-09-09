from __future__ import annotations

from pathlib import Path
from typing import List, Optional, Tuple, cast

from chia._tests.cmds.cmd_test_utils import TestRpcClients, TestWalletRpcClient, logType, run_cli_command_and_assert
from chia._tests.cmds.wallet.test_consts import FINGERPRINT, FINGERPRINT_ARG, get_bytes32
from chia.rpc.wallet_request_types import GetNotifications, GetNotificationsResponse
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.bech32m import encode_puzzle_hash
from chia.util.ints import uint32, uint64
from chia.wallet.conditions import ConditionValidTimes
from chia.wallet.notification_store import Notification
from chia.wallet.transaction_record import TransactionRecord

test_condition_valid_times: ConditionValidTimes = ConditionValidTimes(min_time=uint64(100), max_time=uint64(150))

# Notifications Commands


def test_notifications_send(capsys: object, get_test_cli_clients: Tuple[TestRpcClients, Path]) -> None:
    test_rpc_clients, root_dir = get_test_cli_clients

    # set RPC Client
    class NotificationsSendRpcClient(TestWalletRpcClient):
        async def send_notification(
            self,
            target: bytes32,
            msg: bytes,
            amount: uint64,
            fee: uint64 = uint64(0),
            push: bool = True,
            timelock_info: ConditionValidTimes = ConditionValidTimes(),
        ) -> TransactionRecord:
            self.add_to_log("send_notification", (target, msg, amount, fee, push, timelock_info))

            class FakeTransactionRecord:
                def __init__(self, name: str) -> None:
                    self.name = name

            return cast(TransactionRecord, FakeTransactionRecord(get_bytes32(2).hex()))

    inst_rpc_client = NotificationsSendRpcClient()  # pylint: disable=no-value-for-parameter
    test_rpc_clients.wallet_rpc_client = inst_rpc_client
    target_ph = get_bytes32(1)
    target_addr = encode_puzzle_hash(target_ph, "xch")
    msg = "test message"
    command_args = [
        "wallet",
        "notifications",
        "send",
        FINGERPRINT_ARG,
        "-m0.001",
        "-a0.00002",
        f"-t{target_addr}",
        f"-n{msg}",
        "--valid-at",
        "100",
        "--expires-at",
        "150",
    ]
    # these are various things that should be in the output
    assert_list = [
        "Notification sent successfully.",
        f"To get status, use command: chia wallet get_transaction -f {FINGERPRINT} -tx 0x{get_bytes32(2).hex()}",
    ]
    run_cli_command_and_assert(capsys, root_dir, command_args, assert_list)
    expected_calls: logType = {
        "send_notification": [(target_ph, bytes(msg, "utf8"), 20000000, 1000000000, True, test_condition_valid_times)],
    }
    test_rpc_clients.wallet_rpc_client.check_log(expected_calls)


def test_notifications_get(capsys: object, get_test_cli_clients: Tuple[TestRpcClients, Path]) -> None:
    test_rpc_clients, root_dir = get_test_cli_clients

    # set RPC Client
    class NotificationsGetRpcClient(TestWalletRpcClient):
        async def get_notifications(self, request: GetNotifications) -> GetNotificationsResponse:
            self.add_to_log("get_notifications", (request,))
            return GetNotificationsResponse(
                [Notification(get_bytes32(1), bytes("hello", "utf8"), uint64(1000000000), uint32(50))]
            )

    inst_rpc_client = NotificationsGetRpcClient()  # pylint: disable=no-value-for-parameter
    test_rpc_clients.wallet_rpc_client = inst_rpc_client
    target_ph = get_bytes32(1)
    command_args = [
        "wallet",
        "notifications",
        "get",
        FINGERPRINT_ARG,
        f"-i{target_ph}",
        "-s10",
        "-e10",
    ]
    # these are various things that should be in the output
    assert_list = [
        "ID: 0101010101010101010101010101010101010101010101010101010101010101",
        "message: hello",
        "amount: 1000000000",
    ]
    run_cli_command_and_assert(capsys, root_dir, command_args, assert_list)
    expected_calls: logType = {"get_notifications": [(GetNotifications([get_bytes32(1)], uint32(10), uint32(10)),)]}
    test_rpc_clients.wallet_rpc_client.check_log(expected_calls)


def test_notifications_delete(capsys: object, get_test_cli_clients: Tuple[TestRpcClients, Path]) -> None:
    test_rpc_clients, root_dir = get_test_cli_clients

    # set RPC Client
    class NotificationsDeleteRpcClient(TestWalletRpcClient):
        async def delete_notifications(self, ids: Optional[List[bytes32]] = None) -> bool:
            self.add_to_log("delete_notifications", (ids,))
            return True

    inst_rpc_client = NotificationsDeleteRpcClient()  # pylint: disable=no-value-for-parameter
    test_rpc_clients.wallet_rpc_client = inst_rpc_client
    command_args = ["wallet", "notifications", "delete", FINGERPRINT_ARG, "--all"]
    # these are various things that should be in the output
    assert_list = ["Success: True"]
    run_cli_command_and_assert(capsys, root_dir, command_args, assert_list)
    expected_calls: logType = {"delete_notifications": [(None,)]}
    test_rpc_clients.wallet_rpc_client.check_log(expected_calls)
