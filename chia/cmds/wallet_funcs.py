import asyncio
import pathlib
import sys
import time
from datetime import datetime
from decimal import Decimal
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple, Union

import aiohttp

from chia.cmds.cmds_util import transaction_status_msg, transaction_submitted_msg
from chia.cmds.show import print_connections
from chia.cmds.units import units
from chia.rpc.wallet_rpc_client import WalletRpcClient
from chia.server.start_wallet import SERVICE_NAME
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.bech32m import encode_puzzle_hash
from chia.util.config import load_config
from chia.util.default_root import DEFAULT_ROOT_PATH
from chia.util.ints import uint16, uint32, uint64
from chia.wallet.did_wallet.did_info import DID_HRP
from chia.wallet.nft_wallet.nft_info import NFT_HRP, NFTInfo
from chia.wallet.trade_record import TradeRecord
from chia.wallet.trading.offer import Offer
from chia.wallet.trading.trade_status import TradeStatus
from chia.wallet.transaction_record import TransactionRecord
from chia.wallet.util.transaction_type import TransactionType
from chia.wallet.util.wallet_types import WalletType

CATNameResolver = Callable[[bytes32], Awaitable[Optional[Tuple[Optional[uint32], str]]]]


transaction_type_descriptions = {
    TransactionType.INCOMING_TX: "received",
    TransactionType.OUTGOING_TX: "sent",
    TransactionType.COINBASE_REWARD: "rewarded",
    TransactionType.FEE_REWARD: "rewarded",
    TransactionType.INCOMING_TRADE: "received in trade",
    TransactionType.OUTGOING_TRADE: "sent in trade",
}


def transaction_description_from_type(tx: TransactionRecord) -> str:
    return transaction_type_descriptions.get(TransactionType(tx.type), "(unknown reason)")


def print_transaction(tx: TransactionRecord, verbose: bool, name, address_prefix: str, mojo_per_unit: int) -> None:
    if verbose:
        print(tx)
    else:
        chia_amount = Decimal(int(tx.amount)) / mojo_per_unit
        to_address = encode_puzzle_hash(tx.to_puzzle_hash, address_prefix)
        print(f"Transaction {tx.name}")
        print(f"Status: {'Confirmed' if tx.confirmed else ('In mempool' if tx.is_in_mempool() else 'Pending')}")
        description = transaction_description_from_type(tx)
        print(f"Amount {description}: {chia_amount} {name}")
        print(f"To address: {to_address}")
        print("Created at:", datetime.fromtimestamp(tx.created_at_time).strftime("%Y-%m-%d %H:%M:%S"))
        print("")


def get_mojo_per_unit(wallet_type: WalletType) -> int:
    mojo_per_unit: int
    if wallet_type == WalletType.STANDARD_WALLET or wallet_type == WalletType.POOLING_WALLET:
        mojo_per_unit = units["chia"]
    elif wallet_type == WalletType.CAT:
        mojo_per_unit = units["cat"]
    else:
        raise LookupError("Only standard wallet, CAT wallets, and Plot NFTs are supported")

    return mojo_per_unit


async def get_wallet_type(wallet_id: int, wallet_client: WalletRpcClient) -> WalletType:
    summaries_response = await wallet_client.get_wallets()
    for summary in summaries_response:
        summary_id: int = summary["id"]
        summary_type: int = summary["type"]
        if wallet_id == summary_id:
            return WalletType(summary_type)

    raise LookupError(f"Wallet ID not found: {wallet_id}")


async def get_name_for_wallet_id(
    config: Dict[str, Any],
    wallet_type: WalletType,
    wallet_id: int,
    wallet_client: WalletRpcClient,
):
    if wallet_type == WalletType.STANDARD_WALLET or wallet_type == WalletType.POOLING_WALLET:
        name = config["network_overrides"]["config"][config["selected_network"]]["address_prefix"].upper()
    elif wallet_type == WalletType.CAT:
        name = await wallet_client.get_cat_name(wallet_id=str(wallet_id))
    else:
        raise LookupError("Only standard wallet, CAT wallets, and Plot NFTs are supported")

    return name


