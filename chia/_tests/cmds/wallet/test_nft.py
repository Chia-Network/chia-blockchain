from __future__ import annotations

from pathlib import Path
from typing import Any, List, Optional, Tuple

from chia_rs import G2Element

from chia._tests.cmds.cmd_test_utils import TestRpcClients, TestWalletRpcClient, logType, run_cli_command_and_assert
from chia._tests.cmds.wallet.test_consts import FINGERPRINT, FINGERPRINT_ARG, STD_TX, STD_UTX, get_bytes32
from chia.rpc.wallet_request_types import (
    NFTAddURIResponse,
    NFTMintNFTResponse,
    NFTSetNFTDIDResponse,
    NFTTransferNFTResponse,
)
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.signing_mode import SigningMode
from chia.util.bech32m import encode_puzzle_hash
from chia.util.ints import uint8, uint16, uint32, uint64
from chia.wallet.conditions import ConditionValidTimes
from chia.wallet.nft_wallet.nft_info import NFTInfo
from chia.wallet.util.tx_config import DEFAULT_TX_CONFIG, TXConfig
from chia.wallet.wallet_spend_bundle import WalletSpendBundle

test_condition_valid_times: ConditionValidTimes = ConditionValidTimes(min_time=uint64(100), max_time=uint64(150))

# NFT Commands


def test_nft_create(capsys: object, get_test_cli_clients: Tuple[TestRpcClients, Path]) -> None:
    test_rpc_clients, root_dir = get_test_cli_clients

    # set RPC Client
    class NFTCreateRpcClient(TestWalletRpcClient):
        async def create_new_nft_wallet(self, did_id: str, name: Optional[str] = None) -> dict[str, Any]:
            self.add_to_log("create_new_nft_wallet", (did_id, name))
            return {"wallet_id": 4}

    inst_rpc_client = NFTCreateRpcClient()  # pylint: disable=no-value-for-parameter
    did_id = encode_puzzle_hash(get_bytes32(2), "did:chia:")
    test_rpc_clients.wallet_rpc_client = inst_rpc_client
    command_args = ["wallet", "nft", "create", FINGERPRINT_ARG, "-ntest", "--did-id", did_id]
    # these are various things that should be in the output
    assert_list = [f"Successfully created an NFT wallet with id 4 on key {FINGERPRINT}"]
    run_cli_command_and_assert(capsys, root_dir, command_args, assert_list)
    expected_calls: logType = {
        "create_new_nft_wallet": [(did_id, "test")],
    }
    test_rpc_clients.wallet_rpc_client.check_log(expected_calls)


def test_nft_sign_message(capsys: object, get_test_cli_clients: Tuple[TestRpcClients, Path]) -> None:
    test_rpc_clients, root_dir = get_test_cli_clients

    # set RPC Client

    inst_rpc_client = TestWalletRpcClient()  # pylint: disable=no-value-for-parameter
    test_rpc_clients.wallet_rpc_client = inst_rpc_client
    did_id = encode_puzzle_hash(get_bytes32(1), "nft")
    message = b"hello nft world!!"
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


