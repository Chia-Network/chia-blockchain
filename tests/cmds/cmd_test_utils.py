from __future__ import annotations

import sys
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, AsyncIterator, Dict, Iterable, List, Optional, Tuple, Type, cast

from blspy import G2Element
from chia_rs import Coin

import chia.cmds.wallet_funcs
from chia.cmds.chia import cli as chia_cli
from chia.cmds.cmds_util import _T_RpcClient, node_config_section_names
from chia.consensus.block_record import BlockRecord
from chia.consensus.default_constants import DEFAULT_CONSTANTS
from chia.rpc.data_layer_rpc_client import DataLayerRpcClient
from chia.rpc.farmer_rpc_client import FarmerRpcClient
from chia.rpc.full_node_rpc_client import FullNodeRpcClient
from chia.rpc.rpc_client import RpcClient
from chia.rpc.wallet_rpc_client import WalletRpcClient
from chia.simulator.simulator_full_node_rpc_client import SimulatorFullNodeRpcClient
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.spend_bundle import SpendBundle
from chia.util.config import load_config
from chia.util.ints import uint8, uint16, uint32, uint64
from chia.wallet.transaction_record import TransactionRecord
from chia.wallet.util.transaction_type import TransactionType
from chia.wallet.util.wallet_types import WalletType
from tests.cmds.testing_classes import create_test_block_record

# Any functions that are the same for every command being tested should be below.
# Functions that are specific to a command should be in the test file for that command.

logType = Dict[str, Optional[List[Tuple[Any, ...]]]]


@dataclass
class TestRpcClient:
    client_type: Type[RpcClient]
    rpc_port: Optional[uint16] = None
    root_path: Optional[Path] = None
    config: Optional[Dict[str, Any]] = None
    create_called: bool = field(init=False, default=False)
    rpc_log: Dict[str, List[Tuple[Any, ...]]] = field(init=False, default_factory=dict)

    async def create(self, _: str, rpc_port: uint16, root_path: Path, config: Dict[str, Any]) -> None:
        self.rpc_port = rpc_port
        self.root_path = root_path
        self.config = config
        self.create_called = True

    def add_to_log(self, method_name: str, args: Tuple[Any, ...]) -> None:
        if method_name not in self.rpc_log:
            self.rpc_log[method_name] = []
        self.rpc_log[method_name].append(args)

    def check_log(self, expected_calls: logType) -> None:
        for k, v in expected_calls.items():
            assert k in self.rpc_log
            if v is not None:  # None means we don't care about the value used when calling the rpc.
                assert self.rpc_log[k] == v
        self.rpc_log = {}


@dataclass
class TestFarmerRpcClient(TestRpcClient):
    client_type: Type[FarmerRpcClient] = field(init=False, default=FarmerRpcClient)


@dataclass
class TestWalletRpcClient(TestRpcClient):
    client_type: Type[WalletRpcClient] = field(init=False, default=WalletRpcClient)
    fingerprint: int = field(init=False, default=0)

    async def get_wallets(self) -> List[Dict[str, int]]:
        # we cant start with zero because ints cant have a leading zero
        if str(self.fingerprint).startswith(str(WalletType.STANDARD_WALLET.value + 1)):
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
        self.add_to_log("get_wallets", ())
        return [{"id": 1, "type": w_type}]

    async def get_transaction(self, wallet_id: int, transaction_id: bytes32) -> TransactionRecord:
        self.add_to_log("get_transaction", (wallet_id, transaction_id))
        return TransactionRecord(
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
            type=uint32(TransactionType.OUTGOING_TX.value),
            name=bytes32([2] * 32),
            memos=[(bytes32([3] * 32), [bytes([4] * 32)])],
        )


@dataclass
class TestFullNodeRpcClient(TestRpcClient):
    client_type: Type[FullNodeRpcClient] = field(init=False, default=FullNodeRpcClient)

    async def get_blockchain_state(self) -> Dict[str, Any]:
        response: Dict[str, Any] = {
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

    async def get_block_record_by_height(self, height: int) -> Optional[BlockRecord]:
        self.add_to_log("get_block_record_by_height", (height,))
        return cast(BlockRecord, create_test_block_record(height=uint32(height)))

    async def get_block_record(self, header_hash: bytes32) -> Optional[BlockRecord]:
        self.add_to_log("get_block_record", (header_hash,))
        return cast(BlockRecord, create_test_block_record(header_hash=header_hash))


@dataclass
class TestDataLayerRpcClient(TestRpcClient):
    client_type: Type[DataLayerRpcClient] = field(init=False, default=DataLayerRpcClient)


@dataclass
class TestSimulatorFullNodeRpcClient(TestRpcClient):
    client_type: Type[SimulatorFullNodeRpcClient] = field(init=False, default=SimulatorFullNodeRpcClient)


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

    def get_client(self, client_type: Type[_T_RpcClient]) -> _T_RpcClient:
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
        client_type: Type[_T_RpcClient],
        rpc_port: Optional[int] = None,
        root_path: Path = default_root,
        consume_errors: bool = True,
    ) -> AsyncIterator[Tuple[_T_RpcClient, Dict[str, Any]]]:
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
        wallet_rpc_port: Optional[int] = None,
        fingerprint: Optional[int] = None,
        root_path: Path = default_root,
    ) -> AsyncIterator[Tuple[WalletRpcClient, int, Dict[str, Any]]]:
        async with test_get_any_service_client(WalletRpcClient, wallet_rpc_port, root_path) as (wallet_client, config):
            wallet_client.fingerprint = fingerprint  # type: ignore
            assert fingerprint is not None
            yield wallet_client, fingerprint, config

    # Monkey patches the functions into the module, the classes returned by these functions can be changed in the class.
    # For more information, read the docstring of this function.
    chia.cmds.cmds_util.get_any_service_client = test_get_any_service_client
    chia.cmds.wallet_funcs.get_wallet_client = test_get_wallet_client  # type: ignore[attr-defined]


def run_cli_command(capsys: object, chia_root: Path, command_list: List[str]) -> Tuple[bool, str]:
    """
    This is just an easy way to run the chia CLI with the given command list.
    """
    # we don't use the real capsys object because its only accessible in a private part of the pytest module
    argv_temp = sys.argv
    try:
        sys.argv = ["chia", "--root-path", str(chia_root)] + command_list
        exited_cleanly = True
        try:
            chia_cli()  # pylint: disable=no-value-for-parameter
        except SystemExit as e:
            if e.code != 0:
                exited_cleanly = False
        output = capsys.readouterr()  # type: ignore[attr-defined]
    finally:  # always reset sys.argv
        sys.argv = argv_temp
    if not exited_cleanly:  # so we can look at what went wrong
        print(f"\n{output.out}\n{output.err}")
    return exited_cleanly, output.out


def cli_assert_shortcut(output: str, strings_to_assert: Iterable[str]) -> None:
    """
    Asserts that all the strings in strings_to_assert are in the output
    """
    for string_to_assert in strings_to_assert:
        assert string_to_assert in output