async def get_transaction(args: dict, wallet_client: WalletRpcClient, fingerprint: int) -> None:
    transaction_id = bytes32.from_hexstr(args["tx_id"])
    config = load_config(DEFAULT_ROOT_PATH, "config.yaml", SERVICE_NAME)
    address_prefix = config["network_overrides"]["config"][config["selected_network"]]["address_prefix"]
    tx: TransactionRecord = await wallet_client.get_transaction("this is unused", transaction_id=transaction_id)

    try:
        wallet_type = await get_wallet_type(wallet_id=tx.wallet_id, wallet_client=wallet_client)
        mojo_per_unit = get_mojo_per_unit(wallet_type=wallet_type)
        name = await get_name_for_wallet_id(
            config=config,
            wallet_type=wallet_type,
            wallet_id=tx.wallet_id,
            wallet_client=wallet_client,
        )
    except LookupError as e:
        print(e.args[0])
        return

    print_transaction(
        tx,
        verbose=(args["verbose"] > 0),
        name=name,
        address_prefix=address_prefix,
        mojo_per_unit=mojo_per_unit,
    )


async def get_transactions(args: dict, wallet_client: WalletRpcClient, fingerprint: int) -> None:
    wallet_id = args["id"]
    paginate = args["paginate"]
    if paginate is None:
        paginate = sys.stdout.isatty()
    offset = args["offset"]
    limit = args["limit"]
    sort_key = args["sort_key"]
    reverse = args["reverse"]

    txs: List[TransactionRecord] = await wallet_client.get_transactions(
        wallet_id, start=offset, end=(offset + limit), sort_key=sort_key, reverse=reverse
    )

    config = load_config(DEFAULT_ROOT_PATH, "config.yaml", SERVICE_NAME)
    address_prefix = config["network_overrides"]["config"][config["selected_network"]]["address_prefix"]
    if len(txs) == 0:
        print("There are no transactions to this address")

    try:
        wallet_type = await get_wallet_type(wallet_id=wallet_id, wallet_client=wallet_client)
        mojo_per_unit = get_mojo_per_unit(wallet_type=wallet_type)
        name = await get_name_for_wallet_id(
            config=config,
            wallet_type=wallet_type,
            wallet_id=wallet_id,
            wallet_client=wallet_client,
        )
    except LookupError as e:
        print(e.args[0])
        return

    num_per_screen = 5 if paginate else len(txs)
    for i in range(0, len(txs), num_per_screen):
        for j in range(0, num_per_screen):
            if i + j >= len(txs):
                break
            print_transaction(
                txs[i + j],
                verbose=(args["verbose"] > 0),
                name=name,
                address_prefix=address_prefix,
                mojo_per_unit=mojo_per_unit,
            )
        if i + num_per_screen >= len(txs):
            return None
        print("Press q to quit, or c to continue")
        while True:
            entered_key = sys.stdin.read(1)
            if entered_key == "q":
                return None
            elif entered_key == "c":
                break


def check_unusual_transaction(amount: Decimal, fee: Decimal):
    return fee >= amount


async def send(args: dict, wallet_client: WalletRpcClient, fingerprint: int) -> None:
    wallet_id: int = args["id"]
    amount = Decimal(args["amount"])
    fee = Decimal(args["fee"])
    address = args["address"]
    override = args["override"]
    memo = args["memo"]
    if memo is None:
        memos = None
    else:
        memos = [memo]

    if not override and check_unusual_transaction(amount, fee):
        print(
            f"A transaction of amount {amount} and fee {fee} is unusual.\n"
            f"Pass in --override if you are sure you mean to do this."
        )
        return

    try:
        typ = await get_wallet_type(wallet_id=wallet_id, wallet_client=wallet_client)
    except LookupError:
        print(f"Wallet id: {wallet_id} not found.")
        return

    final_fee = uint64(int(fee * units["chia"]))
    final_amount: uint64
    if typ == WalletType.STANDARD_WALLET:
        final_amount = uint64(int(amount * units["chia"]))
        print("Submitting transaction...")
        res = await wallet_client.send_transaction(str(wallet_id), final_amount, address, final_fee, memos)
    elif typ == WalletType.CAT:
        final_amount = uint64(int(amount * units["cat"]))
        print("Submitting transaction...")
        res = await wallet_client.cat_spend(str(wallet_id), final_amount, address, final_fee, memos)
    else:
        print("Only standard wallet and CAT wallets are supported")
        return

    tx_id = res.name
    start = time.time()
    while time.time() - start < 10:
        await asyncio.sleep(0.1)
        tx = await wallet_client.get_transaction(str(wallet_id), tx_id)
        if len(tx.sent_to) > 0:
            print(transaction_submitted_msg(tx))
            print(transaction_status_msg(fingerprint, tx_id))
            return None

    print("Transaction not yet submitted to nodes")
    print(f"To get status, use command: chia wallet get_transaction -f {fingerprint} -tx 0x{tx_id}")


