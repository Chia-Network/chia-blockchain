from decimal import Decimal
from typing import Any, Dict, List, Optional, Union

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
    for cr in conf_coins:
        address = encode_puzzle_hash(cr.coin.puzzle_hash, addr_prefix)
        amount = print_balance(cr.coin.amount, mojo_per_unit, addr_prefix)
        print(f"Coin ID: 0x{cr.name.hex()}")
        print(f"    Current Address: {address} Amount: {amount}, Confirmed in block: {cr.confirmed_block_index}\n")
    if show_unconfirmed:
        print("\nUnconfirmed Removals:")
        for cr in unconfirmed_removals:
            address = encode_puzzle_hash(cr.coin.puzzle_hash, addr_prefix)
            amount = print_balance(cr.coin.amount, mojo_per_unit, addr_prefix)
            print(f"Coin ID: 0x{cr.name.hex()}")
            print(f"    Previous Address: {address} Amount: {amount}, Confirmed in block: {cr.confirmed_block_index}")
        print("\nUnconfirmed Additions:")
        for coin in unconfirmed_additions:
            address = encode_puzzle_hash(coin.puzzle_hash, addr_prefix)
            amount = print_balance(coin.amount, mojo_per_unit, addr_prefix)
            print(f"Coin ID: 0x{coin.name().hex()}")
            print(f"    New Address: {address} Amount: {amount}, Not yet confirmed in a block.\n")


async def async_combine(args: Dict[str, Any], wallet_client: WalletRpcClient, fingerprint: int) -> None:
    wallet_id: int = args["id"]
    min_coin_amount = Decimal(args["min_coin_amount"])
    excluded_amounts = args["excluded_amounts"]
    number_of_coins = args["number_of_coins"]
    max_dust_amount = Decimal(args["max_dust_amount"])
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
    final_max_dust_amount = uint64(int(max_dust_amount * mojo_per_unit))
    final_min_coin_amount: uint64 = uint64(int(min_coin_amount * mojo_per_unit))
    final_excluded_amounts: List[uint64] = [uint64(int(amount * mojo_per_unit)) for amount in excluded_amounts]
    final_fee = uint64(int(fee * mojo_per_unit))
    conf_coins, _, _ = await wallet_client.get_spendable_coins(
        wallet_id=wallet_id,
        max_coin_amount=final_max_dust_amount,
        min_coin_amount=final_min_coin_amount,
        excluded_amounts=final_excluded_amounts,
    )
    if len(conf_coins) <= 1:
        print("No coins to combine.")
        return
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
    removal_coin_record: Optional[CoinRecord] = await wallet_client.get_coin_record_by_name(target_coin_id)
    if removal_coin_record is None:
        print("Coin not found.")
        return
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
