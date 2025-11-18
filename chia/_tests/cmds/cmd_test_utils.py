from __future__ import annotations

import sys
from collections.abc import AsyncIterator, Iterable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

from chia_rs import BlockRecord, Coin, G1Element, G2Element
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint8, uint16, uint32, uint64

import chia.cmds.wallet_funcs
from chia._tests.cmds.testing_classes import create_test_block_record
from chia._tests.cmds.wallet.test_consts import STD_TX, STD_UTX, get_bytes32
from chia.cmds.chia import cli as chia_cli
from chia.cmds.cmds_util import _T_RpcClient, node_config_section_names
from chia.consensus.default_constants import DEFAULT_CONSTANTS
from chia.data_layer.data_layer_rpc_client import DataLayerRpcClient
from chia.farmer.farmer_rpc_client import FarmerRpcClient
from chia.full_node.full_node_rpc_client import FullNodeRpcClient
from chia.rpc.rpc_client import RpcClient
from chia.simulator.simulator_full_node_rpc_client import SimulatorFullNodeRpcClient
from chia.types.signing_mode import SigningMode
from chia.util.bech32m import encode_puzzle_hash
from chia.util.config import load_config
from chia.wallet.conditions import ConditionValidTimes
from chia.wallet.nft_wallet.nft_info import NFTInfo
from chia.wallet.nft_wallet.nft_wallet import NFTWallet
from chia.wallet.transaction_record import TransactionRecord
from chia.wallet.util.transaction_type import TransactionType
from chia.wallet.util.tx_config import TXConfig
from chia.wallet.util.wallet_types import WalletType
from chia.wallet.wallet_request_types import (
    CATAssetIDToName,
    CATAssetIDToNameResponse,
    CATGetName,
    CATGetNameResponse,
    GetSyncStatusResponse,
    GetTransaction,
    GetTransactionResponse,
    GetWallets,
    GetWalletsResponse,
    NFTCalculateRoyalties,
    NFTCalculateRoyaltiesResponse,
    NFTGetInfo,
    NFTGetInfoResponse,
    SendTransactionMultiResponse,
    SignMessageByAddress,
    SignMessageByAddressResponse,
    SignMessageByID,
    SignMessageByIDResponse,
    WalletInfoResponse,
)
from chia.wallet.wallet_rpc_client import WalletRpcClient
from chia.wallet.wallet_spend_bundle import WalletSpendBundle

# Any functions that are the same for every command being tested should be below.
# Functions that are specific to a command should be in the test file for that command.

logType = dict[str, list[tuple[Any, ...]] | None]


@dataclass
class TestRpcClient:
    client_type: type[RpcClient]
    rpc_port: uint16 | None = None
    root_path: Path | None = None
    config: dict[str, Any] | None = None
    create_called: bool = field(init=False, default=False)
    rpc_log: dict[str, list[tuple[Any, ...]]] = field(init=False, default_factory=dict)

    async def create(self, _: str, rpc_port: uint16, root_path: Path, config: dict[str, Any]) -> None:
        self.rpc_port = rpc_port
        self.root_path = root_path
        self.config = config
        self.create_called = True

    def add_to_log(self, method_name: str, args: tuple[Any, ...]) -> None:
        if method_name not in self.rpc_log:
            self.rpc_log[method_name] = []
        self.rpc_log[method_name].append(args)

    def check_log(self, expected_calls: logType) -> None:
        for k, v in expected_calls.items():
            assert k in self.rpc_log, f"key '{k}' not in rpc_log, rpc log's keys are: '{list(self.rpc_log.keys())}'"
            if v is not None:  # None means we don't care about the value used when calling the rpc.
                assert self.rpc_log[k] == v, f"for key '{k}'\n'{self.rpc_log[k]}'\n!=\n'{v}'"
        self.rpc_log = {}


@dataclass
class TestFarmerRpcClient(TestRpcClient):
    client_type: type[FarmerRpcClient] = field(init=False, default=FarmerRpcClient)