async def get_address(args: dict, wallet_client: WalletRpcClient, fingerprint: int) -> None:
    wallet_id = args["id"]
    new_address: bool = args.get("new_address", False)
    res = await wallet_client.get_next_address(wallet_id, new_address)
    print(res)


async def delete_unconfirmed_transactions(args: dict, wallet_client: WalletRpcClient, fingerprint: int) -> None:
    wallet_id = args["id"]
    await wallet_client.delete_unconfirmed_transactions(wallet_id)
    print(f"Successfully deleted all unconfirmed transactions for wallet id {wallet_id} on key {fingerprint}")


async def add_token(args: dict, wallet_client: WalletRpcClient, fingerprint: int) -> None:
    asset_id = args["asset_id"]
    token_name = args["token_name"]
    try:
        asset_id_bytes: bytes32 = bytes32.from_hexstr(asset_id)
        existing_info: Optional[Tuple[Optional[uint32], str]] = await wallet_client.cat_asset_id_to_name(asset_id_bytes)
        if existing_info is None or existing_info[0] is None:
            response = await wallet_client.create_wallet_for_existing_cat(asset_id_bytes)
            wallet_id = response["wallet_id"]
            await wallet_client.set_cat_name(wallet_id, token_name)
            print(f"Successfully added {token_name} with wallet id {wallet_id} on key {fingerprint}")
        else:
            wallet_id, old_name = existing_info
            await wallet_client.set_cat_name(wallet_id, token_name)
            print(f"Successfully renamed {old_name} with wallet_id {wallet_id} on key {fingerprint} to {token_name}")
    except ValueError as e:
        if "fromhex()" in str(e):
            print(f"{asset_id} is not a valid Asset ID")
        else:
            raise e


async def make_offer(args: dict, wallet_client: WalletRpcClient, fingerprint: int) -> None:
    offers: List[str] = args["offers"]
    requests: List[str] = args["requests"]
    filepath: str = args["filepath"]
    fee: int = int(Decimal(args["fee"]) * units["chia"])

    if [] in [offers, requests]:
        print("Not creating offer: Must be offering and requesting at least one asset")
    else:
        offer_dict: Dict[Union[uint32, str], int] = {}
        printable_dict: Dict[str, Tuple[str, int, int]] = {}  # Dict[asset_name, Tuple[amount, unit, multiplier]]
        for item in [*offers, *requests]:
            wallet_id, amount = tuple(item.split(":")[0:2])
            if int(wallet_id) == 1:
                name: str = "XCH"
                unit: int = units["chia"]
            else:
                name = await wallet_client.get_cat_name(wallet_id)
                unit = units["cat"]
            multiplier: int = -1 if item in offers else 1
            printable_dict[name] = (amount, unit, multiplier)
            if uint32(int(wallet_id)) in offer_dict:
                print("Not creating offer: Cannot offer and request the same asset in a trade")
                break
            else:
                offer_dict[uint32(int(wallet_id))] = int(Decimal(amount) * unit) * multiplier
        else:
            print("Creating Offer")
            print("--------------")
            print()
            print("OFFERING:")
            for name, info in printable_dict.items():
                amount, unit, multiplier = info
                if multiplier < 0:
                    print(f"  - {amount} {name} ({int(Decimal(amount) * unit)} mojos)")
            print("REQUESTING:")
            for name, info in printable_dict.items():
                amount, unit, multiplier = info
                if multiplier > 0:
                    print(f"  - {amount} {name} ({int(Decimal(amount) * unit)} mojos)")

            confirmation = input("Confirm (y/n): ")
            if confirmation not in ["y", "yes"]:
                print("Not creating offer...")
            else:
                offer, trade_record = await wallet_client.create_offer_for_ids(offer_dict, fee=fee)
                if offer is not None:
                    with open(pathlib.Path(filepath), "w") as file:
                        file.write(offer.to_bech32())
                    print(f"Created offer with ID {trade_record.trade_id}")
                    print(f"Use chia wallet get_offers --id {trade_record.trade_id} -f {fingerprint} to view status")
                else:
                    print("Error creating offer")


def timestamp_to_time(timestamp):
    return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S")


