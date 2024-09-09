from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Tuple

from chia._tests.cmds.cmd_test_utils import TestRpcClients, TestWalletRpcClient, logType, run_cli_command_and_assert
from chia._tests.cmds.wallet.test_consts import FINGERPRINT, FINGERPRINT_ARG, STD_TX, STD_UTX, get_bytes32
from chia.rpc.wallet_request_types import CombineCoins, CombineCoinsResponse, SplitCoins, SplitCoinsResponse
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.ints import uint16, uint32, uint64
from chia.wallet.conditions import ConditionValidTimes
from chia.wallet.util.tx_config import DEFAULT_TX_CONFIG, CoinSelectionConfig, TXConfig

test_condition_valid_times: ConditionValidTimes = ConditionValidTimes(min_time=uint64(100), max_time=uint64(150))

# Coin Commands


def test_coins_get_info(capsys: object, get_test_cli_clients: Tuple[TestRpcClients, Path]) -> None:
    test_rpc_clients, root_dir = get_test_cli_clients

    # set RPC Client

    inst_rpc_client = TestWalletRpcClient()  # pylint: disable=no-value-for-parameter
    test_rpc_clients.wallet_rpc_client = inst_rpc_client
    command_args = ["wallet", "coins", "list", FINGERPRINT_ARG, "-i1", "-u"]
    # these are various things that should be in the output
    assert_list = [
        "There are a total of 3 coins in wallet 1.",
        "2 confirmed coins.",
        "1 unconfirmed additions.",
        "1 unconfirmed removals.",
    ]
    run_cli_command_and_assert(capsys, root_dir, command_args, assert_list)
    expected_calls: logType = {
        "get_wallets": [(None,)],
        "get_synced": [()],
        "get_spendable_coins": [
            (
                1,
                CoinSelectionConfig(
                    min_coin_amount=uint64(0),
                    max_coin_amount=DEFAULT_TX_CONFIG.max_coin_amount,
                    excluded_coin_amounts=[],
                    excluded_coin_ids=[],
                ),
            )
        ],
    }
    test_rpc_clients.wallet_rpc_client.check_log(expected_calls)


def test_coins_combine(capsys: object, get_test_cli_clients: Tuple[TestRpcClients, Path]) -> None:
    test_rpc_clients, root_dir = get_test_cli_clients

    # set RPC Client
    class CoinsCombineRpcClient(TestWalletRpcClient):
        async def combine_coins(
            self,
            args: CombineCoins,
            tx_config: TXConfig,
            timelock_info: ConditionValidTimes,
        ) -> CombineCoinsResponse:
            self.add_to_log("combine_coins", (args, tx_config, timelock_info))
            return CombineCoinsResponse([STD_UTX], [STD_TX])

    inst_rpc_client = CoinsCombineRpcClient()  # pylint: disable=no-value-for-parameter
    test_rpc_clients.wallet_rpc_client = inst_rpc_client
    command_args = [
        "wallet",
        "coins",
        "combine",
        FINGERPRINT_ARG,
        "-i1",
        "--largest-first",
        "-m0.001",
        "--min-amount",
        "0.1",
        "--max-amount",
        "0.2",
        "--exclude-amount",
        "0.3",
        "--target-amount",
        "1",
        "--input-coin",
        bytes(32).hex(),
        "--valid-at",
        "100",
        "--expires-at",
        "150",
    ]
    # these are various things that should be in the output
    assert_list = [
        "Transactions would combine up to 500 coins",
        f"To get status, use command: chia wallet get_transaction -f {FINGERPRINT} -tx 0x{STD_TX.name.hex()}",
    ]
    run_cli_command_and_assert(capsys, root_dir, command_args, assert_list)
    expected_tx_config = TXConfig(
        min_coin_amount=uint64(100_000_000_000),
        max_coin_amount=uint64(200_000_000_000),
        excluded_coin_amounts=[uint64(300_000_000_000)],
        excluded_coin_ids=[],
        reuse_puzhash=False,
    )
    expected_request = CombineCoins(
        wallet_id=uint32(1),
        number_of_coins=uint16(500),
        largest_first=True,
        target_coin_ids=[bytes32([0] * 32)],
        target_coin_amount=uint64(1_000_000_000_000),
        fee=uint64(1_000_000_000),
        push=False,
    )
    expected_calls: logType = {
        "get_wallets": [(None,)],
        "get_synced": [()],
        "combine_coins": [
            (
                expected_request,
                expected_tx_config,
                test_condition_valid_times,
            ),
            (
                dataclasses.replace(expected_request, push=True),
                expected_tx_config,
                test_condition_valid_times,
            ),
        ],
    }
    test_rpc_clients.wallet_rpc_client.check_log(expected_calls)


def test_coins_split(capsys: object, get_test_cli_clients: Tuple[TestRpcClients, Path]) -> None:
    test_rpc_clients, root_dir = get_test_cli_clients

    # set RPC Client
    class CoinsSplitRpcClient(TestWalletRpcClient):
        async def split_coins(
            self, args: SplitCoins, tx_config: TXConfig, timelock_info: ConditionValidTimes
        ) -> SplitCoinsResponse:
            self.add_to_log("split_coins", (args, tx_config, timelock_info))
            return SplitCoinsResponse([STD_UTX], [STD_TX])

    inst_rpc_client = CoinsSplitRpcClient()  # pylint: disable=no-value-for-parameter
    test_rpc_clients.wallet_rpc_client = inst_rpc_client
    target_coin_id = get_bytes32(1)
    command_args = [
        "wallet",
        "coins",
        "split",
        FINGERPRINT_ARG,
        "-i1",
        "-m0.001",
        "-n10",
        "-a0.0000001",
        f"-t{target_coin_id.hex()}",
        "--valid-at",
        "100",
        "--expires-at",
        "150",
    ]
    # these are various things that should be in the output
    assert_list = [
        f"To get status, use command: chia wallet get_transaction -f {FINGERPRINT} -tx 0x{STD_TX.name.hex()}",
        "WARNING: The amount per coin: 1E-7 is less than the dust threshold: 1e-06.",
    ]
    run_cli_command_and_assert(capsys, root_dir, command_args, assert_list)
    expected_calls: logType = {
        "get_wallets": [(None,)],
        "get_synced": [()],
        "split_coins": [
            (
                SplitCoins(
                    wallet_id=uint32(1),
                    number_of_coins=uint16(10),
                    amount_per_coin=uint64(100_000),
                    target_coin_id=target_coin_id,
                    fee=uint64(1_000_000_000),
                    push=True,
                ),
                DEFAULT_TX_CONFIG,
                test_condition_valid_times,
            )
        ],
    }
    test_rpc_clients.wallet_rpc_client.check_log(expected_calls)
