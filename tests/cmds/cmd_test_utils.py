from __future__ import annotations

import sys
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, AsyncIterator, Dict, Iterable, List, Optional, Tuple, Type, cast

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
from chia.util.config import load_config
from chia.util.default_root import DEFAULT_ROOT_PATH
from chia.util.ints import uint16, uint32
from tests.cmds.test_classes import create_test_block_record

# Any functions that are the same for every command being tested should be below.
# Functions that are specific to a command should be in the test file for that command.


@dataclass
class TestRpcClient:
    client_type: Type[RpcClient]
    rpc_port: Optional[uint16] = None
    root_path: Optional[Path] = None
    config: Optional[Dict[str, Any]] = None
    create_called: bool = field(init=False, default=False)
    rpc_log: Dict[str, Tuple[Any, ...]] = field(init=False, default_factory=dict)

    async def create(self, _: str, rpc_port: uint16, root_path: Path, config: Dict[str, Any]) -> None:
        self.rpc_port = rpc_port
        self.root_path = root_path
        self.config = config
        self.create_called = True

    def check_log(self, expected_calls: Dict[str, Optional[Tuple[Any, ...]]]) -> None:
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
        self.rpc_log["get_blockchain_state"] = ()
        return response

    async def get_block_record_by_height(self, height: int) -> Optional[BlockRecord]:
        self.rpc_log["get_block_record_by_height"] = (height,)
        return cast(BlockRecord, create_test_block_record(height=uint32(height)))

    async def get_block_record(self, header_hash: bytes32) -> Optional[BlockRecord]:
        self.rpc_log["get_block_record"] = (header_hash,)
        return cast(BlockRecord, create_test_block_record(header_hash=header_hash))


@dataclass
class TestDataLayerRpcClient(TestRpcClient):
    client_type: Type[DataLayerRpcClient] = field(init=False, default=DataLayerRpcClient)


@dataclass
class TestSimulatorFullNodeRpcClient(TestRpcClient):
    client_type: Type[SimulatorFullNodeRpcClient] = field(init=False, default=SimulatorFullNodeRpcClient)


@dataclass
class GlobalTestRpcClients:
    """
    Because this data is in a class, it can be modified by the tests even after the generator is created and imported.
    """

    farmer_rpc_client: TestFarmerRpcClient = TestFarmerRpcClient()
    wallet_rpc_client: TestWalletRpcClient = TestWalletRpcClient()
    full_node_rpc_client: TestFullNodeRpcClient = TestFullNodeRpcClient()
    data_layer_rpc_client: TestDataLayerRpcClient = TestDataLayerRpcClient()
    simulator_full_node_rpc_client: TestSimulatorFullNodeRpcClient = TestSimulatorFullNodeRpcClient()

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


def create_service_and_wallet_client_generators(test_rpc_clients: GlobalTestRpcClients) -> None:
    # custom generators designed for testing

    @asynccontextmanager
    async def test_get_any_service_client(
        client_type: Type[_T_RpcClient],
        rpc_port: Optional[int] = None,
        root_path: Path = DEFAULT_ROOT_PATH,
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
        root_path: Path = DEFAULT_ROOT_PATH,
    ) -> AsyncIterator[Tuple[WalletRpcClient, int, Dict[str, Any]]]:
        async with test_get_any_service_client(WalletRpcClient, wallet_rpc_port, root_path) as (wallet_client, config):
            wallet_client.fingerprint = fingerprint  # type: ignore
            assert fingerprint is not None
            yield wallet_client, fingerprint, config

    # override the functions
    chia.cmds.cmds_util.get_any_service_client = test_get_any_service_client
    chia.cmds.wallet_funcs.get_wallet_client = test_get_wallet_client  # type: ignore[attr-defined]


def run_cli_command(capsys: Any, command_list: List[str]) -> Tuple[bool, str]:
    argv_temp = sys.argv
    try:
        sys.argv = [sys.argv[0]] + command_list
        exited_cleanly = True
        try:
            chia_cli()  # pylint: disable=no-value-for-parameter
        except SystemExit as e:
            if e.code != 0:
                exited_cleanly = False
        str_output = capsys.readouterr().out
    finally:  # always reset sys.argv
        sys.argv = argv_temp
    if not exited_cleanly:  # so we can look at what went wrong
        print(str_output)
    return exited_cleanly, str_output


def cli_assert_shortcut(output: str, strings_to_assert: Iterable[str]) -> None:
    """
    Asserts that all the strings in strings_to_assert are in the output
    """
    for string_to_assert in strings_to_assert:
        assert string_to_assert in output