async def print_offer_summary(cat_name_resolver: CATNameResolver, sum_dict: Dict[str, int], has_fee: bool = False):
    for asset_id, amount in sum_dict.items():
        description: str = ""
        unit: int = units["chia"]
        wid: str = "1" if asset_id == "xch" else ""
        mojo_amount: int = int(Decimal(amount))
        name: str = "XCH"
        if asset_id != "xch":
            name = asset_id
            if asset_id == "unknown":
                name = "Unknown"
                unit = units["mojo"]
                if has_fee:
                    description = " [Typically represents change returned from the included fee]"
            else:
                unit = units["cat"]
                result = await cat_name_resolver(bytes32.from_hexstr(asset_id))
                if result is not None:
                    wid = str(result[0])
                    name = result[1]
        output: str = f"    - {name}"
        mojo_str: str = f"{mojo_amount} {'mojo' if mojo_amount == 1 else 'mojos'}"
        if len(wid) > 0:
            output += f" (Wallet ID: {wid})"
        if unit == units["mojo"]:
            output += f": {mojo_str}"
        else:
            output += f": {mojo_amount / unit} ({mojo_str})"
        if len(description) > 0:
            output += f" {description}"
        print(output)


async def print_trade_record(record, wallet_client: WalletRpcClient, summaries: bool = False) -> None:
    print()
    print(f"Record with id: {record.trade_id}")
    print("---------------")
    print(f"Created at: {timestamp_to_time(record.created_at_time)}")
    print(f"Confirmed at: {record.confirmed_at_index}")
    print(f"Accepted at: {timestamp_to_time(record.accepted_at_time) if record.accepted_at_time else 'N/A'}")
    print(f"Status: {TradeStatus(record.status).name}")
    if summaries:
        print("Summary:")
        offer = Offer.from_bytes(record.offer)
        offered, requested, _ = offer.summary()
        outbound_balances: Dict[str, int] = offer.get_pending_amounts()
        fees: Decimal = Decimal(offer.bundle.fees())
        cat_name_resolver = wallet_client.cat_asset_id_to_name
        print("  OFFERED:")
        await print_offer_summary(cat_name_resolver, offered)
        print("  REQUESTED:")
        await print_offer_summary(cat_name_resolver, requested)
        print("Pending Outbound Balances:")
        await print_offer_summary(cat_name_resolver, outbound_balances, has_fee=(fees > 0))
        print(f"Included Fees: {fees / units['chia']}")
    print("---------------")


async def get_offers(args: dict, wallet_client: WalletRpcClient, fingerprint: int) -> None:
    id: Optional[str] = args.get("id", None)
    filepath: Optional[str] = args.get("filepath", None)
    exclude_my_offers: bool = args.get("exclude_my_offers", False)
    exclude_taken_offers: bool = args.get("exclude_taken_offers", False)
    include_completed: bool = args.get("include_completed", False)
    summaries: bool = args.get("summaries", False)
    reverse: bool = args.get("reverse", False)
    file_contents: bool = (filepath is not None) or summaries
    records: List[TradeRecord] = []
    if id is None:
        batch_size: int = 10
        start: int = 0
        end: int = start + batch_size

        # Traverse offers page by page
        while True:
            new_records: List[TradeRecord] = await wallet_client.get_all_offers(
                start,
                end,
                reverse=reverse,
                file_contents=file_contents,
                exclude_my_offers=exclude_my_offers,
                exclude_taken_offers=exclude_taken_offers,
                include_completed=include_completed,
            )
            records.extend(new_records)

            # If fewer records were returned than requested, we're done
            if len(new_records) < batch_size:
                break

            start = end
            end += batch_size
    else:
        records = [await wallet_client.get_offer(bytes32.from_hexstr(id), file_contents)]
        if filepath is not None:
            with open(pathlib.Path(filepath), "w") as file:
                file.write(Offer.from_bytes(records[0].offer).to_bech32())
                file.close()

    for record in records:
        await print_trade_record(record, wallet_client, summaries=summaries)


