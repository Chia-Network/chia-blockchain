from __future__ import annotations

import asyncio
import sys
from typing import List, Optional, Sequence, Tuple

import click

from chia.cmds import options
from chia.cmds.cmd_classes import NeedsCoinSelectionConfig, NeedsWalletRPC, chia_command, option
from chia.cmds.cmds_util import tx_config_args, tx_out_cmd
from chia.cmds.param_types import AmountParamType, Bytes32ParamType, CliAmount
from chia.cmds.wallet_funcs import get_mojo_per_unit, get_wallet_type, print_balance
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.bech32m import encode_puzzle_hash
from chia.util.config import selected_network_address_prefix
from chia.util.ints import uint64
from chia.wallet.conditions import ConditionValidTimes
from chia.wallet.transaction_record import TransactionRecord


@click.group("coins", help="Manage your wallets coins")
@click.pass_context
def coins_cmd(ctx: click.Context) -> None:
    pass


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
    default=None,
)
@click.option(
    "-n",
    "--number-of-coins",
    type=int,
    default=500,
    show_default=True,
    help="The number of coins we are combining.",
)
@tx_config_args
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
@tx_out_cmd()
def combine_cmd(
    wallet_rpc_port: Optional[int],
    fingerprint: int,
    id: int,
    target_amount: Optional[CliAmount],
    min_coin_amount: CliAmount,
    amounts_to_exclude: Sequence[CliAmount],
    coins_to_exclude: Sequence[bytes32],
    number_of_coins: int,
    max_coin_amount: CliAmount,
    fee: uint64,
    input_coins: Sequence[bytes32],
    largest_first: bool,
    reuse: bool,
    push: bool,
    condition_valid_times: ConditionValidTimes,
) -> List[TransactionRecord]:
    from .coin_funcs import async_combine

    return asyncio.run(
        async_combine(
            wallet_rpc_port=wallet_rpc_port,
            fingerprint=fingerprint,
            wallet_id=id,
            fee=fee,
            max_coin_amount=max_coin_amount,
            min_coin_amount=min_coin_amount,
            excluded_amounts=amounts_to_exclude,
            coins_to_exclude=coins_to_exclude,
            reuse_puzhash=reuse,
            number_of_coins=number_of_coins,
            target_coin_amount=target_amount,
            target_coin_ids=input_coins,
            largest_first=largest_first,
            push=push,
            condition_valid_times=condition_valid_times,
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
    help="The amount of each newly created coin, in XCH or CAT units",
    type=AmountParamType(),
    required=True,
)
@click.option(
    "-t", "--target-coin-id", type=Bytes32ParamType(), required=True, help="The coin id of the coin we are splitting."
)
@tx_config_args
@tx_out_cmd()
def split_cmd(
    wallet_rpc_port: Optional[int],
    fingerprint: int,
    id: int,
    number_of_coins: int,
    fee: uint64,
    amount_per_coin: CliAmount,
    target_coin_id: bytes32,
    min_coin_amount: CliAmount,
    max_coin_amount: CliAmount,
    amounts_to_exclude: Sequence[CliAmount],
    coins_to_exclude: Sequence[bytes32],
    reuse: bool,
    push: bool,
    condition_valid_times: ConditionValidTimes,
) -> List[TransactionRecord]:
    from .coin_funcs import async_split

    return asyncio.run(
        async_split(
            wallet_rpc_port=wallet_rpc_port,
            fingerprint=fingerprint,
            wallet_id=id,
            fee=fee,
            max_coin_amount=max_coin_amount,
            min_coin_amount=min_coin_amount,
            excluded_amounts=amounts_to_exclude,
            coins_to_exclude=coins_to_exclude,
            reuse_puzhash=reuse,
            number_of_coins=number_of_coins,
            amount_per_coin=amount_per_coin,
            target_coin_id=target_coin_id,
            push=push,
            condition_valid_times=condition_valid_times,
        )
    )


def print_coins(
    target_string: str, coins: List[Tuple[Coin, str]], mojo_per_unit: int, addr_prefix: str, paginate: bool
) -> None:
    if len(coins) == 0:
        print("\tNo Coins.")
        return
    num_per_screen = 5 if paginate else len(coins)
    for i in range(0, len(coins), num_per_screen):
        for j in range(0, num_per_screen):
            if i + j >= len(coins):
                break
            coin, conf_height = coins[i + j]
            address = encode_puzzle_hash(coin.puzzle_hash, addr_prefix)
            amount_str = print_balance(coin.amount, mojo_per_unit, "", decimal_only=True)
            print(f"Coin ID: 0x{coin.name().hex()}")
            print(target_string.format(address, amount_str, conf_height))

        if i + num_per_screen >= len(coins):
            return None
        print("Press q to quit, or c to continue")
        while True:
            entered_key = sys.stdin.read(1)
            if entered_key.lower() == "q":
                return None
            elif entered_key.lower() == "c":
                break


@chia_command(
    coins_cmd,
    "list",
    "List all coins",
)
class ListCMD:
    rpc_info: NeedsWalletRPC
    coin_selection_config: NeedsCoinSelectionConfig
    id: int = option(
        "-i", "--id", help="Id of the wallet to use", type=int, default=1, show_default=True, required=True
    )
    show_unconfirmed: bool = option(
        "-u", "--show-unconfirmed", help="Separately display unconfirmed coins.", is_flag=True
    )
    paginate: Optional[bool] = option(
        "--paginate/--no-paginate",
        default=None,
        help="Prompt for each page of data.  Defaults to true for interactive consoles, otherwise false.",
    )

    async def run(self) -> None:
        async with self.rpc_info.wallet_rpc() as wallet_rpc:
            addr_prefix = selected_network_address_prefix(wallet_rpc.config)
            if self.paginate is None:
                paginate = sys.stdout.isatty()
            else:
                paginate = self.paginate
            try:
                wallet_type = await get_wallet_type(wallet_id=self.id, wallet_client=wallet_rpc.client)
                mojo_per_unit = get_mojo_per_unit(wallet_type)
            except LookupError:
                print(f"Wallet id: {self.id} not found.")
                return
            if not await wallet_rpc.client.get_synced():
                print("Wallet not synced. Please wait.")
                return
            conf_coins, unconfirmed_removals, unconfirmed_additions = await wallet_rpc.client.get_spendable_coins(
                wallet_id=self.id,
                coin_selection_config=self.coin_selection_config.load(mojo_per_unit),
            )
            print(f"There are a total of {len(conf_coins) + len(unconfirmed_additions)} coins in wallet {self.id}.")
            print(f"{len(conf_coins)} confirmed coins.")
            print(f"{len(unconfirmed_additions)} unconfirmed additions.")
            print(f"{len(unconfirmed_removals)} unconfirmed removals.")
            print("Confirmed coins:")
            print_coins(
                "\tAddress: {} Amount: {}, Confirmed in block: {}\n",
                [(cr.coin, str(cr.confirmed_block_index)) for cr in conf_coins],
                mojo_per_unit,
                addr_prefix,
                paginate,
            )
            if self.show_unconfirmed:
                print("\nUnconfirmed Removals:")
                print_coins(
                    "\tPrevious Address: {} Amount: {}, Confirmed in block: {}\n",
                    [(cr.coin, str(cr.confirmed_block_index)) for cr in unconfirmed_removals],
                    mojo_per_unit,
                    addr_prefix,
                    paginate,
                )
                print("\nUnconfirmed Additions:")
                print_coins(
                    "\tNew Address: {} Amount: {}, Not yet confirmed in a block.{}\n",
                    [(coin, "") for coin in unconfirmed_additions],
                    mojo_per_unit,
                    addr_prefix,
                    paginate,
                )
