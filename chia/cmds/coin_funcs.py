from __future__ import annotations

import sys
from decimal import Decimal
from typing import Dict, List, Optional, Sequence, Tuple, Union

from chia.cmds.cmds_util import CMDCoinSelectionConfigLoader, CMDTXConfigLoader, cli_confirm, get_wallet_client
from chia.cmds.units import units
from chia.cmds.wallet_funcs import get_mojo_per_unit, get_wallet_type, print_balance
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_record import CoinRecord
from chia.util.bech32m import decode_puzzle_hash, encode_puzzle_hash
from chia.util.config import selected_network_address_prefix
from chia.util.ints import uint64, uint128
from chia.wallet.transaction_record import TransactionRecord
from chia.wallet.util.wallet_types import WalletType


async def async_list(
    *,
    wallet_rpc_port: Optional[int],
    fingerprint: Optional[int],
    wallet_id: int,
    max_coin_amount: str,
    min_coin_amount: str,
    excluded_amounts: Sequence[str],
    excluded_coin_ids: Sequence[str],
    show_unconfirmed: bool,
    paginate: Optional[bool],
) -> None:
    async with get_wallet_client(wallet_rpc_port, fingerprint) as (wallet_client, _, config):
        addr_prefix = selected_network_address_prefix(config)
        if paginate is None:
            paginate = sys.stdout.isatty()
        try:
            wallet_type = await get_wallet_type(wallet_id=wallet_id, wallet_client=wallet_client)
            mojo_per_unit = get_mojo_per_unit(wallet_type)
        except LookupError:
            print(f"Wallet id: {wallet_id} not found.")
            return
        if not await wallet_client.get_synced():
            print("Wallet not synced. Please wait.")
            return
        conf_coins, unconfirmed_removals, unconfirmed_additions = await wallet_client.get_spendable_coins(
            wallet_id=wallet_id,
            coin_selection_config=CMDCoinSelectionConfigLoader(
                max_coin_amount=max_coin_amount,
                min_coin_amount=min_coin_amount,
                excluded_coin_amounts=list(excluded_amounts),
                excluded_coin_ids=list(excluded_coin_ids),
            ).to_coin_selection_config(mojo_per_unit),
        )
        print(f"There are a total of {len(conf_coins) + len(unconfirmed_additions)} coins in wallet {wallet_id}.")
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
        if show_unconfirmed:
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
            if entered_key == "q":
                return None
            elif entered_key == "c":
                break


async def async_combine(
    *,
    wallet_rpc_port: Optional[int],
    fingerprint: Optional[int],
    wallet_id: int,
    fee: Decimal,
    max_coin_amount: str,
    min_coin_amount: str,
    excluded_amounts: Sequence[str],
    # TODO: [add TXConfig args] add excluded_coin_ids
    number_of_coins: int,
    target_coin_amount: Decimal,
    target_coin_ids_str: Sequence[str],
    largest_first: bool,
) -> None:
    async with get_wallet_client(wallet_rpc_port, fingerprint) as (wallet_client, fingerprint, config):
        target_coin_ids: List[bytes32] = [bytes32.from_hexstr(coin_id) for coin_id in target_coin_ids_str]
        final_fee = uint64(int(fee * units["chia"]))
        if number_of_coins > 500:
            raise ValueError(f"{number_of_coins} coins is greater then the maximum limit of 500 coins.")
        try:
            wallet_type = await get_wallet_type(wallet_id=wallet_id, wallet_client=wallet_client)
            mojo_per_unit = get_mojo_per_unit(wallet_type)
        except LookupError:
            print(f"Wallet id: {wallet_id} not found.")
            return
        if not await wallet_client.get_synced():
            print("Wallet not synced. Please wait.")
            return
        is_xch: bool = wallet_type == WalletType.STANDARD_WALLET  # this lets us know if we are directly combining Chia

        tx_config = CMDTXConfigLoader(
            max_coin_amount=max_coin_amount,
            min_coin_amount=min_coin_amount,
            excluded_coin_amounts=[*excluded_amounts, str(target_coin_amount)],  # dont reuse coins of same amount.
            # TODO: [add TXConfig args] add excluded_coin_ids
        ).to_tx_config(mojo_per_unit, config, fingerprint)

        final_target_coin_amount = uint64(int(target_coin_amount * mojo_per_unit))

        if final_target_coin_amount != 0:  # if we have a set target, just use standard coin selection.
            removals: List[Coin] = await wallet_client.select_coins(
                amount=(final_target_coin_amount + final_fee) if is_xch else final_target_coin_amount,
                wallet_id=wallet_id,
                coin_selection_config=tx_config.coin_selection_config,
            )
        else:
            conf_coins, _, _ = await wallet_client.get_spendable_coins(
                wallet_id=wallet_id,
                coin_selection_config=tx_config.coin_selection_config,
            )
            if len(target_coin_ids) > 0:
                conf_coins = [cr for cr in conf_coins if cr.name in target_coin_ids]
            if len(conf_coins) == 0:
                print("No coins to combine.")
                return
            if len(conf_coins) == 1:
                print("Only one coin found, you need at least two coins to combine.")
                return
            if largest_first:
                conf_coins.sort(key=lambda r: r.coin.amount, reverse=True)
            else:
                conf_coins.sort(key=lambda r: r.coin.amount)  # sort the smallest first
            if number_of_coins < len(conf_coins):
                conf_coins = conf_coins[:number_of_coins]
            removals = [cr.coin for cr in conf_coins]
        print(f"Combining {len(removals)} coins.")
        cli_confirm("Would you like to Continue? (y/n): ")
        total_amount: uint128 = uint128(sum(coin.amount for coin in removals))
        if is_xch and total_amount - final_fee <= 0:
            print("Total amount is less than 0 after fee, exiting.")
            return
        target_ph: bytes32 = decode_puzzle_hash(await wallet_client.get_next_address(wallet_id, False))
        additions = [{"amount": (total_amount - final_fee) if is_xch else total_amount, "puzzle_hash": target_ph}]
        transaction: TransactionRecord = await wallet_client.send_transaction_multi(
            wallet_id, additions, tx_config, removals, final_fee
        )
        tx_id = transaction.name.hex()
        print(f"Transaction sent: {tx_id}")
        print(f"To get status, use command: chia wallet get_transaction -f {fingerprint} -tx 0x{tx_id}")


