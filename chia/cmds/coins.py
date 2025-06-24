from __future__ import annotations

from collections.abc import Sequence
from typing import Optional

import click
from chia_rs.sized_bytes import bytes32

from chia.cmds.cmd_classes import (
    chia_command,
    option,
)
from chia.cmds.cmd_helpers import (
    NeedsCoinSelectionConfig,
    NeedsWalletRPC,
    TransactionEndpoint,
    transaction_endpoint_runner,
)
from chia.cmds.param_types import AmountParamType, Bytes32ParamType, CliAmount
from chia.wallet.transaction_record import TransactionRecord


@click.group("coins", help="Manage your wallets coins")
@click.pass_context
def coins_cmd(ctx: click.Context) -> None:
    pass


@chia_command(
    group=coins_cmd,
    name="list",
    short_help="List all coins",
    help="List all coins",
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
            from chia.cmds.coin_funcs import async_list

            await async_list(
                client_info=wallet_rpc,
                wallet_id=self.id,
                max_coin_amount=self.coin_selection_config.max_coin_amount,
                min_coin_amount=self.coin_selection_config.min_coin_amount,
                excluded_amounts=self.coin_selection_config.amounts_to_exclude,
                excluded_coin_ids=self.coin_selection_config.coins_to_exclude,
                show_unconfirmed=self.show_unconfirmed,
                paginate=self.paginate,
            )


@chia_command(
    group=coins_cmd,
    name="combine",
    short_help="Combine dust coins",
    help="Combine dust coins",
)
class CombineCMD(TransactionEndpoint):
    id: int = option(
        "-i", "--id", help="Id of the wallet to use", type=int, default=1, show_default=True, required=True
    )
    target_amount: Optional[CliAmount] = option(
        "-a",
        "--target-amount",
        help="Select coins until this amount (in XCH or CAT) is reached. \
        Combine all selected coins into one coin, which will have a value of at least target-amount",
        type=AmountParamType(),
        default=None,
    )
    number_of_coins: int = option(
        "-n",
        "--number-of-coins",
        type=int,
        default=500,
        show_default=True,
        help="The number of coins we are combining.",
    )
    input_coins: Sequence[bytes32] = option(
        "--input-coin",
        multiple=True,
        help="Only combine coins with these ids.",
        type=Bytes32ParamType(),
    )
    largest_first: bool = option(
        "--largest-first/--smallest-first",
        default=False,
        help="Sort coins from largest to smallest or smallest to largest.",
    )
    override: bool = option(
        "--override", help="Submits transaction without checking for unusual values", is_flag=True, default=False
    )

    @transaction_endpoint_runner
    async def run(self) -> list[TransactionRecord]:
        async with self.rpc_info.wallet_rpc() as wallet_rpc:
            from chia.cmds.coin_funcs import async_combine

            return await async_combine(
                client_info=wallet_rpc,
                wallet_id=self.id,
                fee=self.fee,
                max_coin_amount=self.tx_config_loader.max_coin_amount,
                min_coin_amount=self.tx_config_loader.min_coin_amount,
                excluded_amounts=self.tx_config_loader.amounts_to_exclude,
                coins_to_exclude=self.tx_config_loader.coins_to_exclude,
                reuse_puzhash=self.tx_config_loader.reuse,
                number_of_coins=self.number_of_coins,
                target_coin_amount=self.target_amount,
                target_coin_ids=self.input_coins,
                largest_first=self.largest_first,
                push=self.push,
                condition_valid_times=self.load_condition_valid_times(),
                override=self.override,
            )


@chia_command(
    group=coins_cmd,
    name="split",
    short_help="Split up larger coins",
    help="Split up larger coins",
)
class SplitCMD(TransactionEndpoint):
    id: int = option(
        "-i", "--id", help="Id of the wallet to use", type=int, default=1, show_default=True, required=True
    )
    number_of_coins: int = option(
        "-n",
        "--number-of-coins",
        type=int,
        help="The number of coins we are creating.",
        required=True,
    )
    amount_per_coin: CliAmount = option(
        "-a",
        "--amount-per-coin",
        help="The amount of each newly created coin, in XCH or CAT units",
        type=AmountParamType(),
        required=True,
    )
    target_coin_id: bytes32 = option(
        "-t",
        "--target-coin-id",
        type=Bytes32ParamType(),
        required=True,
        help="The coin id of the coin we are splitting.",
    )

    @transaction_endpoint_runner
    async def run(self) -> list[TransactionRecord]:
        async with self.rpc_info.wallet_rpc() as wallet_rpc:
            from chia.cmds.coin_funcs import async_split

            return await async_split(
                client_info=wallet_rpc,
                wallet_id=self.id,
                fee=self.fee,
                max_coin_amount=self.tx_config_loader.max_coin_amount,
                min_coin_amount=self.tx_config_loader.min_coin_amount,
                excluded_amounts=self.tx_config_loader.amounts_to_exclude,
                coins_to_exclude=self.tx_config_loader.coins_to_exclude,
                reuse_puzhash=self.tx_config_loader.reuse,
                number_of_coins=self.number_of_coins,
                amount_per_coin=self.amount_per_coin,
                target_coin_id=self.target_coin_id,
                push=self.push,
                condition_valid_times=self.load_condition_valid_times(),
            )
