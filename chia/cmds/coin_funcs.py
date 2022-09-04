from decimal import Decimal
from typing import Any, Dict, List

from chia.cmds.wallet_funcs import get_mojo_per_unit, get_wallet_type, print_balance
from chia.rpc.wallet_rpc_client import WalletRpcClient
from chia.util.bech32m import encode_puzzle_hash
from chia.util.ints import uint64


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