async def async_split(
    *,
    wallet_rpc_port: Optional[int],
    fingerprint: Optional[int],
    wallet_id: int,
    fee: Decimal,
    number_of_coins: int,
    amount_per_coin: Decimal,
    target_coin_id_str: str,
    # TODO: [add TXConfig args]
) -> None:
    async with get_wallet_client(wallet_rpc_port, fingerprint) as (wallet_client, fingerprint, config):
        final_fee = uint64(int(fee * units["chia"]))
        target_coin_id: bytes32 = bytes32.from_hexstr(target_coin_id_str)
        if number_of_coins > 500:
            print(f"{number_of_coins} coins is greater then the maximum limit of 500 coins.")
            return
        try:
            wallet_type = await get_wallet_type(wallet_id=wallet_id, wallet_client=wallet_client)
            mojo_per_unit = get_mojo_per_unit(wallet_type)
        except LookupError:
            print(f"Wallet id: {wallet_id} not found.")
            return
        if not await wallet_client.get_synced():
            print("Wallet not synced. Please wait.")
            return
        is_xch: bool = wallet_type == WalletType.STANDARD_WALLET  # this lets us know if we are directly spitting Chia
        final_amount_per_coin = uint64(int(amount_per_coin * mojo_per_unit))
        total_amount = final_amount_per_coin * number_of_coins
        if is_xch:
            total_amount += final_fee
        # get full coin record from name, and validate information about it.
        removal_coin_record: CoinRecord = (await wallet_client.get_coin_records_by_names([target_coin_id]))[0]
        if removal_coin_record.coin.amount < total_amount:
            print(
                f"Coin amount: {removal_coin_record.coin.amount / mojo_per_unit} "
                f"is less than the total amount of the split: {total_amount / mojo_per_unit}, exiting."
            )
            print("Try using a smaller fee or amount.")
            return
        additions: List[Dict[str, Union[uint64, bytes32]]] = []
        for i in range(number_of_coins):  # for readability.
            # we always use new addresses
            target_ph: bytes32 = decode_puzzle_hash(await wallet_client.get_next_address(wallet_id, new_address=True))
            additions.append({"amount": final_amount_per_coin, "puzzle_hash": target_ph})

        tx_config = CMDTXConfigLoader(
            # TODO: [add TXConfig args]
        ).to_tx_config(mojo_per_unit, config, fingerprint)

        transaction: TransactionRecord = await wallet_client.send_transaction_multi(
            wallet_id, additions, tx_config, [removal_coin_record.coin], final_fee
        )
        tx_id = transaction.name.hex()
        print(f"Transaction sent: {tx_id}")
        print(f"To get status, use command: chia wallet get_transaction -f {fingerprint} -tx 0x{tx_id}")
        dust_threshold = config.get("xch_spam_amount", 1000000)  # min amount per coin in mojo
        spam_filter_after_n_txs = config.get("spam_filter_after_n_txs", 200)  # how many txs to wait before filtering
        if final_amount_per_coin < dust_threshold and wallet_type == WalletType.STANDARD_WALLET:
            print(
                f"WARNING: The amount per coin: {amount_per_coin} is less than the dust threshold: "
                f"{dust_threshold / mojo_per_unit}. Some or all of the Coins "
                f"{'will' if number_of_coins > spam_filter_after_n_txs else 'may'} not show up in your wallet unless "
                f"you decrease the dust limit to below {final_amount_per_coin} mojos or disable it by setting it to 0."
            )