async def take_offer(args: dict, wallet_client: WalletRpcClient, fingerprint: int) -> None:
    if "." in args["file"]:
        filepath = pathlib.Path(args["file"])
        with open(filepath, "r") as file:
            offer_hex: str = file.read()
            file.close()
    else:
        offer_hex = args["file"]

    examine_only: bool = args["examine_only"]
    fee: int = int(Decimal(args["fee"]) * units["chia"])

    try:
        offer = Offer.from_bech32(offer_hex)
    except ValueError:
        print("Please enter a valid offer file or hex blob")
        return

    offered, requested, _ = offer.summary()
    cat_name_resolver = wallet_client.cat_asset_id_to_name
    print("Summary:")
    print("  OFFERED:")
    await print_offer_summary(cat_name_resolver, offered)
    print("  REQUESTED:")
    await print_offer_summary(cat_name_resolver, requested)
    print(f"Included Fees: {Decimal(offer.bundle.fees()) / units['chia']}")

    if not examine_only:
        confirmation = input("Would you like to take this offer? (y/n): ")
        if confirmation in ["y", "yes"]:
            trade_record = await wallet_client.take_offer(offer, fee=fee)
            print(f"Accepted offer with ID {trade_record.trade_id}")
            print(f"Use chia wallet get_offers --id {trade_record.trade_id} -f {fingerprint} to view its status")


async def cancel_offer(args: dict, wallet_client: WalletRpcClient, fingerprint: int) -> None:
    id = bytes32.from_hexstr(args["id"])
    secure: bool = not args["insecure"]
    fee: int = int(Decimal(args["fee"]) * units["chia"])

    trade_record = await wallet_client.get_offer(id, file_contents=True)
    await print_trade_record(trade_record, wallet_client, summaries=True)

    confirmation = input(f"Are you sure you wish to cancel offer with ID: {trade_record.trade_id}? (y/n): ")
    if confirmation in ["y", "yes"]:
        await wallet_client.cancel_offer(id, secure=secure, fee=fee)
        print(f"Cancelled offer with ID {trade_record.trade_id}")
        if secure:
            print(f"Use chia wallet get_offers --id {trade_record.trade_id} -f {fingerprint} to view cancel status")


def wallet_coin_unit(typ: WalletType, address_prefix: str) -> Tuple[str, int]:
    if typ == WalletType.CAT:
        return "", units["cat"]
    if typ in [WalletType.STANDARD_WALLET, WalletType.POOLING_WALLET, WalletType.MULTI_SIG, WalletType.RATE_LIMITED]:
        return address_prefix, units["chia"]
    return "", units["mojo"]


def print_balance(amount: int, scale: int, address_prefix: str) -> str:
    ret = f"{amount/scale} {address_prefix} "
    if scale > 1:
        ret += f"({amount} mojo)"
    return ret


async def print_balances(args: dict, wallet_client: WalletRpcClient, fingerprint: int) -> None:
    wallet_type: Optional[WalletType] = None
    if "type" in args:
        wallet_type = WalletType(args["type"])
    summaries_response = await wallet_client.get_wallets(wallet_type)
    config = load_config(DEFAULT_ROOT_PATH, "config.yaml")
    address_prefix = config["network_overrides"]["config"][config["selected_network"]]["address_prefix"]

    is_synced: bool = await wallet_client.get_synced()
    is_syncing: bool = await wallet_client.get_sync_status()

    print(f"Wallet height: {await wallet_client.get_height_info()}")
    if is_syncing:
        print("Sync status: Syncing...")
    elif is_synced:
        print("Sync status: Synced")
    else:
        print("Sync status: Not synced")

    if not is_syncing and is_synced:
        if len(summaries_response) == 0:
            type_hint = " " if wallet_type is None else f" from type {wallet_type.name} "
            print(f"\nNo wallets{type_hint}available for fingerprint: {fingerprint}")
        else:
            print(f"Balances, fingerprint: {fingerprint}")
        for summary in summaries_response:
            indent: str = "   "
            # asset_id currently contains both the asset ID and TAIL program bytes concatenated together.
            # A future RPC update may split them apart, but for now we'll show the first 32 bytes (64 chars)
            asset_id = summary["data"][:64]
            wallet_id = summary["id"]
            balances = await wallet_client.get_wallet_balance(wallet_id)
            typ = WalletType(int(summary["type"]))
            address_prefix, scale = wallet_coin_unit(typ, address_prefix)
            total_balance: str = print_balance(balances["confirmed_wallet_balance"], scale, address_prefix)
            unconfirmed_wallet_balance: str = print_balance(
                balances["unconfirmed_wallet_balance"], scale, address_prefix
            )
            spendable_balance: str = print_balance(balances["spendable_balance"], scale, address_prefix)
            my_did: Optional[str] = None
            print()
            print(f"{summary['name']}:")
            print(f"{indent}{'-Total Balance:'.ljust(23)} {total_balance}")
            print(f"{indent}{'-Pending Total Balance:'.ljust(23)} " f"{unconfirmed_wallet_balance}")
            print(f"{indent}{'-Spendable:'.ljust(23)} {spendable_balance}")
            print(f"{indent}{'-Type:'.ljust(23)} {typ.name}")
            if typ == WalletType.DISTRIBUTED_ID:
                get_did_response = await wallet_client.get_did_id(wallet_id)
                my_did = get_did_response["my_did"]
                print(f"{indent}{'-DID ID:'.ljust(23)} {my_did}")
            elif typ == WalletType.NFT:
                get_did_response = await wallet_client.get_nft_wallet_did(wallet_id)
                my_did = get_did_response["did_id"]
                if my_did is not None and len(my_did) > 0:
                    print(f"{indent}{'-DID ID:'.ljust(23)} {my_did}")
            elif len(asset_id) > 0:
                print(f"{indent}{'-Asset ID:'.ljust(23)} {asset_id}")
            print(f"{indent}{'-Wallet ID:'.ljust(23)} {wallet_id}")

    print(" ")
    trusted_peers: Dict = config["wallet"].get("trusted_peers", {})
    await print_connections(wallet_client, trusted_peers)


