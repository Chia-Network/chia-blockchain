from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

from chia.types.blockchain_format.sized_bytes import bytes48
from chia.types.signing_mode import SigningMode
from chia.util.bech32m import encode_puzzle_hash
from tests.cmds.cmd_test_utils import TestRpcClients, TestWalletRpcClient, logType, run_cli_command_and_assert
from tests.cmds.wallet.test_consts import FINGERPRINT_ARG, get_bytes32

# DID Commands


def test_did_create(capsys: object, get_test_cli_clients: Tuple[TestRpcClients, Path]) -> None:
    test_rpc_clients, root_dir = get_test_cli_clients

    # set RPC Client
    class DidCreateRpcClient(TestWalletRpcClient):
        async def create_new_did_wallet(
            self,
            amount: int,
            fee: int = 0,
            name: Optional[str] = "DID Wallet",
            backup_ids: Optional[List[str]] = None,
            required_num: int = 0,
        ) -> Dict[str, Union[str, int]]:
            if backup_ids is None:
                backup_ids = []
            self.add_to_log("create_new_did_wallet", (amount, fee, name, backup_ids, required_num))
            return {"wallet_id": 3, "my_did": "did:chia:testdid123456"}

    inst_rpc_client = DidCreateRpcClient()  # pylint: disable=no-value-for-parameter
    test_rpc_clients.wallet_rpc_client = inst_rpc_client
    command_args = ["wallet", "did", "create", FINGERPRINT_ARG, "-ntest", "-a3", "-m0.1"]
    # these are various things that should be in the output
    assert_list = [
        "Successfully created a DID wallet with name test and id 3 on key 123456",
        "Successfully created a DID did:chia:testdid123456 in the newly created DID wallet",
    ]
    run_cli_command_and_assert(capsys, root_dir, command_args, assert_list)
    expected_calls: logType = {
        "create_new_did_wallet": [(3, 100000000000, "test", [], 0)],
    }
    test_rpc_clients.wallet_rpc_client.check_log(expected_calls)


def test_did_sign_message(capsys: object, get_test_cli_clients: Tuple[TestRpcClients, Path]) -> None:
    test_rpc_clients, root_dir = get_test_cli_clients

    # set RPC Client
    inst_rpc_client = TestWalletRpcClient()  # pylint: disable=no-value-for-parameter
    test_rpc_clients.wallet_rpc_client = inst_rpc_client
    did_id = encode_puzzle_hash(get_bytes32(1), "did:chia:")
    message = b"hello did world!!"
    command_args = ["wallet", "did", "sign_message", FINGERPRINT_ARG, f"-m{message.hex()}"]
    # these are various things that should be in the output
    assert_list = [
        f"Message: {message.hex()}",
        f"Public Key: {bytes([4] * 48).hex()}",
        f"Signature: {bytes([7] * 576).hex()}",
        f"Signing Mode: {SigningMode.CHIP_0002.value}",
    ]
    run_cli_command_and_assert(capsys, root_dir, command_args + [f"-i{did_id}"], assert_list)
    expected_calls: logType = {
        "sign_message_by_id": [(did_id, message.hex())],  # xch std
    }
    test_rpc_clients.wallet_rpc_client.check_log(expected_calls)


def test_did_set_name(capsys: object, get_test_cli_clients: Tuple[TestRpcClients, Path]) -> None:
    test_rpc_clients, root_dir = get_test_cli_clients

    # set RPC Client
    class DidSetNameRpcClient(TestWalletRpcClient):
        async def did_set_wallet_name(self, wallet_id: int, name: str) -> Dict[str, Union[str, int]]:
            self.add_to_log("did_set_wallet_name", (wallet_id, name))
            return {}

    inst_rpc_client = DidSetNameRpcClient()  # pylint: disable=no-value-for-parameter
    test_rpc_clients.wallet_rpc_client = inst_rpc_client
    w_id = 3
    did_name = "testdid"
    command_args = ["wallet", "did", "set_name", FINGERPRINT_ARG, f"-i{w_id}", f"-n{did_name}"]
    # these are various things that should be in the output
    assert_list = [f"Successfully set a new name for DID wallet with id {w_id}: {did_name}"]
    run_cli_command_and_assert(capsys, root_dir, command_args, assert_list)
    expected_calls: logType = {
        "did_set_wallet_name": [(w_id, did_name)],
    }
    test_rpc_clients.wallet_rpc_client.check_log(expected_calls)


