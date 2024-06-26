from __future__ import annotations

import asyncio
from typing import List, Optional, Sequence

import click

from chia.cmds import options
from chia.cmds.cmds_util import tx_out_cmd
from chia.cmds.param_types import AmountParamType, Bytes32ParamType, CliAmount, cli_amount_none
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.ints import uint64
from chia.wallet.transaction_record import TransactionRecord


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
@options.create_fingerprint()
@click.option("-i", "--id", help="Id of the wallet to use", type=int, default=1, show_default=True, required=True)
@click.option("-u", "--show-unconfirmed", help="Separately display unconfirmed coins.", is_flag=True)
@click.option(
    "--min-amount",
    help="Ignore coins worth less then this much XCH or CAT units",
    type=AmountParamType(),
    default=cli_amount_none,
)
@click.option(
    "--max-amount",
    help="Ignore coins worth more then this much XCH or CAT units",
    type=AmountParamType(),
    default=cli_amount_none,
)
@click.option(
    "--exclude-coin",
    "coins_to_exclude",
    multiple=True,
    help="prevent this coin from being included.",
    type=Bytes32ParamType(),
)
@click.option(
    "--exclude-amount",
    "amounts_to_exclude",
    multiple=True,
    type=AmountParamType(),
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
    min_amount: CliAmount,
    max_amount: CliAmount,
    coins_to_exclude: Sequence[bytes32],
    amounts_to_exclude: Sequence[CliAmount],
    paginate: Optional[bool],
) -> None:
    from .coin_funcs import async_list

    asyncio.run(
        async_list(
            wallet_rpc_port=wallet_rpc_port,
            fingerprint=fingerprint,
            wallet_id=id,
            max_coin_amount=max_amount,
            min_coin_amount=min_amount,
            excluded_amounts=amounts_to_exclude,
            excluded_coin_ids=coins_to_exclude,
            show_unconfirmed=show_unconfirmed,
            paginate=paginate,
        )
    )


@coins_cmd.command("combine", help="Combine dust coins")
@click.option(
    "-p",
    "--wallet-rpc-port",
    help="Set the port where the Wallet is hosting the RPC interface. See the rpc_port under wallet in config.yaml",
    type=int,
    default=None,
)
@options.create_fingerprint()
@click.option("-i", "--id", help="Id of the wallet to use", type=int, default=1, show_default=True, required=True)
@click.option(
    "-a",
    "--target-amount",
    help="Select coins until this amount (in XCH or CAT) is reached. \
    Combine all selected coins into one coin, which will have a value of at least target-amount",
    type=AmountParamType(),
    default=CliAmount(mojos=True, amount=uint64(0)),
)
@click.option(
    "--min-amount",
    help="Ignore coins worth less then this much XCH or CAT units",
    type=AmountParamType(),
    default=cli_amount_none,
)
@click.option(
    "--exclude-amount",
    "amounts_to_exclude",
    multiple=True,
    type=AmountParamType(),
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
    type=AmountParamType(),
    default=cli_amount_none,
)
@options.create_fee()
@click.option(
    "--input-coin",
    "input_coins",
    multiple=True,
    help="Only combine coins with these ids.",
    type=Bytes32ParamType(),
)
@click.option(
    "--largest-first/--smallest-first",
    "largest_first",
    default=False,
    help="Sort coins from largest to smallest or smallest to largest.",
)
@tx_out_cmd
def combine_cmd(
    wallet_rpc_port: Optional[int],
    fingerprint: int,
    id: int,
    target_amount: CliAmount,
    min_amount: CliAmount,
    amounts_to_exclude: Sequence[CliAmount],
    number_of_coins: int,
    max_amount: CliAmount,
    fee: uint64,
    input_coins: Sequence[bytes32],
    largest_first: bool,
    push: bool,
) -> List[TransactionRecord]:
    from .coin_funcs import async_combine

    return asyncio.run(
        async_combine(
            wallet_rpc_port=wallet_rpc_port,
            fingerprint=fingerprint,
            wallet_id=id,
            fee=fee,
            max_coin_amount=max_amount,
            min_coin_amount=min_amount,
            excluded_amounts=amounts_to_exclude,
            number_of_coins=number_of_coins,
            target_coin_amount=target_amount,
            target_coin_ids=input_coins,
            largest_first=largest_first,
            push=push,
        )
    )


@coins_cmd.command("split", help="Split up larger coins")
@click.option(
    "-p",
    "--wallet-rpc-port",
    help="Set the port where the Wallet is hosting the RPC interface. See the rpc_port under wallet in config.yaml",
    type=int,
    default=None,
)
@options.create_fingerprint()
@click.option("-i", "--id", help="Id of the wallet to use", type=int, default=1, show_default=True, required=True)
@click.option(
    "-n",
    "--number-of-coins",
    type=int,
    help="The number of coins we are creating.",
    required=True,
)
@options.create_fee()
@click.option(
    "-a",
    "--amount-per-coin",
    help="The amount of each newly created coin, in XCH",
    type=AmountParamType(),
    required=True,
)
@click.option("-t", "--target-coin-id", type=str, required=True, help="The coin id of the coin we are splitting.")
@tx_out_cmd
def split_cmd(
    wallet_rpc_port: Optional[int],
    fingerprint: int,
    id: int,
    number_of_coins: int,
    fee: uint64,
    amount_per_coin: CliAmount,
    target_coin_id: str,
    push: bool,
) -> List[TransactionRecord]:
    from .coin_funcs import async_split

    return asyncio.run(
        async_split(
            wallet_rpc_port=wallet_rpc_port,
            fingerprint=fingerprint,
            wallet_id=id,
            fee=fee,
            number_of_coins=number_of_coins,
            amount_per_coin=amount_per_coin,
            target_coin_id_str=target_coin_id,
            push=push,
        )
    )
