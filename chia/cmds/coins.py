from __future__ import annotations

import dataclasses
import sys
from collections.abc import Sequence
from typing import Optional

import click

from chia.cmds.cmd_classes import (
    NeedsCoinSelectionConfig,
    NeedsWalletRPC,
    TransactionEndpoint,
    chia_command,
    option,
    transaction_endpoint_runner,
)
from chia.cmds.cmds_util import cli_confirm
from chia.cmds.param_types import AmountParamType, Bytes32ParamType, CliAmount
from chia.cmds.wallet_funcs import get_mojo_per_unit, get_wallet_type, print_balance
from chia.rpc.wallet_request_types import CombineCoins, SplitCoins
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.bech32m import encode_puzzle_hash
from chia.util.config import selected_network_address_prefix
from chia.util.ints import uint16, uint32, uint64
from chia.wallet.transaction_record import TransactionRecord
from chia.wallet.util.wallet_types import WalletType


@click.group("coins", help="Manage your wallets coins")
@click.pass_context
def coins_cmd(ctx: click.Context) -> None:
    pass


def print_coins(
    target_string: str, coins: list[tuple[Coin, str]], mojo_per_unit: int, addr_prefix: str, paginate: bool
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
            if not (await wallet_rpc.client.get_sync_status()).synced:
                print("Wallet not synced. Please wait.")
                return
            conf_coins, unconfirmed_removals, unconfirmed_additions = await wallet_rpc.client.get_spendable_coins(
                wallet_id=self.id,
                coin_selection_config=self.coin_selection_config.load_coin_selection_config(mojo_per_unit),
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


@chia_command(
    coins_cmd,
    "combine",
    "Combine dust coins",
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
        "input_coins",
        multiple=True,
        help="Only combine coins with these ids.",
        type=Bytes32ParamType(),
    )
    largest_first: bool = option(
        "--largest-first/--smallest-first",
        "largest_first",
        default=False,
        help="Sort coins from largest to smallest or smallest to largest.",
    )

    @transaction_endpoint_runner
    async def run(self) -> list[TransactionRecord]:
        async with self.rpc_info.wallet_rpc() as wallet_rpc:
            try:
                wallet_type = await get_wallet_type(wallet_id=self.id, wallet_client=wallet_rpc.client)
                mojo_per_unit = get_mojo_per_unit(wallet_type)
            except LookupError:
                print(f"Wallet id: {self.id} not found.")
                return []
            if not (await wallet_rpc.client.get_sync_status()).synced:
                print("Wallet not synced. Please wait.")
                return []

            tx_config = self.tx_config_loader.load_tx_config(mojo_per_unit, wallet_rpc.config, wallet_rpc.fingerprint)

            final_target_coin_amount = (
                None if self.target_amount is None else self.target_amount.convert_amount(mojo_per_unit)
            )

            combine_request = CombineCoins(
                wallet_id=uint32(self.id),
                target_coin_amount=final_target_coin_amount,
                number_of_coins=uint16(self.number_of_coins),
                target_coin_ids=list(self.input_coins),
                largest_first=self.largest_first,
                fee=self.fee,
                push=False,
            )
            resp = await wallet_rpc.client.combine_coins(
                combine_request,
                tx_config,
                timelock_info=self.load_condition_valid_times(),
            )

            print(f"Transactions would combine up to {self.number_of_coins} coins.")
            if self.push:
                cli_confirm("Would you like to Continue? (y/n): ")
                resp = await wallet_rpc.client.combine_coins(
                    dataclasses.replace(combine_request, push=True),
                    tx_config,
                    timelock_info=self.load_condition_valid_times(),
                )
                for tx in resp.transactions:
                    print(f"Transaction sent: {tx.name}")
                    print(
                        "To get status, use command: chia wallet get_transaction "
                        f"-f {wallet_rpc.fingerprint} -tx 0x{tx.name}"
                    )

            return resp.transactions


@chia_command(
    coins_cmd,
    "split",
    "Split up larger coins",
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
            try:
                wallet_type = await get_wallet_type(wallet_id=self.id, wallet_client=wallet_rpc.client)
                mojo_per_unit = get_mojo_per_unit(wallet_type)
            except LookupError:
                print(f"Wallet id: {self.id} not found.")
                return []
            if not (await wallet_rpc.client.get_sync_status()).synced:
                print("Wallet not synced. Please wait.")
                return []

            final_amount_per_coin = self.amount_per_coin.convert_amount(mojo_per_unit)

            tx_config = self.tx_config_loader.load_tx_config(mojo_per_unit, wallet_rpc.config, wallet_rpc.fingerprint)

            transactions: list[TransactionRecord] = (
                await wallet_rpc.client.split_coins(
                    SplitCoins(
                        wallet_id=uint32(self.id),
                        number_of_coins=uint16(self.number_of_coins),
                        amount_per_coin=uint64(final_amount_per_coin),
                        target_coin_id=self.target_coin_id,
                        fee=self.fee,
                        push=self.push,
                    ),
                    tx_config=tx_config,
                    timelock_info=self.load_condition_valid_times(),
                )
            ).transactions

            if self.push:
                for tx in transactions:
                    print(f"Transaction sent: {tx.name}")
                    print(
                        "To get status, use command: "
                        f"chia wallet get_transaction -f {wallet_rpc.fingerprint} -tx 0x{tx.name}"
                    )
            dust_threshold = wallet_rpc.config.get("xch_spam_amount", 1000000)  # min amount per coin in mojo
            spam_filter_after_n_txs = wallet_rpc.config.get(
                "spam_filter_after_n_txs", 200
            )  # how many txs to wait before filtering
            if final_amount_per_coin < dust_threshold and wallet_type == WalletType.STANDARD_WALLET:
                print(
                    f"WARNING: The amount per coin: {self.amount_per_coin.amount} is less than the dust threshold: "
                    f"{dust_threshold / (1 if self.amount_per_coin.mojos else mojo_per_unit)}. "
                    "Some or all of the Coins "
                    f"{'will' if self.number_of_coins > spam_filter_after_n_txs else 'may'} "
                    "not show up in your wallet unless "
                    f"you decrease the dust limit to below {final_amount_per_coin} "
                    "mojos or disable it by setting it to 0."
                )

            return transactions
