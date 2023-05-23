from __future__ import annotations

import asyncio
from typing import List, Optional

import click

from chia.cmds.cmds_util import execute_with_wallet
from chia.util.config import load_config, selected_network_address_prefix


@click.group("coins", help="Manage your wallets coins")
@click.pass_context
def coins_cmd(ctx: click.Context) -> None:
    pass


@coins_cmd.command("list", help="List all coins")
@click.option(
    "-p",
    "--wallet-rpc-port",
    help="Set the port where the Wallet is hosting the RPC interface. See the rpc_port under wallet in config.yaml",
    type=int,
    default=None,
)
@click.option("-f", "--fingerprint", help="Set the fingerprint to specify which key to use", type=int)
@click.option("-i", "--id", help="Id of the wallet to use", type=int, default=1, show_default=True, required=True)
@click.option("-u", "--show-unconfirmed", help="Separately display unconfirmed coins.", is_flag=True)
@click.option(
    "--min-amount",
    help="Ignore coins worth less then this much XCH or CAT units",
    type=str,
    default="0",
)
@click.option(
    "--max-amount",
    help="Ignore coins worth more then this much XCH or CAT units",
    type=str,
    default="0",
)
@click.option(
    "--exclude-coin",
    "coins_to_exclude",
    multiple=True,
    help="prevent this coin from being included.",
)
@click.option(
    "--exclude-amount",
    "amounts_to_exclude",
    multiple=True,
    help="Exclude any coins with this XCH or CAT amount from being included.",
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
    min_amount: str,
    max_amount: str,
    coins_to_exclude: List[str],
    amounts_to_exclude: List[int],
    paginate: Optional[bool],
) -> None:
    config = load_config(ctx.obj["root_path"], "config.yaml", "wallet")
    address_prefix = selected_network_address_prefix(config)
    extra_params = {
        "id": id,
        "max_coin_amount": max_amount,
        "min_coin_amount": min_amount,
        "excluded_amounts": amounts_to_exclude,
        "excluded_coin_ids": coins_to_exclude,
        "addr_prefix": address_prefix,
        "show_unconfirmed": show_unconfirmed,
        "paginate": paginate,
    }
    from .coin_funcs import async_list

    asyncio.run(execute_with_wallet(wallet_rpc_port, fingerprint, extra_params, async_list))


@coins_cmd.command("combine", help="Combine dust coins")
@click.option(
    "-p",
    "--wallet-rpc-port",
    help="Set the port where the Wallet is hosting the RPC interface. See the rpc_port under wallet in config.yaml",
    type=int,
    default=None,
)
@click.option("-f", "--fingerprint", help="Set the fingerprint to specify which key to use", type=int)
@click.option("-i", "--id", help="Id of the wallet to use", type=int, default=1, show_default=True, required=True)
@click.option(
    "-a",
    "--target-amount",
    help="Select coins until this amount (in XCH or CAT) is reached. \
    Combine all selected coins into one coin, which will have a value of at least target-amount",
    type=str,
    default="0",
)
@click.option(
    "--min-amount",
    help="Ignore coins worth less then this much XCH or CAT units",
    type=str,
    default="0",
)
@click.option(
    "--exclude-amount",
    "amounts_to_exclude",
    multiple=True,
    help="Exclude any coins with this XCH or CAT amount from being included.",
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
    "--max-amount",
    help="Ignore coins worth more then this much XCH or CAT units",
    type=str,
    default="0",  # 0 means no limit
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
    "--input-coin",
    "input_coins",
    multiple=True,
    help="Only combine coins with these ids.",
)
@click.option(
    "--largest-first/--smallest-first",
    "largest_first",
    default=False,
    help="Sort coins from largest to smallest or smallest to largest.",
)
def combine_cmd(
    wallet_rpc_port: Optional[int],
    fingerprint: int,
    id: int,
    target_amount: str,
    min_amount: str,
    amounts_to_exclude: List[int],
    number_of_coins: int,
    max_amount: str,
    fee: str,
    input_coins: List[str],
    largest_first: bool,
) -> None:
    extra_params = {
        "id": id,
        "target_coin_amount": target_amount,
        "min_coin_amount": min_amount,
        "excluded_amounts": amounts_to_exclude,
        "number_of_coins": number_of_coins,
        "max_amount": max_amount,
        "fee": fee,
        "target_coin_ids": list(input_coins),
        "largest": largest_first,
    }
    from .coin_funcs import async_combine

    asyncio.run(execute_with_wallet(wallet_rpc_port, fingerprint, extra_params, async_combine))


@coins_cmd.command("split", help="Split up larger coins")
@click.option(
    "-p",
    "--wallet-rpc-port",
    help="Set the port where the Wallet is hosting the RPC interface. See the rpc_port under wallet in config.yaml",
    type=int,
    default=None,
)
@click.option("-f", "--fingerprint", help="Set the fingerprint to specify which key to use", type=int)
@click.option("-i", "--id", help="Id of the wallet to use", type=int, default=1, show_default=True, required=True)
@click.option(
    "-n",
    "--number-of-coins",
    type=int,
    help="The number of coins we are creating.",
    required=True,
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
@click.option("-t", "--target-coin-id", type=str, required=True, help="The coin id of the coin we are splitting.")
def split_cmd(
    wallet_rpc_port: Optional[int],
    fingerprint: int,
    id: int,
    number_of_coins: int,
    fee: str,
    amount_per_coin: str,
    target_coin_id: str,
) -> None:
    extra_params = {
        "id": id,
        "number_of_coins": number_of_coins,
        "fee": fee,
        "amount_per_coin": amount_per_coin,
        "target_coin_id": target_coin_id,
    }
    from .coin_funcs import async_split

    asyncio.run(execute_with_wallet(wallet_rpc_port, fingerprint, extra_params, async_split))