@dataclass
class TestWalletRpcClient(TestRpcClient):
    client_type: type[WalletRpcClient] = field(init=False, default=WalletRpcClient)
    fingerprint: int = field(init=False, default=0)
    wallet_index: int = field(init=False, default=0)

    async def get_sync_status(self) -> GetSyncStatusResponse:
        self.add_to_log("get_sync_status", ())
        return GetSyncStatusResponse(synced=True, syncing=False)

    async def get_wallets(self, request: GetWallets) -> GetWalletsResponse:
        self.add_to_log("get_wallets", (request,))
        # we cant start with zero because ints cant have a leading zero
        if request.type is not None:
            w_type = WalletType(request.type)
        elif str(self.fingerprint).startswith(str(WalletType.STANDARD_WALLET.value + 1)):
            w_type = WalletType.STANDARD_WALLET
        elif str(self.fingerprint).startswith(str(WalletType.CAT.value + 1)):
            w_type = WalletType.CAT
        elif str(self.fingerprint).startswith(str(WalletType.NFT.value + 1)):
            w_type = WalletType.NFT
        elif str(self.fingerprint).startswith(str(WalletType.DECENTRALIZED_ID.value + 1)):
            w_type = WalletType.DECENTRALIZED_ID
        elif str(self.fingerprint).startswith(str(WalletType.POOLING_WALLET.value + 1)):
            w_type = WalletType.POOLING_WALLET
        else:
            raise ValueError(f"Invalid fingerprint: {self.fingerprint}")
        return GetWalletsResponse([WalletInfoResponse(id=uint32(1), name="", type=uint8(w_type.value), data="")])

    async def get_transaction(self, request: GetTransaction) -> GetTransactionResponse:
        self.add_to_log("get_transaction", (request,))
        return GetTransactionResponse(
            TransactionRecord(
                confirmed_at_height=uint32(1),
                created_at_time=uint64(1234),
                to_puzzle_hash=bytes32([1] * 32),
                to_address=encode_puzzle_hash(bytes32([1] * 32), "xch"),
                amount=uint64(12345678),
                fee_amount=uint64(1234567),
                confirmed=False,
                sent=uint32(0),
                spend_bundle=WalletSpendBundle([], G2Element()),
                additions=[Coin(bytes32([1] * 32), bytes32([2] * 32), uint64(12345678))],
                removals=[Coin(bytes32([2] * 32), bytes32([4] * 32), uint64(12345678))],
                wallet_id=uint32(1),
                sent_to=[("aaaaa", uint8(1), None)],
                trade_id=None,
                type=uint32(TransactionType.OUTGOING_TX.value),
                name=bytes32([2] * 32),
                memos={bytes32([3] * 32): [bytes([4] * 32)]},
                valid_times=ConditionValidTimes(),
            ),
            bytes32([2] * 32),
        )

    async def get_cat_name(self, request: CATGetName) -> CATGetNameResponse:
        self.add_to_log("get_cat_name", (request.wallet_id,))
        return CATGetNameResponse(request.wallet_id, "test" + str(request.wallet_id))

    async def sign_message_by_address(self, request: SignMessageByAddress) -> SignMessageByAddressResponse:
        self.add_to_log("sign_message_by_address", (request.address, request.message))
        pubkey = G1Element.from_bytes(
            bytes.fromhex(
                "b5acf3599bc5fa5da1c00f6cc3d5bcf1560def67778b7f50a8c373a83f78761505b6250ab776e38a292e26628009aec4"
            )
        )
        signature = G2Element.from_bytes(
            bytes.fromhex(
                "c00000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
                "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
            )
        )
        signing_mode = SigningMode.CHIP_0002.value
        return SignMessageByAddressResponse(pubkey, signature, signing_mode)

    async def sign_message_by_id(self, request: SignMessageByID) -> SignMessageByIDResponse:
        self.add_to_log("sign_message_by_id", (request.id, request.message))
        pubkey = G1Element.from_bytes(
            bytes.fromhex(
                "a9e652cb551d5978a9ee4b7aa52a4e826078a54b08a3d903c38611cb8a804a9a29c926e4f8549314a079e04ecde10cc1"
            )
        )
        signature = G2Element.from_bytes(
            bytes.fromhex(
                "c00000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
                "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
            )
        )
        signing_mode = SigningMode.CHIP_0002.value
        return SignMessageByIDResponse(pubkey, signature, bytes32.zeros, signing_mode)

    async def cat_asset_id_to_name(self, request: CATAssetIDToName) -> CATAssetIDToNameResponse:
        """
        if bytes32([1] * 32), return (uint32(2), "test1"), if bytes32([1] * 32), return (uint32(3), "test2")
        """
        self.add_to_log("cat_asset_id_to_name", (request.asset_id,))
        for i in range(256):
            if request.asset_id == get_bytes32(i):
                return CATAssetIDToNameResponse(uint32(i + 1), "test" + str(i))
        return CATAssetIDToNameResponse(wallet_id=None, name=None)

    async def get_nft_info(self, request: NFTGetInfo) -> NFTGetInfoResponse:
        self.add_to_log("get_nft_info", (request.coin_id, request.latest))
        coin_id_bytes = bytes32.fromhex(request.coin_id)
        nft_info = NFTInfo(
            nft_id=encode_puzzle_hash(coin_id_bytes, "nft"),
            launcher_id=bytes32([1] * 32),
            nft_coin_id=coin_id_bytes,
            nft_coin_confirmation_height=uint32(2),
            owner_did=bytes32([2] * 32),
            royalty_percentage=uint16(1000),
            royalty_puzzle_hash=bytes32([3] * 32),
            data_uris=["https://example.com/data"],
            data_hash=bytes([4]),
            metadata_uris=["https://example.com/mdata"],
            metadata_hash=bytes([5]),
            license_uris=["https://example.com/license"],
            license_hash=bytes([6]),
            edition_total=uint64(10),
            edition_number=uint64(1),
            updater_puzhash=bytes32([7] * 32),
            chain_info="",
            mint_height=uint32(1),
            supports_did=True,
            p2_address=bytes32([8] * 32),
        )
        return NFTGetInfoResponse(nft_info)

    async def nft_calculate_royalties(
        self,
        request: NFTCalculateRoyalties,
    ) -> NFTCalculateRoyaltiesResponse:
        self.add_to_log("nft_calculate_royalties", (request,))
        return NFTCalculateRoyaltiesResponse.from_json_dict(
            NFTWallet.royalty_calculation(
                {asset.asset: (asset.royalty_address, asset.royalty_percentage) for asset in request.royalty_assets},
                {asset.asset: asset.amount for asset in request.fungible_assets},
            )
        )

    async def send_transaction_multi(
        self,
        wallet_id: int,
        additions: list[dict[str, object]],
        tx_config: TXConfig,
        coins: list[Coin] | None = None,
        fee: uint64 = uint64(0),
        push: bool = True,
        timelock_info: ConditionValidTimes = ConditionValidTimes(),
    ) -> SendTransactionMultiResponse:
        self.add_to_log("send_transaction_multi", (wallet_id, additions, tx_config, coins, fee, push, timelock_info))
        name = bytes32([2] * 32)
        return SendTransactionMultiResponse(
            [STD_UTX],
            [STD_TX],
            TransactionRecord(
                confirmed_at_height=uint32(1),
                created_at_time=uint64(1234),
                to_puzzle_hash=bytes32([1] * 32),
                to_address=encode_puzzle_hash(bytes32([1] * 32), "xch"),
                amount=uint64(12345678),
                fee_amount=uint64(1234567),
                confirmed=False,
                sent=uint32(0),
                spend_bundle=WalletSpendBundle([], G2Element()),
                additions=[Coin(bytes32([1] * 32), bytes32([2] * 32), uint64(12345678))],
                removals=[Coin(bytes32([2] * 32), bytes32([4] * 32), uint64(12345678))],
                wallet_id=uint32(1),
                sent_to=[("aaaaa", uint8(1), None)],
                trade_id=None,
                type=uint32(TransactionType.OUTGOING_TX.value),
                name=name,
                memos={bytes32([3] * 32): [bytes([4] * 32)]},
                valid_times=ConditionValidTimes(),
            ),
            name,
        )