def test_nft_mint(capsys: object, get_test_cli_clients: Tuple[TestRpcClients, Path]) -> None:
    test_rpc_clients, root_dir = get_test_cli_clients

    # set RPC Client
    class NFTCreateRpcClient(TestWalletRpcClient):
        async def get_nft_wallet_did(self, wallet_id: uint8) -> dict[str, Optional[str]]:
            self.add_to_log("get_nft_wallet_did", (wallet_id,))
            return {"did_id": "0xcee228b8638c67cb66a55085be99fa3b457ae5b56915896f581990f600b2c652"}

        async def mint_nft(
            self,
            wallet_id: int,
            royalty_address: Optional[str],
            target_address: Optional[str],
            hash: str,
            uris: List[str],
            meta_hash: str = "",
            meta_uris: Optional[List[str]] = None,
            license_hash: str = "",
            license_uris: Optional[List[str]] = None,
            edition_total: uint8 = uint8(1),
            edition_number: uint8 = uint8(1),
            fee: uint64 = uint64(0),
            royalty_percentage: int = 0,
            did_id: Optional[str] = None,
            reuse_puzhash: Optional[bool] = None,
            push: bool = True,
            timelock_info: ConditionValidTimes = ConditionValidTimes(),
        ) -> NFTMintNFTResponse:
            self.add_to_log(
                "mint_nft",
                (
                    wallet_id,
                    royalty_address,
                    target_address,
                    hash,
                    uris,
                    meta_hash,
                    meta_uris,
                    license_hash,
                    license_uris,
                    edition_total,
                    edition_number,
                    fee,
                    royalty_percentage,
                    did_id,
                    reuse_puzhash,
                    push,
                    timelock_info,
                ),
            )
            return NFTMintNFTResponse(
                [STD_UTX],
                [STD_TX],
                uint32(wallet_id),
                WalletSpendBundle([], G2Element()),
                bytes32([0] * 32).hex(),
            )

    inst_rpc_client = NFTCreateRpcClient()  # pylint: disable=no-value-for-parameter
    target_addr = encode_puzzle_hash(get_bytes32(2), "xch")
    test_rpc_clients.wallet_rpc_client = inst_rpc_client
    command_args = [
        "wallet",
        "nft",
        "mint",
        FINGERPRINT_ARG,
        "-i4",
        "--hash",
        "0x1234",
        "--uris",
        "https://example.com",
        "--target-address",
        target_addr,
        "-m0.5",
        "--reuse",
        "--valid-at",
        "100",
        "--expires-at",
        "150",
    ]
    # these are various things that should be in the output
    assert_list = [f"NFT minted Successfully with spend bundle: {STD_TX.spend_bundle}"]
    run_cli_command_and_assert(capsys, root_dir, command_args, assert_list)
    expected_calls: logType = {
        "get_nft_wallet_did": [(4,)],
        "mint_nft": [
            (
                4,
                None,
                "xch1qgpqyqszqgpqyqszqgpqyqszqgpqyqszqgpqyqszqgpqyqszqgpqzc0j4g",
                "0x1234",
                ["https://example.com"],
                TXConfig(
                    min_coin_amount=uint64(0),
                    max_coin_amount=uint64(18446744073709551615),
                    excluded_coin_amounts=[],
                    excluded_coin_ids=[],
                    reuse_puzhash=True,
                ),
                "",
                [],
                "",
                [],
                1,
                1,
                500000000000,
                0,
                "0xcee228b8638c67cb66a55085be99fa3b457ae5b56915896f581990f600b2c652",
                True,
                test_condition_valid_times,
            )
        ],
    }
    test_rpc_clients.wallet_rpc_client.check_log(expected_calls)


def test_nft_add_uri(capsys: object, get_test_cli_clients: Tuple[TestRpcClients, Path]) -> None:
    test_rpc_clients, root_dir = get_test_cli_clients

    # set RPC Client
    class NFTAddUriRpcClient(TestWalletRpcClient):
        async def add_uri_to_nft(
            self,
            wallet_id: int,
            nft_coin_id: str,
            key: str,
            uri: str,
            fee: int,
            tx_config: TXConfig,
            push: bool,
            timelock_info: ConditionValidTimes = ConditionValidTimes(),
        ) -> NFTAddURIResponse:
            self.add_to_log("add_uri_to_nft", (wallet_id, nft_coin_id, key, uri, fee, tx_config, push, timelock_info))
            return NFTAddURIResponse([STD_UTX], [STD_TX], uint32(wallet_id), WalletSpendBundle([], G2Element()))

    inst_rpc_client = NFTAddUriRpcClient()  # pylint: disable=no-value-for-parameter
    nft_coin_id = get_bytes32(2).hex()
    test_rpc_clients.wallet_rpc_client = inst_rpc_client
    command_args = [
        "wallet",
        "nft",
        "add_uri",
        FINGERPRINT_ARG,
        "-i4",
        "--nft-coin-id",
        nft_coin_id,
        "--uri",
        "https://example.com/nft",
        "-m0.5",
        "--reuse",
        "--valid-at",
        "100",
        "--expires-at",
        "150",
    ]
    # these are various things that should be in the output
    assert STD_TX.spend_bundle is not None
    assert_list = [f"URI added successfully with spend bundle: {STD_TX.spend_bundle.to_json_dict()}"]
    run_cli_command_and_assert(capsys, root_dir, command_args, assert_list)
    expected_calls: logType = {
        "add_uri_to_nft": [
            (
                4,
                nft_coin_id,
                "u",
                "https://example.com/nft",
                500000000000,
                DEFAULT_TX_CONFIG.override(reuse_puzhash=True),
                True,
                test_condition_valid_times,
            )
        ],
    }
    test_rpc_clients.wallet_rpc_client.check_log(expected_calls)