async def get_wallet(wallet_client: WalletRpcClient, fingerprint: int = None) -> Optional[Tuple[WalletRpcClient, int]]:
    if fingerprint is not None:
        fingerprints = [fingerprint]
    else:
        fingerprints = await wallet_client.get_public_keys()
    if len(fingerprints) == 0:
        print("No keys loaded. Run 'chia keys generate' or import a key")
        return None
    if len(fingerprints) == 1:
        fingerprint = fingerprints[0]
    if fingerprint is not None:
        log_in_response = await wallet_client.log_in(fingerprint)
    else:
        logged_in_fingerprint: Optional[int] = await wallet_client.get_logged_in_fingerprint()
        spacing: str = "  " if logged_in_fingerprint is not None else ""
        current_sync_status: str = ""
        if logged_in_fingerprint is not None:
            if await wallet_client.get_synced():
                current_sync_status = "Synced"
            elif await wallet_client.get_sync_status():
                current_sync_status = "Syncing"
            else:
                current_sync_status = "Not Synced"
        print("Wallet keys:")
        for i, fp in enumerate(fingerprints):
            row: str = f"{i+1}) "
            row += "* " if fp == logged_in_fingerprint else spacing
            row += f"{fp}"
            if fp == logged_in_fingerprint and len(current_sync_status) > 0:
                row += f" ({current_sync_status})"
            print(row)
        val = None
        prompt: str = (
            f"Choose a wallet key [1-{len(fingerprints)}] ('q' to quit, or Enter to use {logged_in_fingerprint}): "
        )
        while val is None:
            val = input(prompt)
            if val == "q":
                return None
            elif val == "" and logged_in_fingerprint is not None:
                fingerprint = logged_in_fingerprint
                break
            elif not val.isdigit():
                val = None
            else:
                index = int(val) - 1
                if index < 0 or index >= len(fingerprints):
                    print("Invalid value")
                    val = None
                    continue
                else:
                    fingerprint = fingerprints[index]
        assert fingerprint is not None
        log_in_response = await wallet_client.log_in(fingerprint)

    if log_in_response["success"] is False:
        print(f"Login failed: {log_in_response}")
        return None
    return wallet_client, fingerprint


async def execute_with_wallet(
    wallet_rpc_port: Optional[int], fingerprint: int, extra_params: Dict, function: Callable
) -> None:
    try:
        config = load_config(DEFAULT_ROOT_PATH, "config.yaml")
        self_hostname = config["self_hostname"]
        if wallet_rpc_port is None:
            wallet_rpc_port = config["wallet"]["rpc_port"]
        wallet_client = await WalletRpcClient.create(self_hostname, uint16(wallet_rpc_port), DEFAULT_ROOT_PATH, config)
        wallet_client_f = await get_wallet(wallet_client, fingerprint=fingerprint)
        if wallet_client_f is None:
            wallet_client.close()
            await wallet_client.await_closed()
            return None
        wallet_client, fingerprint = wallet_client_f
        await function(extra_params, wallet_client, fingerprint)
    except KeyboardInterrupt:
        pass
    except Exception as e:
        if isinstance(e, aiohttp.ClientConnectorError):
            print(
                f"Connection error. Check if the wallet is running at {wallet_rpc_port}. "
                "You can run the wallet via:\n\tchia start wallet"
            )
        else:
            print(f"Exception from 'wallet' {e}")
    wallet_client.close()
    await wallet_client.await_closed()


