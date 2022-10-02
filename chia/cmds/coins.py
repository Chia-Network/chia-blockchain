from __future__ import annotations

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
    "-a",
    "--min-coin-amount",
    help="Ignore coins worth less then this much XCH or CAT units",
    type=str,
    default="0",
)
@click.option(
    "-l",
    "--max-coin-amount",
    help="Ignore coins worth more then this much XCH or CAT units",
    type=str,
    default="0",
)
@click.option(
    "-e",
    "--excluded-coin-ids",
    multiple=True,
    help="prevent this coin from being included.",
)
@click.option(
    "-x",
    "--excluded-coin-amounts",
    multiple=True,
    help="Exclude any coins with this amount from being included.",
)
@click.option(
    "--paginate/--no-paginate",
    default=None,
    help="Prompt for each page of data.  Defaults to true for interactive consoles, otherwise false.",
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
    paginate: Optional[bool],
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
        "paginate": paginate,
    }
    from .coin_funcs import async_list

    asyncio.run(execute_with_wallet(wallet_rpc_port, fingerprint, extra_params, async_list))


@coins_cmd.command("combine", short_help="Combine dust coins")
@click.option(
    "-p",
    "--wallet-rpc-port",
    help="Set the port where the Wallet is hosting the RPC interface. See the rpc_port under wallet in config.yaml",
    type=int,
    default=None,
)
@click.option("-f", "--fingerprint", help="Set the fingerprint to specify which wallet to use", type=int)
@click.option("-i", "--id", help="Id of the wallet to use", type=int, default=1, show_default=True, required=True)
@click.option(
    "-b",
    "--min-coin-amount",
    help="Ignore coins worth less then this much XCH or CAT units",
    type=str,
    default="0",
)
@click.option(
    "-a",
    "--excluded-coin-amounts",
    multiple=True,
    help="Exclude any coins with this amount from being included.",
)
@click.option(
    "-n",
    "--number-of-coins",
    type=int,
    default=500,
    show_default=True,
    help="The number of coins we are combining.",
)
@click.option(
    "-x",
    "--max-dust-amount",
    help="Ignore coins worth more then this much XCH or CAT units",
    type=str,
    show_default=True,
    default="0.000001000000",  # 1000000 mojo
)
@click.option(
    "-m",
    "--fee",
    help="Set the fees for the transaction, in XCH",
    type=str,
    default="0",
    show_default=True,
    required=True,
)
@click.option(
    "-t",
    "--target_coin_ids",
    multiple=True,
    help="Only combine coins with these ids.",
)
@click.option(
    "-l",
    "--largest_coins_first",
    help="Sort coins from largest to smallest instead of smallest to largest.",
    is_flag=True,
)
def combine_cmd(
    wallet_rpc_port: Optional[int],
    fingerprint: int,
    id: int,
    min_coin_amount: str,
    excluded_coin_amounts: Tuple[int],
    number_of_coins: int,
    max_dust_amount: str,
    fee: str,
    target_coin_ids: Tuple[str],
    largest_coins_first: bool,
) -> None:
    extra_params = {
        "id": id,
        "min_coin_amount": min_coin_amount,
        "excluded_amounts": excluded_coin_amounts,
        "number_of_coins": number_of_coins,
        "max_dust_amount": max_dust_amount,
        "fee": fee,
        "target_coin_ids": list(target_coin_ids),
        "largest": largest_coins_first,
    }
    from .coin_funcs import async_combine

    asyncio.run(execute_with_wallet(wallet_rpc_port, fingerprint, extra_params, async_combine))


@coins_cmd.command("split", short_help="Split up larger coins")
@click.option(
    "-p",
    "--wallet-rpc-port",
    help="Set the port where the Wallet is hosting the RPC interface. See the rpc_port under wallet in config.yaml",
    type=int,
    default=None,
)
@click.option("-f", "--fingerprint", help="Set the fingerprint to specify which wallet to use", type=int)
@click.option("-i", "--id", help="Id of the wallet to use", type=int, default=1, show_default=True, required=True)
@click.option(
    "-n",
    "--number-of-coins",
    type=int,
    help="The number of coins we are creating.",
)
@click.option(
    "-m",
    "--fee",
    help="Set the fees for the transaction, in XCH",
    type=str,
    default="0",
    show_default=True,
    required=True,
)
@click.option(
    "-a",
    "--amount-per-coin",
    help="The amount of each newly created coin, in XCH",
    type=str,
    required=True,
)
@click.option("-u", "--unique_addresses", is_flag=True, help="Generate a new address for each coin.")
@click.option("-t", "--target-coin-id", type=str, required=True, help="The coin id of the coin we are splitting.")
def split_cmd(
    wallet_rpc_port: Optional[int],
    fingerprint: int,
    id: int,
    number_of_coins: int,
    fee: str,
    amount_per_coin: str,
    unique_addresses: bool,
    target_coin_id: str,
) -> None:
    extra_params = {
        "id": id,
        "number_of_coins": number_of_coins,
        "fee": fee,
        "amount_per_coin": amount_per_coin,
        "unique_addresses": unique_addresses,
        "target_coin_id": target_coin_id,
    }
    from .coin_funcs import async_split

    asyncio.run(execute_with_wallet(wallet_rpc_port, fingerprint, extra_params, async_split))
