from __future__ import annotations

from pathlib import Path
from typing import Optional, Union

import pytest
from chia_rs import G2Element
from chia_rs.sized_bytes import bytes32, bytes48
from chia_rs.sized_ints import uint16, uint32, uint64

from chia._tests.cmds.cmd_test_utils import TestRpcClients, TestWalletRpcClient, logType, run_cli_command_and_assert
from chia._tests.cmds.wallet.test_consts import FINGERPRINT_ARG, STD_TX, STD_UTX, get_bytes32
from chia.types.blockchain_format.program import NIL, Program
from chia.types.signing_mode import SigningMode
from chia.util.bech32m import encode_puzzle_hash
from chia.util.config import load_config
from chia.wallet.conditions import Condition, ConditionValidTimes, CreateCoinAnnouncement, CreatePuzzleAnnouncement
from chia.wallet.did_wallet.did_info import did_recovery_is_nil
from chia.wallet.util.curry_and_treehash import NIL_TREEHASH
from chia.wallet.util.tx_config import DEFAULT_TX_CONFIG, TXConfig
from chia.wallet.wallet_request_types import (
    DIDFindLostDID,
    DIDFindLostDIDResponse,
    DIDGetDID,
    DIDGetDIDResponse,
    DIDGetInfo,
    DIDGetInfoResponse,
    DIDMessageSpend,
    DIDMessageSpendResponse,
    DIDSetWalletName,
    DIDSetWalletNameResponse,
    DIDTransferDID,
    DIDTransferDIDResponse,
    DIDUpdateMetadata,
    DIDUpdateMetadataResponse,
)
from chia.wallet.wallet_spend_bundle import WalletSpendBundle

test_condition_valid_times: ConditionValidTimes = ConditionValidTimes(min_time=uint64(100), max_time=uint64(150))


@pytest.mark.parametrize(
    argnames=["program", "result"],
    argvalues=[
        (Program.to(NIL_TREEHASH), True),
        (NIL, True),
        (Program.to(bytes32([1] * 32)), False),
    ],
)
def test_did_recovery_is_nil(program: Program, result: bool) -> None:
    # test that the alternate wallet nil recovery list bytes are used
    assert did_recovery_is_nil(program) is result


# DID Commands
def test_did_create(capsys: object, get_test_cli_clients: tuple[TestRpcClients, Path]) -> None:
    test_rpc_clients, root_dir = get_test_cli_clients

    # set RPC Client
    class DidCreateRpcClient(TestWalletRpcClient):
        async def create_new_did_wallet(
            self,
            amount: int,
            tx_config: TXConfig,
            fee: int = 0,
            name: Optional[str] = "DID Wallet",
            backup_ids: Optional[list[str]] = None,
            required_num: int = 0,
            push: bool = True,
            timelock_info: ConditionValidTimes = ConditionValidTimes(),
        ) -> dict[str, Union[str, int]]:
            if backup_ids is None:
                backup_ids = []
            self.add_to_log(
                "create_new_did_wallet", (amount, tx_config, fee, name, backup_ids, required_num, push, timelock_info)
            )
            return {"wallet_id": 3, "my_did": "did:chia:testdid123456"}

    inst_rpc_client = DidCreateRpcClient()
    test_rpc_clients.wallet_rpc_client = inst_rpc_client
    command_args = [
        "wallet",
        "did",
        "create",
        FINGERPRINT_ARG,
        "-ntest",
        "-a3",
        "-m0.1",
        "--valid-at",
        "100",
        "--expires-at",
        "150",
    ]
    # these are various things that should be in the output
    assert_list = [
        "Successfully created a DID wallet with name test and id 3 on key 123456",
        "Successfully created a DID did:chia:testdid123456 in the newly created DID wallet",
    ]
    run_cli_command_and_assert(capsys, root_dir, command_args, assert_list)
    expected_calls: logType = {
        "create_new_did_wallet": [
            (3, DEFAULT_TX_CONFIG, 100000000000, "test", [], 0, True, test_condition_valid_times)
        ],
    }
    test_rpc_clients.wallet_rpc_client.check_log(expected_calls)


def test_did_sign_message(capsys: object, get_test_cli_clients: tuple[TestRpcClients, Path]) -> None:
    test_rpc_clients, root_dir = get_test_cli_clients

    # set RPC Client
    inst_rpc_client = TestWalletRpcClient()
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
    run_cli_command_and_assert(capsys, root_dir, [*command_args, f"-i{did_id}"], assert_list)
    expected_calls: logType = {
        "sign_message_by_id": [(did_id, message.hex())],  # xch std
    }
    test_rpc_clients.wallet_rpc_client.check_log(expected_calls)