async def create_did_wallet(args: Dict, wallet_client: WalletRpcClient, fingerprint: int) -> None:
    amount = args["amount"]
    fee: int = int(Decimal(args["fee"]) * units["chia"])
    name = args["name"]
    try:
        response = await wallet_client.create_new_did_wallet(amount, fee, name)
        wallet_id = response["wallet_id"]
        my_did = response["my_did"]
        print(f"Successfully created a DID wallet with name {name} and id {wallet_id} on key {fingerprint}")
        print(f"Successfully created a DID {my_did} in the newly created DID wallet")
    except Exception as e:
        print(f"Failed to create DID wallet: {e}")


async def did_set_wallet_name(args: Dict, wallet_client: WalletRpcClient, fingerprint: int) -> None:
    wallet_id = args["wallet_id"]
    name = args["name"]
    try:
        await wallet_client.did_set_wallet_name(wallet_id, name)
        print(f"Successfully set a new name for DID wallet with id {wallet_id}: {name}")
    except Exception as e:
        print(f"Failed to set DID wallet name: {e}")


async def get_did(args: Dict, wallet_client: WalletRpcClient, fingerprint: int) -> None:
    did_wallet_id: int = args["did_wallet_id"]
    try:
        response = await wallet_client.get_did_id(did_wallet_id)
        my_did = response["my_did"]
        coin_id = response["coin_id"]
        print(f"{'DID:'.ljust(23)} {my_did}")
        print(f"{'Coin ID:'.ljust(23)} {coin_id}")
    except Exception as e:
        print(f"Failed to get DID: {e}")


async def create_nft_wallet(args: Dict, wallet_client: WalletRpcClient, fingerprint: int) -> None:
    did_id = args["did_id"]
    name = args["name"]
    try:
        response = await wallet_client.create_new_nft_wallet(did_id, name)
        wallet_id = response["wallet_id"]
        print(f"Successfully created an NFT wallet with id {wallet_id} on key {fingerprint}")
    except Exception as e:
        print(f"Failed to create NFT wallet: {e}")


async def mint_nft(args: Dict, wallet_client: WalletRpcClient, fingerprint: int) -> None:
    wallet_id = args["wallet_id"]
    royalty_address = args["royalty_address"]
    target_address = args["target_address"]
    hash = args["hash"]
    uris = args["uris"]
    metadata_hash = args["metadata_hash"]
    metadata_uris = args["metadata_uris"]
    license_hash = args["license_hash"]
    license_uris = args["license_uris"]
    series_total = args["series_total"]
    series_number = args["series_number"]
    fee: int = int(Decimal(args["fee"]) * units["chia"])
    royalty_percentage = args["royalty_percentage"]
    try:
        response = await wallet_client.mint_nft(
            wallet_id,
            royalty_address,
            target_address,
            hash,
            uris,
            metadata_hash,
            metadata_uris,
            license_hash,
            license_uris,
            series_total,
            series_number,
            fee,
            royalty_percentage,
        )
        spend_bundle = response["spend_bundle"]
        print(f"NFT minted Successfully with spend bundle: {spend_bundle}")
    except Exception as e:
        print(f"Failed to mint NFT: {e}")


async def add_uri_to_nft(args: Dict, wallet_client: WalletRpcClient, fingerprint: int) -> None:
    try:
        wallet_id = args["wallet_id"]
        nft_coin_id = args["nft_coin_id"]
        uri = args["uri"]
        metadata_uri = args["metadata_uri"]
        license_uri = args["license_uri"]
        if len([x for x in (uri, metadata_uri, license_uri) if x is not None]) > 1:
            raise ValueError("You must provide only one of the URI flags")
        if uri is not None and len(uri) > 0:
            key = "u"
            uri_value = uri
        elif metadata_uri is not None and len(metadata_uri) > 0:
            key = "mu"
            uri_value = metadata_uri
        elif license_uri is not None and len(license_uri) > 0:
            key = "lu"
            uri_value = license_uri
        else:
            raise ValueError("You must provide at least one of the URI flags")
        fee: int = int(Decimal(args["fee"]) * units["chia"])
        response = await wallet_client.add_uri_to_nft(wallet_id, nft_coin_id, key, uri_value, fee)
        spend_bundle = response["spend_bundle"]
        print(f"URI added successfully with spend bundle: {spend_bundle}")
    except Exception as e:
        print(f"Failed to add URI to NFT: {e}")