@dataclass
class TestFullNodeRpcClient(TestRpcClient):
    client_type: type[FullNodeRpcClient] = field(init=False, default=FullNodeRpcClient)

    async def get_fee_estimate(
        self,
        target_times: list[int] | None,
        cost: int | None,
    ) -> dict[str, Any]:
        return {}

    async def get_blockchain_state(self) -> dict[str, Any]:
        response: dict[str, Any] = {
            "peak": cast(BlockRecord, create_test_block_record()),
            "genesis_challenge_initialized": True,
            "sync": {
                "sync_mode": False,
                "synced": True,
                "sync_tip_height": 0,
                "sync_progress_height": 0,
            },
            "difficulty": 1024,
            "sub_slot_iters": 147849216,
            "space": 29569289860555554816,
            "mempool_size": 3,
            "mempool_cost": 88304083,
            "mempool_fees": 50,
            "mempool_min_fees": {
                # We may give estimates for varying costs in the future
                # This Dict sets us up for that in the future
                "cost_5000000": 0,
            },
            "mempool_max_total_cost": 550000000000,
            "block_max_cost": DEFAULT_CONSTANTS.MAX_BLOCK_COST_CLVM,
            "node_id": "7991a584ae4784ab7525bda352ea9b155ce2ac108d361afc13d5964a0f33fa6d",
        }
        self.add_to_log("get_blockchain_state", ())
        return response

    async def get_block_record_by_height(self, height: int) -> BlockRecord | None:
        self.add_to_log("get_block_record_by_height", (height,))
        return cast(BlockRecord, create_test_block_record(height=uint32(height)))

    async def get_block_record(self, header_hash: bytes32) -> BlockRecord | None:
        self.add_to_log("get_block_record", (header_hash,))
        return cast(BlockRecord, create_test_block_record(header_hash=header_hash))