def test_did_get_did(capsys: object, get_test_cli_clients: Tuple[TestRpcClients, Path]) -> None:
    test_rpc_clients, root_dir = get_test_cli_clients

    # set RPC Client
    class DidGetDidRpcClient(TestWalletRpcClient):
        async def get_did_id(self, wallet_id: int) -> Dict[str, str]:
            self.add_to_log("get_did_id", (wallet_id,))
            return {"my_did": encode_puzzle_hash(get_bytes32(1), "did:chia:"), "coin_id": get_bytes32(2).hex()}

    inst_rpc_client = DidGetDidRpcClient()  # pylint: disable=no-value-for-parameter
    test_rpc_clients.wallet_rpc_client = inst_rpc_client
    w_id = 3
    expected_did = encode_puzzle_hash(get_bytes32(1), "did:chia:")
    command_args = ["wallet", "did", "get_did", FINGERPRINT_ARG, f"-i{w_id}"]
    # these are various things that should be in the output
    assert_list = [f"DID:                    {expected_did}", f"Coin ID:                {get_bytes32(2)}"]
    run_cli_command_and_assert(capsys, root_dir, command_args, assert_list)
    expected_calls: logType = {
        "get_did_id": [(w_id,)],
    }
    test_rpc_clients.wallet_rpc_client.check_log(expected_calls)


def test_did_get_details(capsys: object, get_test_cli_clients: Tuple[TestRpcClients, Path]) -> None:
    test_rpc_clients, root_dir = get_test_cli_clients

    # set RPC Client
    class DidGetDetailsRpcClient(TestWalletRpcClient):
        async def get_did_info(self, coin_id: str, latest: bool) -> Dict[str, object]:
            self.add_to_log("get_did_info", (coin_id, latest))
            response = {
                "did_id": encode_puzzle_hash(get_bytes32(2), "did:chia:"),
                "latest_coin": get_bytes32(3).hex(),
                "p2_address": encode_puzzle_hash(get_bytes32(4), "xch"),
                "public_key": bytes48([5] * 48).hex(),
                "launcher_id": get_bytes32(6).hex(),
                "metadata": "did metadata",
                "recovery_list_hash": get_bytes32(7).hex(),
                "num_verification": 8,
                "full_puzzle": get_bytes32(9).hex(),
                "solution": get_bytes32(10).hex(),
                "hints": [get_bytes32(11).hex(), get_bytes32(12).hex()],
            }
            return response

    inst_rpc_client = DidGetDetailsRpcClient()  # pylint: disable=no-value-for-parameter
    test_rpc_clients.wallet_rpc_client = inst_rpc_client
    did_coin_id_hex = get_bytes32(1).hex()
    command_args = ["wallet", "did", "get_details", FINGERPRINT_ARG, "--coin_id", did_coin_id_hex]
    # these are various things that should be in the output
    assert_list = [
        f"DID:                    {encode_puzzle_hash(get_bytes32(2), 'did:chia:')}",
        f"Coin ID:                {get_bytes32(3).hex()}",
        "Inner P2 Address:       xch1qszqgpqyqszqgpqyqszqgpqyqszqgpqyqszqgpqyqszqgpqyqszqkxck8d",
        f"Public Key:             {bytes48([5] * 48).hex()}",
        f"Launcher ID:            {get_bytes32(6).hex()}",
        "DID Metadata:           did metadata",
        f"Recovery List Hash:     {get_bytes32(7).hex()}",
        "Recovery Required Verifications: 8",
        f"Last Spend Puzzle:      {get_bytes32(9).hex()}",
        "Last Spend Solution:    0a0a0a0a0a0a0a0a0a0a0a0a0a0a0a0a0a0a0a0a0a0a0a0a0a0a0a0a0a0a0a0a",
        "Last Spend Hints:       ['0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b', "
        "'0c0c0c0c0c0c0c0c0c0c0c0c0c0c0c0c0c0c0c0c0c0c0c0c0c0c0c0c0c0c0c0c']",
    ]
    run_cli_command_and_assert(capsys, root_dir, command_args, assert_list)
    expected_calls: logType = {
        "get_did_info": [(did_coin_id_hex, True)],
    }
    test_rpc_clients.wallet_rpc_client.check_log(expected_calls)


def test_did_update_metadata(capsys: object, get_test_cli_clients: Tuple[TestRpcClients, Path]) -> None:
    test_rpc_clients, root_dir = get_test_cli_clients

    # set RPC Client
    class DidUpdateMetadataRpcClient(TestWalletRpcClient):
        async def update_did_metadata(
            self,
            wallet_id: int,
            metadata: Dict[str, object],
            reuse_puzhash: Optional[bool] = None,
        ) -> Dict[str, object]:
            self.add_to_log("update_did_metadata", (wallet_id, metadata, reuse_puzhash))
            return {"wallet_id": wallet_id, "spend_bundle": "spend bundle here"}

    inst_rpc_client = DidUpdateMetadataRpcClient()  # pylint: disable=no-value-for-parameter
    test_rpc_clients.wallet_rpc_client = inst_rpc_client
    w_id = 3
    json_mdata = '{"test": true}'
    command_args = [
        "wallet",
        "did",
        "update_metadata",
        FINGERPRINT_ARG,
        f"-i{w_id}",
        "--metadata",
        json_mdata,
        "--reuse",
    ]
    # these are various things that should be in the output
    assert_list = [f"Successfully updated DID wallet ID: {w_id}, Spend Bundle: spend bundle here"]
    run_cli_command_and_assert(capsys, root_dir, command_args, assert_list)
    expected_calls: logType = {
        "update_did_metadata": [(w_id, {"test": True}, True)],
    }
    test_rpc_clients.wallet_rpc_client.check_log(expected_calls)


