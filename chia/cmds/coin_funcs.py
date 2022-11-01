from __future__ import annotations

import sys
from decimal import Decimal
from typing import Any, Dict, List, Tuple, Union

from chia.cmds.wallet_funcs import get_mojo_per_unit, get_wallet_type, print_balance
from chia.rpc.wallet_rpc_client import WalletRpcClient
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_record import CoinRecord
from chia.util.bech32m import decode_puzzle_hash, encode_puzzle_hash
from chia.util.ints import uint64, uint128
from chia.wallet.transaction_record import TransactionRecord


async def async_list(args: Dict[str, Any], wallet_client: WalletRpcClient, fingerprint: int) -> None:
    wallet_id: int = args["id"]
    min_coin_amount = Decimal(args["min_coin_amount"])
    max_coin_amount = Decimal(args["max_coin_amount"])
    excluded_coin_ids = args["excluded_coin_ids"]
    excluded_amounts = args["excluded_amounts"]
    addr_prefix = args["addr_prefix"]
    show_unconfirmed = args["show_unconfirmed"]
    paginate = args["paginate"]
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
    final_min_coin_amount: uint64 = uint64(int(min_coin_amount * mojo_per_unit))
    final_max_coin_amount: uint64 = uint64(int(max_coin_amount * mojo_per_unit))
    final_excluded_amounts: List[uint64] = [uint64(int(amount * mojo_per_unit)) for amount in excluded_amounts]
    conf_coins, unconfirmed_removals, unconfirmed_additions = await wallet_client.get_spendable_coins(
        wallet_id=wallet_id,
        max_coin_amount=final_max_coin_amount,
        min_coin_amount=final_min_coin_amount,
        excluded_amounts=final_excluded_amounts,
        excluded_coin_ids=excluded_coin_ids,
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
            amount_str = print_balance(coin.amount, mojo_per_unit, addr_prefix)
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


async def async_combine(args: Dict[str, Any], wallet_client: WalletRpcClient, fingerprint: int) -> None:
    wallet_id: int = args["id"]
    min_coin_amount = Decimal(args["min_coin_amount"])
    excluded_amounts = args["excluded_amounts"]
    number_of_coins = args["number_of_coins"]
    max_dust_amount = Decimal(args["max_dust_amount"])
    target_coin_ids: List[bytes32] = [bytes32.from_hexstr(coin_id) for coin_id in args["target_coin_ids"]]
    largest = bool(args["largest"])
    fee = Decimal(args["fee"])
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
    final_max_dust_amount = uint64(int(max_dust_amount * mojo_per_unit)) if not target_coin_ids else uint64(0)
    final_min_coin_amount: uint64 = uint64(int(min_coin_amount * mojo_per_unit))
    final_excluded_amounts: List[uint64] = [uint64(int(amount * mojo_per_unit)) for amount in excluded_amounts]
    final_fee = uint64(int(fee * mojo_per_unit))
    conf_coins, _, _ = await wallet_client.get_spendable_coins(
        wallet_id=wallet_id,
        max_coin_amount=final_max_dust_amount,
        min_coin_amount=final_min_coin_amount,
        excluded_amounts=final_excluded_amounts,
    )
    if len(target_coin_ids) > 0:
        conf_coins = [cr for cr in conf_coins if cr.name in target_coin_ids]
    if len(conf_coins) <= 1:
        print("No coins to combine.")
        return
    if largest:
        conf_coins.sort(key=lambda r: r.coin.amount, reverse=True)
    else:
        conf_coins.sort(key=lambda r: r.coin.amount)  # sort the smallest first
    if number_of_coins < len(conf_coins):
        conf_coins = conf_coins[:number_of_coins]
    print(f"Combining {len(conf_coins)} coins.")
    if input("Would you like to Continue? (y/n): ") != "y":
        return
    removals: List[Coin] = [cr.coin for cr in conf_coins]
    total_amount: uint128 = uint128(sum(coin.amount for coin in removals))
    if total_amount - final_fee <= 0:
        print("Total amount is less than 0 after fee, exiting.")
        return
    target_ph: bytes32 = decode_puzzle_hash(await wallet_client.get_next_address(str(wallet_id), False))
    additions = [{"amount": total_amount - final_fee, "puzzle_hash": target_ph}]
    transaction: TransactionRecord = await wallet_client.send_transaction_multi(
        str(wallet_id), additions, removals, final_fee
    )
    tx_id = transaction.name.hex()
    print(f"Transaction sent: {tx_id}")
    print(f"To get status, use command: chia wallet get_transaction -f {fingerprint} -tx 0x{tx_id}")


async def async_split(args: Dict[str, Any], wallet_client: WalletRpcClient, fingerprint: int) -> None:
    wallet_id: int = args["id"]
    number_of_coins = args["number_of_coins"]
    fee = Decimal(args["fee"])
    # new args
    amount_per_coin = Decimal(args["amount_per_coin"])
    unique_addresses = bool(args["unique_addresses"])
    target_coin_id: bytes32 = bytes32.from_hexstr(args["target_coin_id"])
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
    final_amount_per_coin = uint64(int(amount_per_coin * mojo_per_unit))
    final_fee = uint64(int(fee * mojo_per_unit))

    total_amount = (final_amount_per_coin * number_of_coins) + final_fee
    # get full coin record from name, and validate information about it.
    removal_coin_record: CoinRecord = (await wallet_client.get_coin_records_by_names([target_coin_id]))[0]
    if removal_coin_record.coin.amount < total_amount:
        print(
            f"Coin amount: {removal_coin_record.coin.amount/ mojo_per_unit} "
            f"is less than the total amount of the split: {total_amount/mojo_per_unit}, exiting."
        )
        print("Try using a smaller fee or amount.")
        return
    additions: List[Dict[str, Union[uint64, bytes32]]] = []
    for i in range(number_of_coins):  # for readability.
        target_ph: bytes32 = decode_puzzle_hash(await wallet_client.get_next_address(str(wallet_id), unique_addresses))
        additions.append({"amount": final_amount_per_coin, "puzzle_hash": target_ph})
    transaction: TransactionRecord = await wallet_client.send_transaction_multi(
        str(wallet_id), additions, [removal_coin_record.coin], final_fee
    )
    tx_id = transaction.name.hex()
    print(f"Transaction sent: {tx_id}")
    print(f"To get status, use command: chia wallet get_transaction -f {fingerprint} -tx 0x{tx_id}")