def test_did_set_name(capsys: object, get_test_cli_clients: tuple[TestRpcClients, Path]) -> None:
    test_rpc_clients, root_dir = get_test_cli_clients

    # set RPC Client
    class DidSetNameRpcClient(TestWalletRpcClient):
        async def did_set_wallet_name(self, request: DIDSetWalletName) -> DIDSetWalletNameResponse:
            self.add_to_log("did_set_wallet_name", (request.wallet_id, request.name))
            return DIDSetWalletNameResponse(request.wallet_id)

    inst_rpc_client = DidSetNameRpcClient()
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


def test_did_get_did(capsys: object, get_test_cli_clients: tuple[TestRpcClients, Path]) -> None:
    test_rpc_clients, root_dir = get_test_cli_clients

    # set RPC Client
    class DidGetDidRpcClient(TestWalletRpcClient):
        async def get_did_id(self, request: DIDGetDID) -> DIDGetDIDResponse:
            self.add_to_log("get_did_id", (request.wallet_id,))
            return DIDGetDIDResponse(
                wallet_id=request.wallet_id,
                my_did=encode_puzzle_hash(get_bytes32(1), "did:chia:"),
                coin_id=get_bytes32(2),
            )

    inst_rpc_client = DidGetDidRpcClient()
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


def test_did_get_details(capsys: object, get_test_cli_clients: tuple[TestRpcClients, Path]) -> None:
    test_rpc_clients, root_dir = get_test_cli_clients

    # set RPC Client
    class DidGetDetailsRpcClient(TestWalletRpcClient):
        async def get_did_info(self, request: DIDGetInfo) -> DIDGetInfoResponse:
            self.add_to_log("get_did_info", (request.coin_id, request.latest))
            response = DIDGetInfoResponse(
                did_id=encode_puzzle_hash(get_bytes32(2), "did:chia:"),
                latest_coin=get_bytes32(3),
                p2_address=encode_puzzle_hash(get_bytes32(4), "xch"),
                public_key=bytes48([5] * 48),
                launcher_id=get_bytes32(6),
                metadata={"did metadata": "yes"},
                recovery_list_hash=get_bytes32(7),
                num_verification=uint16(8),
                full_puzzle=Program.to(9),
                solution=Program.to(10),
                hints=[get_bytes32(11), get_bytes32(12)],
            )
            return response

    inst_rpc_client = DidGetDetailsRpcClient()
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
        "DID Metadata:           {'did metadata': 'yes'}",
        f"Recovery List Hash:     {get_bytes32(7).hex()}",
        "Recovery Required Verifications: 8",
        "Last Spend Puzzle:      09",
        "Last Spend Solution:    0a",
        "Last Spend Hints:       ['0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b', "
        "'0c0c0c0c0c0c0c0c0c0c0c0c0c0c0c0c0c0c0c0c0c0c0c0c0c0c0c0c0c0c0c0c']",
    ]
    run_cli_command_and_assert(capsys, root_dir, command_args, assert_list)
    expected_calls: logType = {
        "get_did_info": [(did_coin_id_hex, True)],
    }
    test_rpc_clients.wallet_rpc_client.check_log(expected_calls)


def test_did_update_metadata(capsys: object, get_test_cli_clients: tuple[TestRpcClients, Path]) -> None:
    test_rpc_clients, root_dir = get_test_cli_clients

    # set RPC Client
    class DidUpdateMetadataRpcClient(TestWalletRpcClient):
        async def update_did_metadata(
            self,
            request: DIDUpdateMetadata,
            tx_config: TXConfig,
            extra_conditions: tuple[Condition, ...] = tuple(),
            timelock_info: ConditionValidTimes = ConditionValidTimes(),
        ) -> DIDUpdateMetadataResponse:
            self.add_to_log(
                "update_did_metadata",
                (request.wallet_id, request.metadata, tx_config, request.push, extra_conditions, timelock_info),
            )
            return DIDUpdateMetadataResponse(
                [STD_UTX], [STD_TX], WalletSpendBundle([], G2Element()), uint32(request.wallet_id)
            )

    inst_rpc_client = DidUpdateMetadataRpcClient()
    test_rpc_clients.wallet_rpc_client = inst_rpc_client
    w_id = 3
    json_mdata = '{"foo": "bar"}'
    command_args = [
        "wallet",
        "did",
        "update_metadata",
        FINGERPRINT_ARG,
        f"-i{w_id}",
        "--metadata",
        json_mdata,
        "--reuse",
        "--valid-at",
        "100",
        "--expires-at",
        "150",
    ]
    # these are various things that should be in the output
    assert STD_TX.spend_bundle is not None
    assert_list = [f"Successfully updated DID wallet ID: {w_id}, Spend Bundle: {STD_TX.spend_bundle.to_json_dict()}"]
    run_cli_command_and_assert(capsys, root_dir, command_args, assert_list)
    expected_calls: logType = {
        "update_did_metadata": [
            (w_id, {"foo": "bar"}, DEFAULT_TX_CONFIG.override(reuse_puzhash=True), True, (), test_condition_valid_times)
        ],
    }
    test_rpc_clients.wallet_rpc_client.check_log(expected_calls)


