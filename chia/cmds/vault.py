from __future__ import annotations

import asyncio
from collections.abc import Sequence
from typing import Optional

import click

from chia.cmds import options
from chia.cmds.cmds_util import timelock_args, tx_out_cmd
from chia.cmds.param_types import AmountParamType, Bytes32ParamType, CliAmount, cli_amount_none
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.ints import uint64
from chia.wallet.conditions import ConditionValidTimes
from chia.wallet.transaction_record import TransactionRecord


@click.group("vault", help="Manage your vault")
@click.pass_context
def vault_cmd(ctx: click.Context) -> None:
    pass


@vault_cmd.command("create", help="Create a new vault")
@click.option(
    "-wp",
    "--wallet-rpc-port",
    help="Set the port where the Wallet is hosting the RPC interface. See the rpc_port under wallet in config.yaml",
    type=int,
    default=None,
)
@options.create_fingerprint()
@click.option(
    "-pk",
    "--public-key",
    help="SECP public key",
    type=str,
    required=True,
)
@click.option(
    "-rk",
    "--recovery-public-key",
    help="BLS public key for vault recovery",
    type=str,
    required=False,
    default=None,
)
@click.option(
    "-rt",
    "--recovery-timelock",
    help="Timelock for vault recovery (in seconds)",
    type=int,
    required=False,
    default=None,
)
@click.option(
    "-i",
    "--hidden-puzzle-index",
    help="Starting index for hidden puzzle",
    type=int,
    required=False,
    default=0,
)
@options.create_fee()
@click.option("-n", "--name", help="Set the vault name", type=str)
@click.option(
    "-ma",
    "--min-coin-amount",
    help="Ignore coins worth less then this much XCH or CAT units",
    type=AmountParamType(),
    required=False,
    default=cli_amount_none,
)
@click.option(
    "-l",
    "--max-coin-amount",
    help="Ignore coins worth more then this much XCH or CAT units",
    type=AmountParamType(),
    required=False,
    default=cli_amount_none,
)
@click.option(
    "--exclude-coin",
    "coins_to_exclude",
    multiple=True,
    type=Bytes32ParamType(),
    help="Exclude this coin from being spent.",
)
@click.option(
    "--reuse",
    help="Reuse existing address for the change.",
    is_flag=True,
    default=False,
)
@tx_out_cmd()
def vault_create_cmd(
    wallet_rpc_port: Optional[int],
    fingerprint: int,
    public_key: str,
    recovery_public_key: Optional[str],
    recovery_timelock: Optional[int],
    hidden_puzzle_index: int,
    fee: uint64,
    name: Optional[str],
    min_coin_amount: CliAmount,
    max_coin_amount: CliAmount,
    coins_to_exclude: Sequence[bytes32],
    reuse: bool,
    push: bool,
    condition_valid_times: ConditionValidTimes,
) -> list[TransactionRecord]:
    from .vault_funcs import create_vault

    return asyncio.run(
        create_vault(
            wallet_rpc_port,
            fingerprint,
            public_key,
            recovery_public_key,
            recovery_timelock,
            hidden_puzzle_index,
            fee,
            name,
            min_coin_amount=min_coin_amount,
            max_coin_amount=max_coin_amount,
            excluded_coin_ids=coins_to_exclude,
            reuse_puzhash=True if reuse else None,
            push=push,
            condition_valid_times=condition_valid_times,
        )
    )


@vault_cmd.command("recover", help="Generate transactions for vault recovery")
@click.option(
    "-wp",
    "--wallet-rpc-port",
    help="Set the port where the Wallet is hosting the RPC interface. See the rpc_port under wallet in config.yaml",
    type=int,
    default=None,
)
@options.create_fingerprint()
@click.option("-i", "--wallet-id", help="Vault Wallet ID", type=int, required=True, default=1)
@click.option(
    "-pk",
    "--public-key",
    help="SECP public key",
    type=str,
    required=True,
)
@click.option(
    "-i",
    "--hidden-puzzle-index",
    help="Starting index for hidden puzzle",
    type=int,
    required=False,
    default=0,
)
@click.option(
    "-rk",
    "--recovery-public-key",
    help="BLS public key for vault recovery",
    type=str,
    required=False,
    default=None,
)
@click.option(
    "-rt",
    "--recovery-timelock",
    help="Timelock for vault recovery (in seconds)",
    type=int,
    required=False,
    default=None,
)
@click.option(
    "-ri",
    "--recovery-initiate-file",
    help="Provide a filename to store the recovery transactions",
    type=str,
    required=True,
    default="initiate_recovery.json",
)
@click.option(
    "-rf",
    "--recovery-finish-file",
    help="Provide a filename to store the recovery transactions",
    type=str,
    required=True,
    default="finish_recovery.json",
)
@click.option(
    "-ma",
    "--min-coin-amount",
    help="Ignore coins worth less then this much XCH or CAT units",
    type=AmountParamType(),
    required=False,
    default=cli_amount_none,
)
@click.option(
    "-l",
    "--max-coin-amount",
    help="Ignore coins worth more then this much XCH or CAT units",
    type=AmountParamType(),
    required=False,
    default=cli_amount_none,
)
@click.option(
    "--exclude-coin",
    "coins_to_exclude",
    multiple=True,
    type=Bytes32ParamType(),
    help="Exclude this coin from being spent.",
)
@click.option(
    "--reuse",
    help="Reuse existing address for the change.",
    is_flag=True,
    default=False,
)
@timelock_args()
def vault_recover_cmd(
    wallet_rpc_port: Optional[int],
    fingerprint: int,
    wallet_id: int,
    public_key: str,
    hidden_puzzle_index: int,
    recovery_public_key: Optional[str],
    recovery_timelock: Optional[int],
    recovery_initiate_file: str,
    recovery_finish_file: str,
    min_coin_amount: CliAmount,
    max_coin_amount: CliAmount,
    coins_to_exclude: Sequence[bytes32],
    reuse: bool,
    condition_valid_times: ConditionValidTimes,
) -> None:
    from .vault_funcs import recover_vault

    asyncio.run(
        recover_vault(
            wallet_rpc_port,
            fingerprint,
            wallet_id,
            public_key,
            hidden_puzzle_index,
            recovery_public_key,
            recovery_timelock,
            recovery_initiate_file,
            recovery_finish_file,
            min_coin_amount=min_coin_amount,
            max_coin_amount=max_coin_amount,
            excluded_coin_ids=coins_to_exclude,
            reuse_puzhash=True if reuse else None,
            condition_valid_times=condition_valid_times,
        )
    )
