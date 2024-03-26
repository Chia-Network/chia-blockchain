from __future__ import annotations

from pathlib import Path
from typing import List, Optional, Tuple

from chia_rs import Coin

from chia._tests.cmds.cmd_test_utils import TestRpcClients, TestWalletRpcClient, logType, run_cli_command_and_assert
from chia._tests.cmds.wallet.test_consts import FINGERPRINT, FINGERPRINT_ARG, get_bytes32
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_record import CoinRecord
from chia.util.ints import uint32, uint64
from chia.wallet.util.tx_config import DEFAULT_TX_CONFIG, CoinSelectionConfig, TXConfig

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
                    min_coin_amount=uint64(0), max_coin_amount=uint64(0), excluded_coin_amounts=[], excluded_coin_ids=[]
                ),
            )
        ],
    }
    test_rpc_clients.wallet_rpc_client.check_log(expected_calls)


def test_coins_combine(capsys: object, get_test_cli_clients: Tuple[TestRpcClients, Path]) -> None:
    test_rpc_clients, root_dir = get_test_cli_clients

    # set RPC Client
    class CoinsCombineRpcClient(TestWalletRpcClient):
        async def select_coins(
            self,
            amount: int,
            wallet_id: int,
            coin_selection_config: CoinSelectionConfig,
        ) -> List[Coin]:
            self.add_to_log("select_coins", (amount, wallet_id, coin_selection_config))
            return [
                Coin(get_bytes32(1), get_bytes32(2), uint64(100000000000)),
                Coin(get_bytes32(3), get_bytes32(4), uint64(200000000000)),
                Coin(get_bytes32(5), get_bytes32(6), uint64(300000000000)),
            ]

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
    ]
    # these are various things that should be in the output
    assert_list = [
        "Combining 2 coins.",
        f"To get status, use command: chia wallet get_transaction -f {FINGERPRINT} -tx 0x{get_bytes32(2).hex()}",
    ]
    amount_assert_list = [
        "Combining 3 coins.",
        f"To get status, use command: chia wallet get_transaction -f {FINGERPRINT} -tx 0x{get_bytes32(2).hex()}",
    ]
    run_cli_command_and_assert(capsys, root_dir, command_args, assert_list)
    run_cli_command_and_assert(capsys, root_dir, command_args + ["-a1"], amount_assert_list)
    expected_calls: logType = {
        "get_wallets": [(None,), (None,)],
        "get_synced": [(), ()],
        "get_spendable_coins": [
            (
                1,
                CoinSelectionConfig(
                    min_coin_amount=uint64(100000000000),
                    max_coin_amount=uint64(200000000000),
                    excluded_coin_amounts=[uint64(300000000000), uint64(0)],
                    excluded_coin_ids=[],
                ),
            )
        ],
        "select_coins": [
            (
                1001000000000,
                1,
                CoinSelectionConfig(
                    excluded_coin_ids=[],
                    min_coin_amount=uint64(100000000000),
                    max_coin_amount=uint64(200000000000),
                    excluded_coin_amounts=[uint64(300000000000), uint64(1000000000000)],
                ),
            )
        ],
        "get_next_address": [(1, False), (1, False)],
        "send_transaction_multi": [
            (
                1,
                [{"amount": 1469120000, "puzzle_hash": get_bytes32(0)}],
                TXConfig(
                    min_coin_amount=uint64(100000000000),
                    max_coin_amount=uint64(200000000000),
                    excluded_coin_amounts=[uint64(300000000000), uint64(0)],
                    excluded_coin_ids=[],
                    reuse_puzhash=False,
                ),
                [
                    Coin(get_bytes32(1), get_bytes32(2), uint64(1234560000)),
                    Coin(get_bytes32(3), get_bytes32(4), uint64(1234560000)),
                ],
                1000000000,
            ),
            (
                1,
                [{"amount": 599000000000, "puzzle_hash": get_bytes32(1)}],
                TXConfig(
                    min_coin_amount=uint64(100000000000),
                    max_coin_amount=uint64(200000000000),
                    excluded_coin_amounts=[uint64(300000000000), uint64(1000000000000)],
                    excluded_coin_ids=[],
                    reuse_puzhash=False,
                ),
                [
                    Coin(get_bytes32(1), get_bytes32(2), uint64(100000000000)),
                    Coin(get_bytes32(3), get_bytes32(4), uint64(200000000000)),
                    Coin(get_bytes32(5), get_bytes32(6), uint64(300000000000)),
                ],
                1000000000,
            ),
        ],
    }
    test_rpc_clients.wallet_rpc_client.check_log(expected_calls)


def test_coins_split(capsys: object, get_test_cli_clients: Tuple[TestRpcClients, Path]) -> None:
    test_rpc_clients, root_dir = get_test_cli_clients

    # set RPC Client
    class CoinsSplitRpcClient(TestWalletRpcClient):
        async def get_coin_records_by_names(
            self,
            names: List[bytes32],
            include_spent_coins: bool = True,
            start_height: Optional[int] = None,
            end_height: Optional[int] = None,
        ) -> List[CoinRecord]:
            self.add_to_log("get_coin_records_by_names", (names, include_spent_coins, start_height, end_height))
            return [
                CoinRecord(
                    Coin(get_bytes32(1), get_bytes32(2), uint64(100000000000)),
                    uint32(123456),
                    uint32(0),
                    False,
                    uint64(0),
                ),
            ]

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
    ]
    # these are various things that should be in the output
    assert_list = [
        f"To get status, use command: chia wallet get_transaction -f {FINGERPRINT} -tx 0x{get_bytes32(2).hex()}",
        "WARNING: The amount per coin: 1E-7 is less than the dust threshold: 1e-06.",
    ]
    run_cli_command_and_assert(capsys, root_dir, command_args, assert_list)
    expected_calls: logType = {
        "get_wallets": [(None,)],
        "get_synced": [()],
        "get_coin_records_by_names": [([target_coin_id], True, None, None)],
        "get_next_address": [(1, True) for i in range(10)],
        "send_transaction_multi": [
            (
                1,
                [{"amount": 100000, "puzzle_hash": bytes32([i] * 32)} for i in range(10)],
                DEFAULT_TX_CONFIG,
                [Coin(get_bytes32(1), get_bytes32(2), uint64(100000000000))],
                1000000000,
            )
        ],
    }
    test_rpc_clients.wallet_rpc_client.check_log(expected_calls)
