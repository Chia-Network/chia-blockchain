import asyncio
from typing import Optional, Tuple

import click

from chia.cmds.cmds_util import execute_with_wallet
from chia.util.config import load_config, selected_network_address_prefix


@click.group("coins", short_help="Manage your wallets coins")
@click.pass_context
def coins_cmd(ctx: click.Context) -> None:
    pass


@coins_cmd.command("list", short_help="List all coins")
@click.option(
    "-p",
    "--wallet-rpc-port",
    help="Set the port where the Wallet is hosting the RPC interface. See the rpc_port under wallet in config.yaml",
    type=int,
    default=None,
)
@click.option("-f", "--fingerprint", help="Set the fingerprint to specify which wallet to use", type=int)
@click.option("-i", "--id", help="Id of the wallet to use", type=int, default=1, show_default=True, required=True)
@click.option("-u", "--show_unconfirmed", help="Separately display unconfirmed coins.", is_flag=True)
@click.option(
    "-m",
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
    default="0",
)
@click.option(
    "-e",
    "--excluded-coin-ids",
    multiple=True,
    help="prevent this coin from being included.",
)
@click.option(
    "-a",
    "--excluded-coin-amounts",
    multiple=True,
    help="Exclude any coins with this amount from being included.",
)
@click.pass_context
def list_cmd(
    ctx: click.Context,
    wallet_rpc_port: Optional[int],
    fingerprint: int,
    id: int,
    show_unconfirmed: bool,
    min_coin_amount: str,
    max_coin_amount: str,
    excluded_coin_ids: Tuple[str],
    excluded_coin_amounts: Tuple[int],
) -> None:
    config = load_config(ctx.obj["root_path"], "config.yaml", "wallet")
    address_prefix = selected_network_address_prefix(config)
    extra_params = {
        "id": id,
        "max_coin_amount": max_coin_amount,
        "min_coin_amount": min_coin_amount,
        "excluded_amounts": excluded_coin_amounts,
        "excluded_coin_ids": list(excluded_coin_ids),
        "addr_prefix": address_prefix,
        "show_unconfirmed": show_unconfirmed,
    }
    from .coin_funcs import async_list

    asyncio.run(execute_with_wallet(wallet_rpc_port, fingerprint, extra_params, async_list))