def test_nft_transfer(capsys: object, get_test_cli_clients: Tuple[TestRpcClients, Path]) -> None:
    test_rpc_clients, root_dir = get_test_cli_clients

    # set RPC Client
    class NFTTransferRpcClient(TestWalletRpcClient):
        async def transfer_nft(
            self,
            wallet_id: int,
            nft_coin_id: str,
            target_address: str,
            fee: int,
            tx_config: TXConfig,
            push: bool,
            timelock_info: ConditionValidTimes = ConditionValidTimes(),
        ) -> NFTTransferNFTResponse:
            self.add_to_log(
                "transfer_nft", (wallet_id, nft_coin_id, target_address, fee, tx_config, push, timelock_info)
            )
            return NFTTransferNFTResponse(
                [STD_UTX],
                [STD_TX],
                uint32(wallet_id),
                WalletSpendBundle([], G2Element()),
            )

    inst_rpc_client = NFTTransferRpcClient()  # pylint: disable=no-value-for-parameter
    nft_coin_id = get_bytes32(2).hex()
    target_address = encode_puzzle_hash(get_bytes32(2), "xch")
    test_rpc_clients.wallet_rpc_client = inst_rpc_client
    command_args = [
        "wallet",
        "nft",
        "transfer",
        FINGERPRINT_ARG,
        "-i4",
        "--nft-coin-id",
        nft_coin_id,
        "--target-address",
        target_address,
        "-m0.5",
        "--reuse",
        "--valid-at",
        "100",
        "--expires-at",
        "150",
    ]
    # these are various things that should be in the output
    assert STD_TX.spend_bundle is not None
    assert_list = ["NFT transferred successfully", f"spend bundle: {STD_TX.spend_bundle.to_json_dict()}"]
    run_cli_command_and_assert(capsys, root_dir, command_args, assert_list)
    expected_calls: logType = {
        "transfer_nft": [
            (
                4,
                nft_coin_id,
                target_address,
                500000000000,
                DEFAULT_TX_CONFIG.override(reuse_puzhash=True),
                True,
                test_condition_valid_times,
            )
        ],
    }
    test_rpc_clients.wallet_rpc_client.check_log(expected_calls)


def test_nft_list(capsys: object, get_test_cli_clients: Tuple[TestRpcClients, Path]) -> None:
    test_rpc_clients, root_dir = get_test_cli_clients

    # set RPC Client
    class NFTListRpcClient(TestWalletRpcClient):
        async def list_nfts(self, wallet_id: int, num: int = 50, start_index: int = 0) -> dict[str, object]:
            self.add_to_log("list_nfts", (wallet_id, num, start_index))
            nft_list = []
            for i in range(start_index, start_index + num):
                index_bytes = bytes32([i] * 32)
                nft_list.append(
                    NFTInfo(
                        nft_id=encode_puzzle_hash(index_bytes, "nft"),
                        launcher_id=get_bytes32(1),
                        nft_coin_id=index_bytes,
                        nft_coin_confirmation_height=uint32(2),
                        owner_did=get_bytes32(2),
                        royalty_percentage=uint16(1000),
                        royalty_puzzle_hash=get_bytes32(3),
                        data_uris=["https://example.com/data"],
                        data_hash=bytes([4]),
                        metadata_uris=["https://example.com/mdata"],
                        metadata_hash=bytes([5]),
                        license_uris=["https://example.com/license"],
                        license_hash=bytes([6]),
                        edition_total=uint64(10),
                        edition_number=uint64(1),
                        updater_puzhash=get_bytes32(7),
                        chain_info="",
                        mint_height=uint32(1),
                        supports_did=True,
                        p2_address=get_bytes32(8),
                    ).to_json_dict()
                )
            return {"nft_list": nft_list}

    inst_rpc_client = NFTListRpcClient()  # pylint: disable=no-value-for-parameter
    launcher_ids = [bytes32([i] * 32).hex() for i in range(50, 60)]
    test_rpc_clients.wallet_rpc_client = inst_rpc_client
    command_args = [
        "wallet",
        "nft",
        "list",
        FINGERPRINT_ARG,
        "-i4",
        "--num",
        "10",
        "--start-index",
        "50",
    ]
    # these are various things that should be in the output
    assert_list = [
        "https://example.com/data",
        "did:chia:1qgpqyqszqgpqyqszqgpqyqszqgpqyqszqgpqyqszqgpqyqszqgpq4msw0c",
    ] + launcher_ids
    run_cli_command_and_assert(capsys, root_dir, command_args, assert_list)
    expected_calls: logType = {
        "list_nfts": [(4, 10, 50)],
    }
    test_rpc_clients.wallet_rpc_client.check_log(expected_calls)