@dataclass
class TestDataLayerRpcClient(TestRpcClient):
    client_type: type[DataLayerRpcClient] = field(init=False, default=DataLayerRpcClient)


@dataclass
class TestSimulatorFullNodeRpcClient(TestRpcClient):
    client_type: type[SimulatorFullNodeRpcClient] = field(init=False, default=SimulatorFullNodeRpcClient)


@dataclass
class TestRpcClients:
    """
    Because this data is in a class, it can be modified by the tests even after the generator is created and imported.
    This is important, as we need an easy way to modify the monkey-patched functions.
    """

    farmer_rpc_client: TestFarmerRpcClient = field(default_factory=TestFarmerRpcClient)
    wallet_rpc_client: TestWalletRpcClient = field(default_factory=TestWalletRpcClient)
    full_node_rpc_client: TestFullNodeRpcClient = field(default_factory=TestFullNodeRpcClient)
    data_layer_rpc_client: TestDataLayerRpcClient = field(default_factory=TestDataLayerRpcClient)
    simulator_full_node_rpc_client: TestSimulatorFullNodeRpcClient = field(
        default_factory=TestSimulatorFullNodeRpcClient
    )

    def get_client(self, client_type: type[_T_RpcClient]) -> _T_RpcClient:
        if client_type == FarmerRpcClient:
            return cast(FarmerRpcClient, self.farmer_rpc_client)  # type: ignore[return-value]
        elif client_type == WalletRpcClient:
            return cast(WalletRpcClient, self.wallet_rpc_client)  # type: ignore[return-value]
        elif client_type == FullNodeRpcClient:
            return cast(FullNodeRpcClient, self.full_node_rpc_client)  # type: ignore[return-value]
        elif client_type == DataLayerRpcClient:
            return cast(DataLayerRpcClient, self.data_layer_rpc_client)  # type: ignore[return-value]
        elif client_type == SimulatorFullNodeRpcClient:
            return cast(SimulatorFullNodeRpcClient, self.simulator_full_node_rpc_client)  # type: ignore[return-value]
        else:
            raise ValueError(f"Invalid client type requested: {client_type.__name__}")


