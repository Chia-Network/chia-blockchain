from __future__ import annotations

from pathlib import Path
from typing import List, Optional, Tuple

from chia_rs import Coin, G1Element, G2Element

from chia._tests.cmds.cmd_test_utils import TestRpcClients, TestWalletRpcClient, run_cli_command_and_assert
from chia._tests.cmds.wallet.test_consts import FINGERPRINT_ARG, WALLET_ID_ARG, get_bytes32
from chia.types.spend_bundle import SpendBundle
from chia.util.ints import uint8, uint32, uint64
from chia.wallet.conditions import ConditionValidTimes
from chia.wallet.transaction_record import TransactionRecord
from chia.wallet.util.transaction_type import TransactionType
from chia.wallet.util.tx_config import TXConfig


def test_vault_create(capsys: object, get_test_cli_clients: Tuple[TestRpcClients, Path]) -> None:
    test_rpc_clients, root_dir = get_test_cli_clients

    # set RPC clients
    class CreateVaultRpcClient(TestWalletRpcClient):
        async def vault_create(
            self,
            secp_pk: bytes,
            hp_index: uint32,
            tx_config: TXConfig,
            bls_pk: Optional[bytes] = None,
            timelock: Optional[uint64] = None,
            fee: uint64 = uint64(0),
            push: bool = True,
        ) -> List[TransactionRecord]:
            tx_rec = TransactionRecord(
                confirmed_at_height=uint32(1),
                created_at_time=uint64(1234),
                to_puzzle_hash=get_bytes32(1),
                amount=uint64(12345678),
                fee_amount=uint64(1234567),
                confirmed=False,
                sent=uint32(0),
                spend_bundle=SpendBundle([], G2Element()),
                additions=[Coin(get_bytes32(1), get_bytes32(2), uint64(12345678))],
                removals=[Coin(get_bytes32(2), get_bytes32(4), uint64(12345678))],
                wallet_id=uint32(1),
                sent_to=[("aaaaa", uint8(1), None)],
                trade_id=None,
                type=uint32(TransactionType.OUTGOING_TX.value),
                name=get_bytes32(2),
                memos=[(get_bytes32(3), [bytes([4] * 32)])],
                valid_times=ConditionValidTimes(),
            )
            return [tx_rec]

    inst_rpc_client = CreateVaultRpcClient()  # pylint: disable=no-value-for-parameter
    test_rpc_clients.wallet_rpc_client = inst_rpc_client
    pk = get_bytes32(0).hex()
    recovery_pk = get_bytes32(1).hex()
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
    ]
    assert_list = ["Successfully created a Vault wallet"]
    run_cli_command_and_assert(capsys, root_dir, command_args, assert_list)


def test_vault_recovery(capsys: object, get_test_cli_clients: Tuple[TestRpcClients, Path]) -> None:
    test_rpc_clients, root_dir = get_test_cli_clients

    # set RPC clients
    class CreateVaultRpcClient(TestWalletRpcClient):
        async def vault_recovery(
            self,
            wallet_id: uint32,
            secp_pk: bytes,
            hp_index: uint32,
            tx_config: TXConfig,
            bls_pk: Optional[G1Element] = None,
            timelock: Optional[uint64] = None,
        ) -> List[TransactionRecord]:
            tx_rec = TransactionRecord(
                confirmed_at_height=uint32(1),
                created_at_time=uint64(1234),
                to_puzzle_hash=get_bytes32(1),
                amount=uint64(12345678),
                fee_amount=uint64(1234567),
                confirmed=False,
                sent=uint32(0),
                spend_bundle=SpendBundle([], G2Element()),
                additions=[Coin(get_bytes32(1), get_bytes32(2), uint64(12345678))],
                removals=[Coin(get_bytes32(2), get_bytes32(4), uint64(12345678))],
                wallet_id=uint32(1),
                sent_to=[("aaaaa", uint8(1), None)],
                trade_id=None,
                type=uint32(TransactionType.OUTGOING_TX.value),
                name=get_bytes32(2),
                memos=[(get_bytes32(3), [bytes([4] * 32)])],
                valid_times=ConditionValidTimes(),
            )
            return [tx_rec, tx_rec]

    inst_rpc_client = CreateVaultRpcClient()  # pylint: disable=no-value-for-parameter
    test_rpc_clients.wallet_rpc_client = inst_rpc_client
    pk = get_bytes32(0).hex()
    recovery_pk = get_bytes32(1).hex()
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
        "recovery_init.json",
        "-rf",
        "recovery_finish.json",
    ]
    assert_list = [
        "Initiate Recovery transaction written to: recovery_init.json",
        "Finish Recovery transaction written to: recovery_finish.json",
    ]
    run_cli_command_and_assert(capsys, root_dir, command_args + [FINGERPRINT_ARG, WALLET_ID_ARG], assert_list)