def test_nft_set_did(capsys: object, get_test_cli_clients: Tuple[TestRpcClients, Path]) -> None:
    test_rpc_clients, root_dir = get_test_cli_clients

    # set RPC Client
    class NFTSetDidRpcClient(TestWalletRpcClient):
        async def set_nft_did(
            self,
            wallet_id: int,
            did_id: str,
            nft_coin_id: str,
            fee: int,
            tx_config: TXConfig,
            push: bool,
            timelock_info: ConditionValidTimes = ConditionValidTimes(),
        ) -> NFTSetNFTDIDResponse:
            self.add_to_log("set_nft_did", (wallet_id, did_id, nft_coin_id, fee, tx_config, push, timelock_info))
            return NFTSetNFTDIDResponse(
                [STD_UTX],
                [STD_TX],
                uint32(wallet_id),
                WalletSpendBundle([], G2Element()),
            )

    inst_rpc_client = NFTSetDidRpcClient()  # pylint: disable=no-value-for-parameter
    nft_coin_id = get_bytes32(2).hex()
    did_id = encode_puzzle_hash(get_bytes32(3), "did:chia:")
    test_rpc_clients.wallet_rpc_client = inst_rpc_client
    command_args = [
        "wallet",
        "nft",
        "set_did",
        FINGERPRINT_ARG,
        "-i4",
        "--nft-coin-id",
        nft_coin_id,
        "--did-id",
        did_id,
        "-m0.5",
        "--reuse",
        "--valid-at",
        "100",
        "--expires-at",
        "150",
    ]
    # these are various things that should be in the output
    assert STD_TX.spend_bundle is not None
    assert_list = [f"Transaction to set DID on NFT has been initiated with: {STD_TX.spend_bundle.to_json_dict()}"]
    run_cli_command_and_assert(capsys, root_dir, command_args, assert_list)
    expected_calls: logType = {
        "set_nft_did": [
            (
                4,
                did_id,
                nft_coin_id,
                500000000000,
                DEFAULT_TX_CONFIG.override(reuse_puzhash=True),
                True,
                test_condition_valid_times,
            )
        ],
    }
    test_rpc_clients.wallet_rpc_client.check_log(expected_calls)


def test_nft_get_info(capsys: object, get_test_cli_clients: Tuple[TestRpcClients, Path]) -> None:
    test_rpc_clients, root_dir = get_test_cli_clients

    # set RPC Client

    inst_rpc_client = TestWalletRpcClient()  # pylint: disable=no-value-for-parameter
    nft_coin_id = get_bytes32(2).hex()
    test_rpc_clients.wallet_rpc_client = inst_rpc_client
    command_args = [
        "wallet",
        "nft",
        "get_info",
        FINGERPRINT_ARG,
        "--nft-coin-id",
        nft_coin_id,
    ]
    # these are various things that should be in the output
    assert_list = [
        f"Current NFT coin ID:       {nft_coin_id}",
        "Owner DID:                 did:chia:1qgpqyqszqgpqyqszqgpqyqszqgpqyqszqgpqyqszqgpqyqszqgpq4msw0c",
    ]
    run_cli_command_and_assert(capsys, root_dir, command_args, assert_list)
    expected_calls: logType = {
        "get_nft_info": [(nft_coin_id, True)],
    }
    test_rpc_clients.wallet_rpc_client.check_log(expected_calls)