def create_service_and_wallet_client_generators(test_rpc_clients: TestRpcClients, default_root: Path) -> None:
    """
    Create and monkey patch custom generators designed for testing.
    These are monkey patched into the chia.cmds.cmds_util module.
    Each generator below replaces the original function with a new one that returns a custom client, given by the class.
    The clients given can be changed by changing the variables in the class above, after running this function.
    """

    @asynccontextmanager
    async def test_get_any_service_client(
        client_type: type[_T_RpcClient],
        root_path: Path,
        rpc_port: int | None = None,
        consume_errors: bool = True,
        use_ssl: bool = True,
    ) -> AsyncIterator[tuple[_T_RpcClient, dict[str, Any]]]:
        if root_path is None:
            root_path = default_root

        node_type = node_config_section_names.get(client_type)
        if node_type is None:
            # Click already checks this, so this should never happen
            raise ValueError(f"Invalid client type requested: {client_type.__name__}")
        # load variables from config file
        config = load_config(
            root_path,
            "config.yaml",
            fill_missing_services=issubclass(client_type, DataLayerRpcClient),
        )
        self_hostname = config["self_hostname"]
        if rpc_port is None:
            rpc_port = config[node_type]["rpc_port"]
        test_rpc_client = test_rpc_clients.get_client(client_type)

        await test_rpc_client.create(self_hostname, uint16(rpc_port), root_path, config)
        yield test_rpc_client, config

    @asynccontextmanager
    async def test_get_wallet_client(
        root_path: Path = default_root,
        wallet_rpc_port: int | None = None,
        fingerprint: int | None = None,
    ) -> AsyncIterator[tuple[WalletRpcClient, int, dict[str, Any]]]:
        async with test_get_any_service_client(WalletRpcClient, root_path, wallet_rpc_port) as (wallet_client, config):
            wallet_client.fingerprint = fingerprint  # type: ignore
            assert fingerprint is not None
            yield wallet_client, fingerprint, config

    def cli_confirm(input_message: str, abort_message: str = "Did not confirm. Aborting.") -> None:
        return None

    # Monkey patches the functions into the module, the classes returned by these functions can be changed in the class.
    # For more information, read the docstring of this function.
    chia.cmds.cmds_util.get_any_service_client = test_get_any_service_client
    chia.cmds.cmds_util.get_wallet_client = test_get_wallet_client  # type: ignore[assignment]
    chia.cmds.wallet_funcs.get_wallet_client = test_get_wallet_client  # type: ignore[assignment,attr-defined]
    # Monkey patches the confirm function to not ask for confirmation
    chia.cmds.cmds_util.cli_confirm = cli_confirm
    chia.cmds.wallet_funcs.cli_confirm = cli_confirm  # type: ignore[attr-defined]


def run_cli_command(capsys: object, chia_root: Path, command_list: list[str]) -> str:
    """
    This is just an easy way to run the chia CLI with the given command list.
    """
    # we don't use the real capsys object because its only accessible in a private part of the pytest module
    exited_cleanly = True
    argv_temp = sys.argv
    try:
        sys.argv = ["chia", "--root-path", str(chia_root), *command_list]
        chia_cli()
    except SystemExit as e:
        if e.code != 0:
            exited_cleanly = False
    finally:  # always reset sys.argv
        sys.argv = argv_temp
    output = capsys.readouterr()  # type: ignore[attr-defined]
    assert exited_cleanly, f"\n{output.out}\n{output.err}"
    return str(output.out)


def cli_assert_shortcut(output: str, strings_to_assert: Iterable[str]) -> None:
    """
    Asserts that all the strings in strings_to_assert are in the output
    """
    for string_to_assert in strings_to_assert:
        assert string_to_assert in output, f"'{string_to_assert}' was not in\n'{output}'"


def run_cli_command_and_assert(
    capsys: object, chia_root: Path, command_list: list[str], strings_to_assert: Iterable[str]
) -> None:
    """
    Runs the command and asserts that all the strings in strings_to_assert are in the output
    """
    output = run_cli_command(capsys, chia_root, command_list)
    cli_assert_shortcut(output, strings_to_assert)