def test_did_find_lost(capsys: object, get_test_cli_clients: Tuple[TestRpcClients, Path]) -> None:
    test_rpc_clients, root_dir = get_test_cli_clients

    # set RPC Client
    class DidFindLostRpcClient(TestWalletRpcClient):
        async def find_lost_did(
            self,
            coin_id: str,
            recovery_list_hash: Optional[str],
            metadata: Optional[Dict[str, object]],
            num_verification: Optional[int],
        ) -> Dict[str, Union[bool, str]]:
            self.add_to_log("find_lost_did", (coin_id, recovery_list_hash, metadata, num_verification))
            return {"success": True, "latest_coin_id": get_bytes32(2).hex()}

    inst_rpc_client = DidFindLostRpcClient()  # pylint: disable=no-value-for-parameter
    test_rpc_clients.wallet_rpc_client = inst_rpc_client
    c_id = get_bytes32(1)
    json_mdata = '{"test": true}'
    command_args = [
        "wallet",
        "did",
        "find_lost",
        FINGERPRINT_ARG,
        "--coin_id",
        c_id.hex(),
        "--metadata",
        json_mdata,
    ]
    # these are various things that should be in the output
    assert_list = [f"Successfully found lost DID {c_id.hex()}, latest coin ID: {get_bytes32(2).hex()}"]
    run_cli_command_and_assert(capsys, root_dir, command_args, assert_list)
    expected_calls: logType = {
        "find_lost_did": [(c_id.hex(), None, json_mdata, None)],
    }
    test_rpc_clients.wallet_rpc_client.check_log(expected_calls)


def test_did_message_spend(capsys: object, get_test_cli_clients: Tuple[TestRpcClients, Path]) -> None:
    test_rpc_clients, root_dir = get_test_cli_clients

    # set RPC Client
    class DidMessageSpendRpcClient(TestWalletRpcClient):
        async def did_message_spend(
            self, wallet_id: int, puzzle_announcements: List[str], coin_announcements: List[str]
        ) -> Dict[str, object]:
            self.add_to_log("did_message_spend", (wallet_id, puzzle_announcements, coin_announcements))
            return {"spend_bundle": "spend bundle here"}

    inst_rpc_client = DidMessageSpendRpcClient()  # pylint: disable=no-value-for-parameter
    test_rpc_clients.wallet_rpc_client = inst_rpc_client
    w_id = 3
    c_announcements = [get_bytes32(1), get_bytes32(2)]
    puz_announcements = [get_bytes32(3), get_bytes32(4)]
    command_args = [
        "wallet",
        "did",
        "message_spend",
        FINGERPRINT_ARG,
        f"-i{w_id}",
        "--coin_announcements",
        ",".join([announcement.hex() for announcement in c_announcements]),
        "--puzzle_announcements",
        ",".join([announcement.hex() for announcement in puz_announcements]),
    ]
    # these are various things that should be in the output
    assert_list = ["Message Spend Bundle: spend bundle here"]
    run_cli_command_and_assert(capsys, root_dir, command_args, assert_list)
    expected_calls: logType = {
        "did_message_spend": [
            (
                w_id,
                [announcement.hex() for announcement in puz_announcements],
                [announcement.hex() for announcement in c_announcements],
            )
        ],
    }
    test_rpc_clients.wallet_rpc_client.check_log(expected_calls)


def test_did_transfer(capsys: object, get_test_cli_clients: Tuple[TestRpcClients, Path]) -> None:
    test_rpc_clients, root_dir = get_test_cli_clients

    # set RPC Client
    class DidTransferRpcClient(TestWalletRpcClient):
        async def did_transfer_did(
            self,
            wallet_id: int,
            address: str,
            fee: int,
            with_recovery: bool,
            reuse_puzhash: Optional[bool] = None,
        ) -> Dict[str, object]:
            self.add_to_log("did_transfer_did", (wallet_id, address, fee, with_recovery, reuse_puzhash))
            return {"transaction_id": get_bytes32(2).hex(), "transaction": "transaction here"}

    inst_rpc_client = DidTransferRpcClient()  # pylint: disable=no-value-for-parameter
    test_rpc_clients.wallet_rpc_client = inst_rpc_client
    w_id = 3
    t_address = encode_puzzle_hash(get_bytes32(1), "xch")
    command_args = [
        "wallet",
        "did",
        "transfer",
        FINGERPRINT_ARG,
        f"-i{w_id}",
        "-m0.5",
        "--reuse",
        "--target-address",
        t_address,
    ]
    # these are various things that should be in the output
    assert_list = [
        f"Successfully transferred DID to {t_address}",
        f"Transaction ID: {get_bytes32(2).hex()}",
        "Transaction: transaction here",
    ]
    run_cli_command_and_assert(capsys, root_dir, command_args, assert_list)
    expected_calls: logType = {
        "did_transfer_did": [(w_id, t_address, "0.5", True, True)],
    }
    test_rpc_clients.wallet_rpc_client.check_log(expected_calls)