async def transfer_nft(args: Dict, wallet_client: WalletRpcClient, fingerprint: int) -> None:
    try:
        wallet_id = args["wallet_id"]
        nft_coin_id = args["nft_coin_id"]
        target_address = args["target_address"]
        fee: int = int(Decimal(args["fee"]) * units["chia"])
        response = await wallet_client.transfer_nft(wallet_id, nft_coin_id, target_address, fee)
        spend_bundle = response["spend_bundle"]
        print(f"NFT transferred successfully with spend bundle: {spend_bundle}")
    except Exception as e:
        print(f"Failed to transfer NFT: {e}")


def print_nft_info(nft: NFTInfo) -> None:
    indent: str = "   "
    owner_did = None if nft.owner_did is None else encode_puzzle_hash(nft.owner_did, DID_HRP)
    print()
    print(f"{'NFT identifier:'.ljust(26)} {encode_puzzle_hash(nft.launcher_id, NFT_HRP)}")
    print(f"{'Launcher coin ID:'.ljust(26)} {nft.launcher_id}")
    print(f"{'Launcher puzhash:'.ljust(26)} {nft.launcher_puzhash}")
    print(f"{'Current NFT coin ID:'.ljust(26)} {nft.nft_coin_id}")
    print(f"{'On-chain data/info:'.ljust(26)} {nft.chain_info}")
    print(f"{'Owner DID:'.ljust(26)} {owner_did}")
    print(f"{'Royalty percentage:'.ljust(26)} {nft.royalty_percentage}")
    print(f"{'Royalty puzhash:'.ljust(26)} {nft.royalty_puzzle_hash}")
    print(f"{'NFT content hash:'.ljust(26)} {nft.data_hash.hex()}")
    print(f"{'Metadata hash:'.ljust(26)} {nft.metadata_hash.hex()}")
    print(f"{'License hash:'.ljust(26)} {nft.license_hash.hex()}")
    print(f"{'NFT series total:'.ljust(26)} {nft.series_total}")
    print(f"{'Current NFT number in the series:'.ljust(26)} {nft.series_number}")
    print(f"{'Metadata updater puzhash:'.ljust(26)} {nft.updater_puzhash}")
    print(f"{'NFT minting block height:'.ljust(26)} {nft.mint_height}")
    print(f"{'Inner puzzle supports DID:'.ljust(26)} {nft.supports_did}")
    print(f"{'NFT is pending for a transaction:'.ljust(26)} {nft.pending_transaction}")
    print()
    print("URIs:")
    for uri in nft.data_uris:
        print(f"{indent}{uri}")
    print()
    print("Metadata URIs:")
    for metadata_uri in nft.metadata_uris:
        print(f"{indent}{metadata_uri}")
    print()
    print("License URIs:")
    for license_uri in nft.license_uris:
        print(f"{indent}{license_uri}")


async def list_nfts(args: Dict, wallet_client: WalletRpcClient, fingerprint: int) -> None:
    wallet_id = args["wallet_id"]
    try:
        response = await wallet_client.list_nfts(wallet_id)
        nft_list = response["nft_list"]
        if len(nft_list) > 0:
            for n in nft_list:
                nft = NFTInfo.from_json_dict(n)
                print_nft_info(nft)
        else:
            print(f"No NFTs found for wallet with id {wallet_id} on key {fingerprint}")
    except Exception as e:
        print(f"Failed to list NFTs for wallet with id {wallet_id} on key {fingerprint}: {e}")


async def set_nft_did(args: Dict, wallet_client: WalletRpcClient, fingerprint: int) -> None:
    wallet_id = args["wallet_id"]
    did_id = args["did_id"]
    nft_coin_id = args["nft_coin_id"]
    fee: int = int(Decimal(args["fee"]) * units["chia"])
    try:
        response = await wallet_client.set_nft_did(wallet_id, did_id, nft_coin_id, fee)
        spend_bundle = response["spend_bundle"]
        print(f"Transaction to set DID on NFT has been initiated with: {spend_bundle}")
    except Exception as e:
        print(f"Failed to set DID on NFT: {e}")


async def get_nft_info(args: Dict, wallet_client: WalletRpcClient, fingerprint: int) -> None:
    nft_coin_id = args["nft_coin_id"]
    try:
        response = await wallet_client.get_nft_info(nft_coin_id)
        nft_info = NFTInfo.from_json_dict(response["nft_info"])
        print_nft_info(nft_info)
    except Exception as e:
        print(f"Failed to get NFT info: {e}")
