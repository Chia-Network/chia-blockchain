from __future__ import annotations

import asyncio
from decimal import Decimal
from typing import Optional, Sequence

import click

from chia.cmds import options
from chia.cmds.plotnft import validate_fee


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
@click.option(
    "-m",
    "--fee",
    help="Set the fees per transaction, in XCH.",
    type=str,
    default="0",
    show_default=True,
    callback=validate_fee,
)
@click.option("-n", "--name", help="Set the vault name", type=str)
@click.option(
    "-ma",
    "--min-coin-amount",
    help="Ignore coins worth less then this much XCH or CAT units",
    type=str,
    required=False,
    default="0",
)
@click.option(
    "-l",
    "--max-coin-amount",
    help="Ignore coins worth more then this much XCH or CAT units",
    type=str,
    required=False,
    default=None,
)
@click.option(
    "--exclude-coin",
    "coins_to_exclude",
    multiple=True,
    help="Exclude this coin from being spent.",
)
@click.option(
    "--reuse",
    help="Reuse existing address for the change.",
    is_flag=True,
    default=False,
)
def vault_create_cmd(
    wallet_rpc_port: Optional[int],
    fingerprint: int,
    public_key: str,
    recovery_public_key: Optional[str],
    recovery_timelock: Optional[int],
    hidden_puzzle_index: Optional[int],
    fee: str,
    name: Optional[str],
    min_coin_amount: str,
    max_coin_amount: Optional[str],
    coins_to_exclude: Sequence[str],
    reuse: bool,
) -> None:
    from .vault_funcs import create_vault

    if hidden_puzzle_index is None:
        hidden_puzzle_index = 0

    asyncio.run(
        create_vault(
            wallet_rpc_port,
            fingerprint,
            public_key,
            recovery_public_key,
            recovery_timelock,
            hidden_puzzle_index,
            Decimal(fee),
            name,
            min_coin_amount=min_coin_amount,
            max_coin_amount=max_coin_amount,
            excluded_coin_ids=coins_to_exclude,
            reuse_puzhash=True if reuse else None,
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
    type=str,
    required=False,
    default="0",
)
@click.option(
    "-l",
    "--max-coin-amount",
    help="Ignore coins worth more then this much XCH or CAT units",
    type=str,
    required=False,
    default=None,
)
@click.option(
    "--exclude-coin",
    "coins_to_exclude",
    multiple=True,
    help="Exclude this coin from being spent.",
)
@click.option(
    "--reuse",
    help="Reuse existing address for the change.",
    is_flag=True,
    default=False,
)
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
    min_coin_amount: str,
    max_coin_amount: Optional[str],
    coins_to_exclude: Sequence[str],
    reuse: bool,
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
        )
    )