def test_did_find_lost(capsys: object, get_test_cli_clients: tuple[TestRpcClients, Path]) -> None:
    test_rpc_clients, root_dir = get_test_cli_clients

    # set RPC Client
    class DidFindLostRpcClient(TestWalletRpcClient):
        async def find_lost_did(self, request: DIDFindLostDID) -> DIDFindLostDIDResponse:
            self.add_to_log(
                "find_lost_did",
                (request.coin_id, request.recovery_list_hash, request.metadata, request.num_verification),
            )
            return DIDFindLostDIDResponse(get_bytes32(2))

    inst_rpc_client = DidFindLostRpcClient()
    test_rpc_clients.wallet_rpc_client = inst_rpc_client
    c_id = get_bytes32(1)
    json_mdata = '{"foo": "bar"}'
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
        "find_lost_did": [(c_id.hex(), None, {"foo": "bar"}, None)],
    }
    test_rpc_clients.wallet_rpc_client.check_log(expected_calls)


def test_did_message_spend(capsys: object, get_test_cli_clients: tuple[TestRpcClients, Path]) -> None:
    test_rpc_clients, root_dir = get_test_cli_clients

    # set RPC Client
    class DidMessageSpendRpcClient(TestWalletRpcClient):
        async def did_message_spend(
            self,
            request: DIDMessageSpend,
            tx_config: TXConfig,
            extra_conditions: tuple[Condition, ...] = tuple(),
            timelock_info: ConditionValidTimes = ConditionValidTimes(),
        ) -> DIDMessageSpendResponse:
            self.add_to_log(
                "did_message_spend", (request.wallet_id, tx_config, extra_conditions, request.push, timelock_info)
            )
            return DIDMessageSpendResponse([STD_UTX], [STD_TX], WalletSpendBundle([], G2Element()))

    inst_rpc_client = DidMessageSpendRpcClient()
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
        "--valid-at",
        "100",
        "--expires-at",
        "150",
    ]
    # these are various things that should be in the output
    assert STD_TX.spend_bundle is not None
    assert_list = [f"Message Spend Bundle: {STD_TX.spend_bundle.to_json_dict()}"]
    run_cli_command_and_assert(capsys, root_dir, command_args, assert_list)
    expected_calls: logType = {
        "did_message_spend": [
            (
                w_id,
                DEFAULT_TX_CONFIG,
                (
                    *(CreateCoinAnnouncement(ann) for ann in c_announcements),
                    *(CreatePuzzleAnnouncement(ann) for ann in puz_announcements),
                ),
                True,
                test_condition_valid_times,
            )
        ],
    }
    test_rpc_clients.wallet_rpc_client.check_log(expected_calls)


def test_did_transfer(capsys: object, get_test_cli_clients: tuple[TestRpcClients, Path]) -> None:
    test_rpc_clients, root_dir = get_test_cli_clients

    # set RPC Client
    class DidTransferRpcClient(TestWalletRpcClient):
        async def did_transfer_did(
            self,
            request: DIDTransferDID,
            tx_config: TXConfig,
            extra_conditions: tuple[Condition, ...] = tuple(),
            timelock_info: ConditionValidTimes = ConditionValidTimes(),
        ) -> DIDTransferDIDResponse:
            self.add_to_log(
                "did_transfer_did",
                (
                    request.wallet_id,
                    request.inner_address,
                    request.fee,
                    request.with_recovery_info,
                    tx_config,
                    request.push,
                    extra_conditions,
                    timelock_info,
                ),
            )
            return DIDTransferDIDResponse(
                [STD_UTX],
                [STD_TX],
                STD_TX,
                STD_TX.name,
            )

    inst_rpc_client = DidTransferRpcClient()
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
        "--valid-at",
        "100",
        "--expires-at",
        "150",
    ]
    # these are various things that should be in the output
    config = load_config(
        root_dir,
        "config.yaml",
    )
    assert_list = [
        f"Successfully transferred DID to {t_address}",
        f"Transaction ID: {get_bytes32(2).hex()}",
        f"Transaction: {STD_TX.to_json_dict_convenience(config)}",
    ]
    run_cli_command_and_assert(capsys, root_dir, command_args, assert_list)
    expected_calls: logType = {
        "did_transfer_did": [
            (
                w_id,
                t_address,
                500000000000,
                True,
                DEFAULT_TX_CONFIG.override(reuse_puzhash=True),
                True,
                (),
                test_condition_valid_times,
            )
        ],
    }
    test_rpc_clients.wallet_rpc_client.check_log(expected_calls)
