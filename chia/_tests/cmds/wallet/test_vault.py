from __future__ import annotations

from pathlib import Path

from chia_rs import G1Element

from chia._tests.cmds.cmd_test_utils import TestRpcClients, TestWalletRpcClient, run_cli_command_and_assert
from chia._tests.cmds.wallet.test_consts import FINGERPRINT_ARG, STD_TX, STD_UTX, WALLET_ID_ARG
from chia.rpc.wallet_request_types import VaultCreate, VaultCreateResponse, VaultRecovery, VaultRecoveryResponse
from chia.util.ints import uint64
from chia.wallet.conditions import ConditionValidTimes
from chia.wallet.util.tx_config import TXConfig

test_condition_valid_times: ConditionValidTimes = ConditionValidTimes(min_time=uint64(100), max_time=uint64(150))


def test_vault_create(capsys: object, get_test_cli_clients: tuple[TestRpcClients, Path]) -> None:
    test_rpc_clients, root_dir = get_test_cli_clients

    # set RPC clients
    class CreateVaultRpcClient(TestWalletRpcClient):
        async def vault_create(
            self,
            args: VaultCreate,
            tx_config: TXConfig,
            timelock_info: ConditionValidTimes,
        ) -> VaultCreateResponse:
            return VaultCreateResponse([STD_UTX], [STD_TX])

    inst_rpc_client = CreateVaultRpcClient()  # pylint: disable=no-value-for-parameter
    test_rpc_clients.wallet_rpc_client = inst_rpc_client
    pk = bytes(G1Element()).hex()
    recovery_pk = bytes(G1Element()).hex()
    timelock = "100"
    hidden_puzzle_index = "10"
    fee = "0.1"
    command_args = [
        "vault",
        "create",
        FINGERPRINT_ARG,
        "-pk",
        pk,
        "-rk",
        recovery_pk,
        "-rt",
        timelock,
        "-i",
        hidden_puzzle_index,
        "-m",
        fee,
        "--valid-at",
        "100",
        "--expires-at",
        "150",
    ]
    assert_list = ["Successfully created a Vault wallet"]
    run_cli_command_and_assert(capsys, root_dir, command_args, assert_list)


def test_vault_recovery(capsys: object, get_test_cli_clients: tuple[TestRpcClients, Path], tmp_path: Path) -> None:
    test_rpc_clients, root_dir = get_test_cli_clients

    # set RPC clients
    class CreateVaultRpcClient(TestWalletRpcClient):
        async def vault_recovery(
            self,
            args: VaultRecovery,
            tx_config: TXConfig,
            timelock_info: ConditionValidTimes,
        ) -> VaultRecoveryResponse:
            return VaultRecoveryResponse([STD_UTX, STD_UTX], [STD_TX, STD_TX], STD_TX.name, STD_TX.name)

    inst_rpc_client = CreateVaultRpcClient()  # pylint: disable=no-value-for-parameter
    test_rpc_clients.wallet_rpc_client = inst_rpc_client
    pk = bytes(G1Element()).hex()
    recovery_pk = bytes(G1Element()).hex()
    timelock = "100"
    hidden_puzzle_index = "10"
    command_args = [
        "vault",
        "recover",
        "-pk",
        pk,
        "-rk",
        recovery_pk,
        "-rt",
        timelock,
        "-i",
        hidden_puzzle_index,
        "-ri",
        str(tmp_path / "recovery_init.json"),
        "-rf",
        str(tmp_path / "recovery_finish.json"),
        "--valid-at",
        "100",
        "--expires-at",
        "150",
    ]
    assert_list = [
        "Writing transactions to file ",
        "recovery_init.json",
        "recovery_finish.json",
    ]
    run_cli_command_and_assert(capsys, root_dir, command_args + [FINGERPRINT_ARG, WALLET_ID_ARG], assert_list)
