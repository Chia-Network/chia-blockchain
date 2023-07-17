from __future__ import annotations

import asyncio
import json
import os
import pathlib
import sys
import time
from datetime import datetime
from decimal import Decimal
from typing import Any, Awaitable, Callable, Dict, List, Optional, Sequence, Tuple, Union

from chia.cmds.cmds_util import get_wallet_client, transaction_status_msg, transaction_submitted_msg
from chia.cmds.peer_funcs import print_connections
from chia.cmds.units import units
from chia.rpc.wallet_rpc_client import WalletRpcClient
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.bech32m import bech32_decode, decode_puzzle_hash, encode_puzzle_hash
from chia.util.config import selected_network_address_prefix
from chia.util.ints import uint16, uint32, uint64
from chia.wallet.nft_wallet.nft_info import NFTInfo
from chia.wallet.outer_puzzles import AssetType
from chia.wallet.puzzle_drivers import PuzzleInfo
from chia.wallet.trade_record import TradeRecord
from chia.wallet.trading.offer import Offer
from chia.wallet.trading.trade_status import TradeStatus
from chia.wallet.transaction_record import TransactionRecord
from chia.wallet.transaction_sorting import SortKey
from chia.wallet.util.address_type import AddressType, ensure_valid_address
from chia.wallet.util.puzzle_decorator_type import PuzzleDecoratorType
from chia.wallet.util.query_filter import HashFilter, TransactionTypeFilter
from chia.wallet.util.transaction_type import CLAWBACK_INCOMING_TRANSACTION_TYPES, TransactionType
from chia.wallet.util.wallet_types import WalletType
from chia.wallet.vc_wallet.vc_store import VCProofs
from chia.wallet.wallet_coin_store import GetCoinRecords

CATNameResolver = Callable[[bytes32], Awaitable[Optional[Tuple[Optional[uint32], str]]]]

transaction_type_descriptions = {
    TransactionType.INCOMING_TX: "received",
    TransactionType.OUTGOING_TX: "sent",
    TransactionType.COINBASE_REWARD: "rewarded",
    TransactionType.FEE_REWARD: "rewarded",
    TransactionType.INCOMING_TRADE: "received in trade",
    TransactionType.OUTGOING_TRADE: "sent in trade",
    TransactionType.INCOMING_CLAWBACK_RECEIVE: "received in clawback as recipient",
    TransactionType.INCOMING_CLAWBACK_SEND: "received in clawback as sender",
    TransactionType.OUTGOING_CLAWBACK: "claim/clawback",
}


def transaction_description_from_type(tx: TransactionRecord) -> str:
    return transaction_type_descriptions.get(TransactionType(tx.type), "(unknown reason)")


def print_transaction(
    tx: TransactionRecord,
    verbose: bool,
    name: str,
    address_prefix: str,
    mojo_per_unit: int,
    coin_record: Optional[Dict[str, Any]] = None,
) -> None:  # pragma: no cover
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
        if coin_record is not None:
            print(
                "Recipient claimable time:",
                datetime.fromtimestamp(tx.created_at_time + coin_record["metadata"]["time_lock"]).strftime(
                    "%Y-%m-%d %H:%M:%S"
                ),
            )
        print("")


def get_mojo_per_unit(wallet_type: WalletType) -> int:
    mojo_per_unit: int
    if wallet_type in {
        WalletType.STANDARD_WALLET,
        WalletType.POOLING_WALLET,
        WalletType.DATA_LAYER,
        WalletType.VC,
    }:  # pragma: no cover
        mojo_per_unit = units["chia"]
    elif wallet_type == WalletType.CAT:
        mojo_per_unit = units["cat"]
    else:
        raise LookupError(f"Operation is not supported for Wallet type {wallet_type.name}")

    return mojo_per_unit


async def get_wallet_type(wallet_id: int, wallet_client: WalletRpcClient) -> WalletType:
    summaries_response = await wallet_client.get_wallets()
    for summary in summaries_response:
        summary_id: int = summary["id"]
        summary_type: int = summary["type"]
        if wallet_id == summary_id:
            return WalletType(summary_type)

    raise LookupError(f"Wallet ID not found: {wallet_id}")


async def get_unit_name_for_wallet_id(
    config: Dict[str, Any],
    wallet_type: WalletType,
    wallet_id: int,
    wallet_client: WalletRpcClient,
) -> str:
    if wallet_type in {
        WalletType.STANDARD_WALLET,
        WalletType.POOLING_WALLET,
        WalletType.DATA_LAYER,
        WalletType.VC,
    }:  # pragma: no cover
        name: str = config["network_overrides"]["config"][config["selected_network"]]["address_prefix"].upper()
    elif wallet_type == WalletType.CAT:
        name = await wallet_client.get_cat_name(wallet_id=wallet_id)
    else:
        raise LookupError(f"Operation is not supported for Wallet type {wallet_type.name}")

    return name


async def get_transaction(
    *, wallet_rpc_port: Optional[int], fingerprint: Optional[int], tx_id: str, verbose: int
) -> None:
    async with get_wallet_client(wallet_rpc_port, fingerprint) as (wallet_client, fingerprint, config):
        transaction_id = bytes32.from_hexstr(tx_id)
        address_prefix = selected_network_address_prefix(config)
        # The wallet id parameter is required by the client but unused by the RPC.
        this_is_unused = 37
        tx: TransactionRecord = await wallet_client.get_transaction(this_is_unused, transaction_id=transaction_id)

        try:
            wallet_type = await get_wallet_type(wallet_id=tx.wallet_id, wallet_client=wallet_client)
            mojo_per_unit = get_mojo_per_unit(wallet_type=wallet_type)
            name = await get_unit_name_for_wallet_id(
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
            verbose=(verbose > 0),
            name=name,
            address_prefix=address_prefix,
            mojo_per_unit=mojo_per_unit,
        )


async def get_transactions(
    *,
    wallet_rpc_port: Optional[int],
    fp: Optional[int],
    wallet_id: int,
    verbose: int,
    paginate: Optional[bool],
    offset: int,
    limit: int,
    sort_key: SortKey,
    reverse: bool,
    clawback: bool,
) -> None:  # pragma: no cover
    async with get_wallet_client(wallet_rpc_port, fp) as (wallet_client, fingerprint, config):
        if paginate is None:
            paginate = sys.stdout.isatty()
        type_filter = (
            None
            if not clawback
            else TransactionTypeFilter.include(
                [TransactionType.INCOMING_CLAWBACK_RECEIVE, TransactionType.INCOMING_CLAWBACK_SEND]
            )
        )
        txs: List[TransactionRecord] = await wallet_client.get_transactions(
            wallet_id, start=offset, end=(offset + limit), sort_key=sort_key, reverse=reverse, type_filter=type_filter
        )

        address_prefix = selected_network_address_prefix(config)
        if len(txs) == 0:
            print("There are no transactions to this address")

        try:
            wallet_type = await get_wallet_type(wallet_id=wallet_id, wallet_client=wallet_client)
            mojo_per_unit = get_mojo_per_unit(wallet_type=wallet_type)
            name = await get_unit_name_for_wallet_id(
                config=config,
                wallet_type=wallet_type,
                wallet_id=wallet_id,
                wallet_client=wallet_client,
            )
        except LookupError as e:
            print(e.args[0])
            return

        skipped = 0
        num_per_screen = 5 if paginate else len(txs)
        for i in range(0, len(txs), num_per_screen):
            for j in range(0, num_per_screen):
                if i + j + skipped >= len(txs):
                    break
                coin_record: Optional[Dict[str, Any]] = None
                if txs[i + j + skipped].type in CLAWBACK_INCOMING_TRANSACTION_TYPES:
                    coin_records = await wallet_client.get_coin_records(
                        GetCoinRecords(coin_id_filter=HashFilter.include([txs[i + j + skipped].additions[0].name()]))
                    )
                    if len(coin_records["coin_records"]) > 0:
                        coin_record = coin_records["coin_records"][0]
                    else:
                        j -= 1
                        skipped += 1
                        continue
                print_transaction(
                    txs[i + j + skipped],
                    verbose=(verbose > 0),
                    name=name,
                    address_prefix=address_prefix,
                    mojo_per_unit=mojo_per_unit,
                    coin_record=coin_record,
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


def check_unusual_transaction(amount: Decimal, fee: Decimal) -> bool:
    return fee >= amount


async def send(
    *,
    wallet_rpc_port: Optional[int],
    fp: Optional[int],
    wallet_id: int,
    amount: Decimal,
    memo: Optional[str],
    fee: Decimal,
    address: str,
    override: bool,
    min_coin_amount: Decimal,
    max_coin_amount: Decimal,
    excluded_coin_ids: Sequence[str],
    reuse_puzhash: Optional[bool],
    clawback_time_lock: int,
) -> None:  # pragma: no cover
    async with get_wallet_client(wallet_rpc_port, fp) as (wallet_client, fingerprint, _):
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
        if amount == 0:
            print("You can not send an empty transaction")
            return
        if clawback_time_lock < 0:
            print("Clawback time lock seconds cannot be negative.")
            return
        try:
            typ = await get_wallet_type(wallet_id=wallet_id, wallet_client=wallet_client)
            mojo_per_unit = get_mojo_per_unit(typ)
        except LookupError:
            print(f"Wallet id: {wallet_id} not found.")
            return

        final_fee: uint64 = uint64(int(fee * units["chia"]))  # fees are always in XCH mojos
        final_amount: uint64 = uint64(int(amount * mojo_per_unit))
        final_min_coin_amount: uint64 = uint64(int(min_coin_amount * mojo_per_unit))
        final_max_coin_amount: uint64 = uint64(int(max_coin_amount * mojo_per_unit))
        if typ == WalletType.STANDARD_WALLET:
            print("Submitting transaction...")
            res = await wallet_client.send_transaction(
                wallet_id,
                final_amount,
                address,
                final_fee,
                memos,
                final_min_coin_amount,
                final_max_coin_amount,
                excluded_coin_ids=excluded_coin_ids,
                reuse_puzhash=reuse_puzhash,
                puzzle_decorator_override=[
                    {"decorator": PuzzleDecoratorType.CLAWBACK.name, "clawback_timelock": clawback_time_lock}
                ]
                if clawback_time_lock > 0
                else None,
            )
        elif typ == WalletType.CAT:
            print("Submitting transaction...")
            res = await wallet_client.cat_spend(
                wallet_id,
                final_amount,
                address,
                final_fee,
                memos,
                final_min_coin_amount,
                final_max_coin_amount,
                excluded_coin_ids=excluded_coin_ids,
                reuse_puzhash=reuse_puzhash,
            )
        else:
            print("Only standard wallet and CAT wallets are supported")
            return

        tx_id = res.name
        start = time.time()
        while time.time() - start < 10:
            await asyncio.sleep(0.1)
            tx = await wallet_client.get_transaction(wallet_id, tx_id)
            if len(tx.sent_to) > 0:
                print(transaction_submitted_msg(tx))
                print(transaction_status_msg(fingerprint, tx_id))
                return None

        print("Transaction not yet submitted to nodes")
        print(f"To get status, use command: chia wallet get_transaction -f {fingerprint} -tx 0x{tx_id}")


async def get_address(wallet_rpc_port: Optional[int], fp: Optional[int], wallet_id: int, new_address: bool) -> None:
    async with get_wallet_client(wallet_rpc_port, fp) as (wallet_client, fingerprint, config):
        res = await wallet_client.get_next_address(wallet_id, new_address)
        print(res)


async def delete_unconfirmed_transactions(wallet_rpc_port: Optional[int], fp: Optional[int], wallet_id: int) -> None:
    async with get_wallet_client(wallet_rpc_port, fp) as (wallet_client, fingerprint, _):
        await wallet_client.delete_unconfirmed_transactions(wallet_id)
        print(f"Successfully deleted all unconfirmed transactions for wallet id {wallet_id} on key {fingerprint}")


async def get_derivation_index(wallet_rpc_port: Optional[int], fp: Optional[int]) -> None:
    async with get_wallet_client(wallet_rpc_port, fp) as (wallet_client, _, _):
        res = await wallet_client.get_current_derivation_index()
        print(f"Last derivation index: {res}")


async def update_derivation_index(wallet_rpc_port: Optional[int], fp: Optional[int], index: int) -> None:
    async with get_wallet_client(wallet_rpc_port, fp) as (wallet_client, _, _):
        print("Updating derivation index... This may take a while.")
        res = await wallet_client.extend_derivation_index(index)
        print(f"Updated derivation index: {res}")
        print("Your balances may take a while to update.")


async def add_token(wallet_rpc_port: Optional[int], fp: Optional[int], asset_id: str, token_name: str) -> None:
    async with get_wallet_client(wallet_rpc_port, fp) as (wallet_client, fingerprint, _):
        try:
            asset_id_bytes: bytes32 = bytes32.from_hexstr(asset_id)
            existing_info: Optional[Tuple[Optional[uint32], str]] = await wallet_client.cat_asset_id_to_name(
                asset_id_bytes
            )
            if existing_info is None or existing_info[0] is None:
                response = await wallet_client.create_wallet_for_existing_cat(asset_id_bytes)
                wallet_id = response["wallet_id"]
                await wallet_client.set_cat_name(wallet_id, token_name)
                print(f"Successfully added {token_name} with wallet id {wallet_id} on key {fingerprint}")
            else:
                wallet_id, old_name = existing_info
                await wallet_client.set_cat_name(wallet_id, token_name)
                print(
                    f"Successfully renamed {old_name} with wallet_id {wallet_id} on key {fingerprint} to {token_name}"
                )
        except ValueError as e:
            if "fromhex()" in str(e):
                print(f"{asset_id} is not a valid Asset ID")
            else:
                raise


async def make_offer(
    *,
    wallet_rpc_port: Optional[int],
    fp: Optional[int],
    d_fee: Decimal,
    offers: Sequence[str],
    requests: Sequence[str],
    filepath: str,
    reuse_puzhash: Optional[bool],
) -> None:
    async with get_wallet_client(wallet_rpc_port, fp) as (wallet_client, fingerprint, config):
        fee: int = int(d_fee * units["chia"])

        if offers == [] or requests == []:
            print("Not creating offer: Must be offering and requesting at least one asset")
        else:
            offer_dict: Dict[Union[uint32, str], int] = {}
            driver_dict: Dict[str, Any] = {}
            printable_dict: Dict[str, Tuple[str, int, int]] = {}  # Dict[asset_name, Tuple[amount, unit, multiplier]]
            royalty_asset_dict: Dict[Any, Tuple[Any, uint16]] = {}
            fungible_asset_dict: Dict[Any, uint64] = {}
            for item in [*offers, *requests]:
                name, amount = tuple(item.split(":")[0:2])
                try:
                    b32_id = bytes32.from_hexstr(name)
                    id: Union[uint32, str] = b32_id.hex()
                    result = await wallet_client.cat_asset_id_to_name(b32_id)
                    if result is not None:
                        name = result[1]
                    else:
                        name = "Unknown CAT"
                    unit = units["cat"]
                    if item in offers:
                        fungible_asset_dict[name] = uint64(abs(int(Decimal(amount) * unit)))
                except ValueError:
                    try:
                        hrp, _ = bech32_decode(name)
                        if hrp == "nft":
                            coin_id = decode_puzzle_hash(name)
                            unit = 1
                            info = NFTInfo.from_json_dict((await wallet_client.get_nft_info(coin_id.hex()))["nft_info"])
                            id = info.launcher_id.hex()
                            assert isinstance(id, str)
                            if item in requests:
                                driver_dict[id] = {
                                    "type": "singleton",
                                    "launcher_id": "0x" + id,
                                    "launcher_ph": "0x" + info.launcher_puzhash.hex(),
                                    "also": {
                                        "type": "metadata",
                                        "metadata": info.chain_info,
                                        "updater_hash": "0x" + info.updater_puzhash.hex(),
                                    },
                                }
                                if info.supports_did:
                                    assert info.royalty_puzzle_hash is not None
                                    assert info.royalty_percentage is not None
                                    driver_dict[id]["also"]["also"] = {
                                        "type": "ownership",
                                        "owner": "()",
                                        "transfer_program": {
                                            "type": "royalty transfer program",
                                            "launcher_id": "0x" + info.launcher_id.hex(),
                                            "royalty_address": "0x" + info.royalty_puzzle_hash.hex(),
                                            "royalty_percentage": str(info.royalty_percentage),
                                        },
                                    }
                                    royalty_asset_dict[name] = (
                                        encode_puzzle_hash(info.royalty_puzzle_hash, AddressType.XCH.hrp(config)),
                                        info.royalty_percentage,
                                    )
                        else:
                            id = decode_puzzle_hash(name).hex()
                            assert hrp is not None
                            unit = units[hrp]
                    except ValueError:
                        id = uint32(int(name))
                        if id == 1:
                            name = "XCH"
                            unit = units["chia"]
                        else:
                            name = await wallet_client.get_cat_name(id)
                            unit = units["cat"]
                        if item in offers:
                            fungible_asset_dict[name] = uint64(abs(int(Decimal(amount) * unit)))
                multiplier: int = -1 if item in offers else 1
                printable_dict[name] = (amount, unit, multiplier)
                if id in offer_dict:
                    print("Not creating offer: Cannot offer and request the same asset in a trade")
                    break
                else:
                    offer_dict[id] = int(Decimal(amount) * unit) * multiplier
            else:
                print("Creating Offer")
                print("--------------")
                print()
                print("OFFERING:")
                for name, data in printable_dict.items():
                    amount, unit, multiplier = data
                    if multiplier < 0:
                        print(f"  - {amount} {name} ({int(Decimal(amount) * unit)} mojos)")
                print("REQUESTING:")
                for name, data in printable_dict.items():
                    amount, unit, multiplier = data
                    if multiplier > 0:
                        print(f"  - {amount} {name} ({int(Decimal(amount) * unit)} mojos)")

                if fee > 0:
                    print()
                    print(f"Including Fees: {Decimal(fee) / units['chia']} XCH, {fee} mojos")

                if royalty_asset_dict != {}:
                    royalty_summary: Dict[Any, List[Dict[str, Any]]] = await wallet_client.nft_calculate_royalties(
                        royalty_asset_dict, fungible_asset_dict
                    )
                    total_amounts_requested: Dict[Any, int] = {}
                    print()
                    print("Royalties Summary:")
                    for nft_id, summaries in royalty_summary.items():
                        print(f"  - For {nft_id}:")
                        for summary in summaries:
                            divisor = units["chia"] if summary["asset"] == "XCH" else units["cat"]
                            converted_amount = Decimal(summary["amount"]) / divisor
                            total_amounts_requested.setdefault(summary["asset"], fungible_asset_dict[summary["asset"]])
                            total_amounts_requested[summary["asset"]] += summary["amount"]
                            print(
                                f"    - {converted_amount} {summary['asset']} ({summary['amount']} mojos) to {summary['address']}"  # noqa
                            )

                    print()
                    print("Total Amounts Offered:")
                    for asset, requested_amount in total_amounts_requested.items():
                        divisor = units["chia"] if asset == "XCH" else units["cat"]
                        converted_amount = Decimal(requested_amount) / divisor
                        print(f"  - {converted_amount} {asset} ({requested_amount} mojos)")

                    print()
                    nft_confirmation = input(
                        "Offers for NFTs will have royalties automatically added. "
                        + "Are you sure you would like to continue? (y/n): "
                    )
                    if nft_confirmation not in ["y", "yes"]:
                        print("Not creating offer...")
                        return

                confirmation = input("Confirm (y/n): ")
                if confirmation not in ["y", "yes"]:
                    print("Not creating offer...")
                else:
                    with open(pathlib.Path(filepath), "w") as file:
                        offer, trade_record = await wallet_client.create_offer_for_ids(
                            offer_dict, driver_dict=driver_dict, fee=fee, reuse_puzhash=reuse_puzhash
                        )
                        if offer is not None:
                            file.write(offer.to_bech32())
                            print(f"Created offer with ID {trade_record.trade_id}")
                            print(
                                f"Use chia wallet get_offers --id "
                                f"{trade_record.trade_id} -f {fingerprint} to view status"
                            )
                        else:
                            print("Error creating offer")


def timestamp_to_time(timestamp: int) -> str:
    return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S")


async def print_offer_summary(
    cat_name_resolver: CATNameResolver, sum_dict: Dict[str, int], has_fee: bool = False, network_xch: str = "XCH"
) -> None:
    for asset_id, amount in sum_dict.items():
        description: str = ""
        unit: int = units["chia"]
        wid: str = "1" if asset_id == "xch" else ""
        mojo_amount: int = int(Decimal(amount))
        name: str = network_xch
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


async def print_trade_record(record: TradeRecord, wallet_client: WalletRpcClient, summaries: bool = False) -> None:
    print()
    print(f"Record with id: {record.trade_id}")
    print("---------------")
    print(f"Created at: {timestamp_to_time(record.created_at_time)}")
    print(f"Confirmed at: {record.confirmed_at_index if record.confirmed_at_index > 0 else 'Not confirmed'}")
    print(f"Accepted at: {timestamp_to_time(record.accepted_at_time) if record.accepted_at_time else 'N/A'}")
    print(f"Status: {TradeStatus(record.status).name}")
    if summaries:
        print("Summary:")
        offer = Offer.from_bytes(record.offer)
        offered, requested, _ = offer.summary()
        outbound_balances: Dict[str, int] = offer.get_pending_amounts()
        fees: Decimal = Decimal(offer.fees())
        cat_name_resolver = wallet_client.cat_asset_id_to_name
        print("  OFFERED:")
        await print_offer_summary(cat_name_resolver, offered)
        print("  REQUESTED:")
        await print_offer_summary(cat_name_resolver, requested)
        print("Pending Outbound Balances:")
        await print_offer_summary(cat_name_resolver, outbound_balances, has_fee=(fees > 0))
        print(f"Included Fees: {fees / units['chia']} XCH, {fees} mojos")
    print("---------------")


async def get_offers(
    *,
    wallet_rpc_port: Optional[int],
    fp: Optional[int],
    offer_id: Optional[str],
    filepath: Optional[str],
    exclude_my_offers: bool = False,
    exclude_taken_offers: bool = False,
    include_completed: bool = False,
    summaries: bool = False,
    reverse: bool = False,
) -> None:
    async with get_wallet_client(wallet_rpc_port, fp) as (wallet_client, fingerprint, config):
        file_contents: bool = (filepath is not None) or summaries
        records: List[TradeRecord] = []
        if offer_id is None:
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
            records = [await wallet_client.get_offer(bytes32.from_hexstr(offer_id), file_contents)]
            if filepath is not None:
                with open(pathlib.Path(filepath), "w") as file:
                    file.write(Offer.from_bytes(records[0].offer).to_bech32())
                    file.close()

        for record in records:
            await print_trade_record(record, wallet_client, summaries=summaries)


async def take_offer(
    wallet_rpc_port: Optional[int],
    fp: Optional[int],
    d_fee: Decimal,
    file: str,
    examine_only: bool,
) -> None:
    async with get_wallet_client(wallet_rpc_port, fp) as (wallet_client, fingerprint, config):
        if os.path.exists(file):
            filepath = pathlib.Path(file)
            with open(filepath, "r") as ffile:
                offer_hex: str = ffile.read()
                ffile.close()
        else:
            offer_hex = file

        fee: int = int(d_fee * units["chia"])

        try:
            offer = Offer.from_bech32(offer_hex)
        except ValueError:
            print("Please enter a valid offer file or hex blob")
            return

        ###
        # This is temporary code, delete it when we no longer care about incorrectly parsing CAT1s
        # There's also temp code in test_wallet_rpc.py and wallet_rpc_api.py
        from chia.types.spend_bundle import SpendBundle
        from chia.util.bech32m import bech32_decode, convertbits
        from chia.wallet.util.puzzle_compression import decompress_object_with_puzzles

        hrpgot, data = bech32_decode(offer_hex, max_length=len(offer_hex))
        if data is None:
            raise ValueError("Invalid Offer")
        decoded = convertbits(list(data), 5, 8, False)
        decoded_bytes = bytes(decoded)
        try:
            decompressed_bytes = decompress_object_with_puzzles(decoded_bytes)
        except TypeError:
            decompressed_bytes = decoded_bytes
        bundle = SpendBundle.from_bytes(decompressed_bytes)
        for spend in bundle.coin_spends:
            mod, _ = spend.puzzle_reveal.to_program().uncurry()
            if mod.get_tree_hash() == bytes32.from_hexstr(
                "72dec062874cd4d3aab892a0906688a1ae412b0109982e1797a170add88bdcdc"
            ):
                raise ValueError("CAT1s are no longer supported")
        ###

        offered, requested, _ = offer.summary()
        cat_name_resolver = wallet_client.cat_asset_id_to_name
        network_xch = AddressType.XCH.hrp(config).upper()
        print("Summary:")
        print("  OFFERED:")
        await print_offer_summary(cat_name_resolver, offered, network_xch=network_xch)
        print("  REQUESTED:")
        await print_offer_summary(cat_name_resolver, requested, network_xch=network_xch)

        print()

        royalty_asset_dict: Dict[Any, Tuple[Any, uint16]] = {}
        for royalty_asset_id in nft_coin_ids_supporting_royalties_from_offer(offer):
            if royalty_asset_id.hex() in offered:
                percentage, address = await get_nft_royalty_percentage_and_address(royalty_asset_id, wallet_client)
                royalty_asset_dict[encode_puzzle_hash(royalty_asset_id, AddressType.NFT.hrp(config))] = (
                    encode_puzzle_hash(address, AddressType.XCH.hrp(config)),
                    percentage,
                )

        if royalty_asset_dict != {}:
            fungible_asset_dict: Dict[Any, uint64] = {}
            for fungible_asset_id in fungible_assets_from_offer(offer):
                fungible_asset_id_str = fungible_asset_id.hex() if fungible_asset_id is not None else "xch"
                if fungible_asset_id_str in requested:
                    nft_royalty_currency: str = "Unknown CAT"
                    if fungible_asset_id is None:
                        nft_royalty_currency = network_xch
                    else:
                        result = await wallet_client.cat_asset_id_to_name(fungible_asset_id)
                        if result is not None:
                            nft_royalty_currency = result[1]
                    fungible_asset_dict[nft_royalty_currency] = uint64(requested[fungible_asset_id_str])

            if fungible_asset_dict != {}:
                royalty_summary: Dict[Any, List[Dict[str, Any]]] = await wallet_client.nft_calculate_royalties(
                    royalty_asset_dict, fungible_asset_dict
                )
                total_amounts_requested: Dict[Any, int] = {}
                print("Royalties Summary:")
                for nft_id, summaries in royalty_summary.items():
                    print(f"  - For {nft_id}:")
                    for summary in summaries:
                        divisor = units["chia"] if summary["asset"] == network_xch else units["cat"]
                        converted_amount = Decimal(summary["amount"]) / divisor
                        total_amounts_requested.setdefault(summary["asset"], fungible_asset_dict[summary["asset"]])
                        total_amounts_requested[summary["asset"]] += summary["amount"]
                        print(
                            f"    - {converted_amount} {summary['asset']} ({summary['amount']} mojos) to {summary['address']}"  # noqa
                        )

                print()
                print("Total Amounts Requested:")
                for asset, amount in total_amounts_requested.items():
                    divisor = units["chia"] if asset == network_xch else units["cat"]
                    converted_amount = Decimal(amount) / divisor
                    print(f"  - {converted_amount} {asset} ({amount} mojos)")

        print(f"Included Fees: {Decimal(offer.fees()) / units['chia']} {network_xch}, {offer.fees()} mojos")

        if not examine_only:
            print()
            confirmation = input("Would you like to take this offer? (y/n): ")
            if confirmation in ["y", "yes"]:
                trade_record = await wallet_client.take_offer(offer, fee=fee)
                print(f"Accepted offer with ID {trade_record.trade_id}")
                print(f"Use chia wallet get_offers --id {trade_record.trade_id} -f {fingerprint} to view its status")


async def cancel_offer(
    wallet_rpc_port: Optional[int], fp: Optional[int], d_fee: Decimal, offer_id_hex: str, secure: bool
) -> None:
    async with get_wallet_client(wallet_rpc_port, fp) as (wallet_client, fingerprint, config):
        offer_id = bytes32.from_hexstr(offer_id_hex)
        fee: int = int(d_fee * units["chia"])

        trade_record = await wallet_client.get_offer(offer_id, file_contents=True)
        await print_trade_record(trade_record, wallet_client, summaries=True)

        confirmation = input(f"Are you sure you wish to cancel offer with ID: {trade_record.trade_id}? (y/n): ")
        if confirmation in ["y", "yes"]:
            await wallet_client.cancel_offer(offer_id, secure=secure, fee=fee)
            print(f"Cancelled offer with ID {trade_record.trade_id}")
            if secure:
                print(f"Use chia wallet get_offers --id {trade_record.trade_id} -f {fingerprint} to view cancel status")


def wallet_coin_unit(typ: WalletType, address_prefix: str) -> Tuple[str, int]:
    if typ == WalletType.CAT:
        return "", units["cat"]
    if typ in [WalletType.STANDARD_WALLET, WalletType.POOLING_WALLET, WalletType.MULTI_SIG]:
        return address_prefix, units["chia"]
    return "", units["mojo"]


def print_balance(amount: int, scale: int, address_prefix: str, *, decimal_only: bool = False) -> str:
    if decimal_only:  # dont use scientific notation.
        final_amount = f"{amount / scale:.12f}"
    else:
        final_amount = f"{amount / scale}"
    ret = f"{final_amount} {address_prefix} "
    if scale > 1:
        ret += f"({amount} mojo)"
    return ret


async def print_balances(
    wallet_rpc_port: Optional[int], fp: Optional[int], wallet_type: Optional[WalletType] = None
) -> None:
    async with get_wallet_client(wallet_rpc_port, fp) as (wallet_client, fingerprint, config):
        summaries_response = await wallet_client.get_wallets(wallet_type)
        address_prefix = selected_network_address_prefix(config)

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
                print(f"{indent}{'-Pending Total Balance:'.ljust(23)} {unconfirmed_wallet_balance}")
                print(f"{indent}{'-Spendable:'.ljust(23)} {spendable_balance}")
                print(f"{indent}{'-Type:'.ljust(23)} {typ.name}")
                if typ == WalletType.DECENTRALIZED_ID:
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
        trusted_peers: dict[str, str] = config["wallet"].get("trusted_peers", {})
        await print_connections(wallet_client, trusted_peers)


async def create_did_wallet(
    wallet_rpc_port: Optional[int], fp: Optional[int], d_fee: Decimal, name: Optional[str], amount: int
) -> None:
    async with get_wallet_client(wallet_rpc_port, fp) as (wallet_client, fingerprint, config):
        fee: int = int(d_fee * units["chia"])
        try:
            response = await wallet_client.create_new_did_wallet(amount, fee, name)
            wallet_id = response["wallet_id"]
            my_did = response["my_did"]
            print(f"Successfully created a DID wallet with name {name} and id {wallet_id} on key {fingerprint}")
            print(f"Successfully created a DID {my_did} in the newly created DID wallet")
        except Exception as e:
            print(f"Failed to create DID wallet: {e}")


async def did_set_wallet_name(wallet_rpc_port: Optional[int], fp: Optional[int], wallet_id: int, name: str) -> None:
    async with get_wallet_client(wallet_rpc_port, fp) as (wallet_client, fingerprint, config):
        try:
            await wallet_client.did_set_wallet_name(wallet_id, name)
            print(f"Successfully set a new name for DID wallet with id {wallet_id}: {name}")
        except Exception as e:
            print(f"Failed to set DID wallet name: {e}")


async def get_did(wallet_rpc_port: Optional[int], fp: Optional[int], did_wallet_id: int) -> None:
    async with get_wallet_client(wallet_rpc_port, fp) as (wallet_client, fingerprint, config):
        try:
            response = await wallet_client.get_did_id(did_wallet_id)
            my_did = response["my_did"]
            coin_id = response["coin_id"]
            print(f"{'DID:'.ljust(23)} {my_did}")
            print(f"{'Coin ID:'.ljust(23)} {coin_id}")
        except Exception as e:
            print(f"Failed to get DID: {e}")


async def get_did_info(wallet_rpc_port: Optional[int], fp: Optional[int], coin_id: str, latest: bool) -> None:
    async with get_wallet_client(wallet_rpc_port, fp) as (wallet_client, fingerprint, config):
        did_padding_length = 23
        try:
            response = await wallet_client.get_did_info(coin_id, latest)
            print(f"{'DID:'.ljust(did_padding_length)} {response['did_id']}")
            print(f"{'Coin ID:'.ljust(did_padding_length)} {response['latest_coin']}")
            print(f"{'Inner P2 Address:'.ljust(did_padding_length)} {response['p2_address']}")
            print(f"{'Public Key:'.ljust(did_padding_length)} {response['public_key']}")
            print(f"{'Launcher ID:'.ljust(did_padding_length)} {response['launcher_id']}")
            print(f"{'DID Metadata:'.ljust(did_padding_length)} {response['metadata']}")
            print(f"{'Recovery List Hash:'.ljust(did_padding_length)} {response['recovery_list_hash']}")
            print(f"{'Recovery Required Verifications:'.ljust(did_padding_length)} {response['num_verification']}")
            print(f"{'Last Spend Puzzle:'.ljust(did_padding_length)} {response['full_puzzle']}")
            print(f"{'Last Spend Solution:'.ljust(did_padding_length)} {response['solution']}")
            print(f"{'Last Spend Hints:'.ljust(did_padding_length)} {response['hints']}")

        except Exception as e:
            print(f"Failed to get DID details: {e}")


async def update_did_metadata(
    wallet_rpc_port: Optional[int], fp: Optional[int], did_wallet_id: int, metadata: str, reuse_puzhash: bool
) -> None:
    async with get_wallet_client(wallet_rpc_port, fp) as (wallet_client, fingerprint, config):
        try:
            response = await wallet_client.update_did_metadata(did_wallet_id, json.loads(metadata), reuse_puzhash)
            print(
                f"Successfully updated DID wallet ID: {response['wallet_id']}, Spend Bundle: {response['spend_bundle']}"
            )
        except Exception as e:
            print(f"Failed to update DID metadata: {e}")


async def did_message_spend(
    wallet_rpc_port: Optional[int],
    fp: Optional[int],
    did_wallet_id: int,
    puzzle_announcements: List[str],
    coin_announcements: List[str],
) -> None:
    async with get_wallet_client(wallet_rpc_port, fp) as (wallet_client, fingerprint, config):
        try:
            response = await wallet_client.did_message_spend(did_wallet_id, puzzle_announcements, coin_announcements)
            print(f"Message Spend Bundle: {response['spend_bundle']}")
        except Exception as e:
            print(f"Failed to update DID metadata: {e}")


async def transfer_did(
    wallet_rpc_port: Optional[int],
    fp: Optional[int],
    did_wallet_id: int,
    fee: int,
    target_address: str,
    with_recovery: bool,
    reuse_puzhash: Optional[bool],
) -> None:
    async with get_wallet_client(wallet_rpc_port, fp) as (wallet_client, fingerprint, config):
        try:
            response = await wallet_client.did_transfer_did(
                did_wallet_id,
                target_address,
                fee,
                with_recovery,
                reuse_puzhash,
            )
            print(f"Successfully transferred DID to {target_address}")
            print(f"Transaction ID: {response['transaction_id']}")
            print(f"Transaction: {response['transaction']}")
        except Exception as e:
            print(f"Failed to transfer DID: {e}")


async def find_lost_did(
    *,
    wallet_rpc_port: Optional[int],
    fp: Optional[int],
    coin_id: str,
    metadata: Optional[Any],
    recovery_list_hash: Optional[str],
    num_verification: Optional[int],
) -> None:
    async with get_wallet_client(wallet_rpc_port, fp) as (wallet_client, fingerprint, config):
        try:
            response = await wallet_client.find_lost_did(
                coin_id,
                recovery_list_hash,
                metadata,
                num_verification,
            )
            if response["success"]:
                print(f"Successfully found lost DID {coin_id}, latest coin ID: {response['latest_coin_id']}")
            else:
                print(f"Cannot find lost DID {coin_id}: {response['error']}")
        except Exception as e:
            print(f"Failed to find lost DID: {e}")


async def create_nft_wallet(
    wallet_rpc_port: Optional[int], fp: Optional[int], did_id: Optional[str] = None, name: Optional[str] = None
) -> None:
    async with get_wallet_client(wallet_rpc_port, fp) as (wallet_client, fingerprint, config):
        try:
            response = await wallet_client.create_new_nft_wallet(did_id, name)
            wallet_id = response["wallet_id"]
            print(f"Successfully created an NFT wallet with id {wallet_id} on key {fingerprint}")
        except Exception as e:
            print(f"Failed to create NFT wallet: {e}")


async def mint_nft(
    *,
    wallet_rpc_port: Optional[int],
    fp: Optional[int],
    wallet_id: int,
    royalty_address: Optional[str],
    target_address: Optional[str],
    no_did_ownership: bool,
    hash: str,
    uris: List[str],
    metadata_hash: Optional[str],
    metadata_uris: List[str],
    license_hash: Optional[str],
    license_uris: List[str],
    edition_total: Optional[int],
    edition_number: Optional[int],
    d_fee: Decimal,
    royalty_percentage: int,
    reuse_puzhash: Optional[bool],
) -> None:
    async with get_wallet_client(wallet_rpc_port, fp) as (wallet_client, fingerprint, config):
        royalty_address = (
            None
            if not royalty_address
            else ensure_valid_address(royalty_address, allowed_types={AddressType.XCH}, config=config)
        )
        target_address = (
            None
            if not target_address
            else ensure_valid_address(target_address, allowed_types={AddressType.XCH}, config=config)
        )
        fee: int = int(d_fee * units["chia"])
        try:
            response = await wallet_client.get_nft_wallet_did(wallet_id)
            wallet_did = response["did_id"]
            wallet_has_did = wallet_did is not None
            did_id: Optional[str] = wallet_did
            # Handle the case when the user wants to disable DID ownership
            if no_did_ownership:
                if wallet_has_did:
                    raise ValueError("Disabling DID ownership is not supported for this NFT wallet, it does have a DID")
                else:
                    did_id = None
            else:
                if not wallet_has_did:
                    did_id = ""

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
                edition_total,
                edition_number,
                fee,
                royalty_percentage,
                did_id,
                reuse_puzhash=reuse_puzhash,
            )
            spend_bundle = response["spend_bundle"]
            print(f"NFT minted Successfully with spend bundle: {spend_bundle}")
        except Exception as e:
            print(f"Failed to mint NFT: {e}")


async def add_uri_to_nft(
    *,
    wallet_rpc_port: Optional[int],
    fp: Optional[int],
    wallet_id: int,
    d_fee: Decimal,
    nft_coin_id: str,
    uri: str,
    metadata_uri: str,
    license_uri: str,
    reuse_puzhash: Optional[bool],
) -> None:
    async with get_wallet_client(wallet_rpc_port, fp) as (wallet_client, fingerprint, config):
        try:
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
            fee: int = int(d_fee * units["chia"])
            response = await wallet_client.add_uri_to_nft(wallet_id, nft_coin_id, key, uri_value, fee, reuse_puzhash)
            spend_bundle = response["spend_bundle"]
            print(f"URI added successfully with spend bundle: {spend_bundle}")
        except Exception as e:
            print(f"Failed to add URI to NFT: {e}")


async def transfer_nft(
    *,
    wallet_rpc_port: Optional[int],
    fp: Optional[int],
    wallet_id: int,
    d_fee: Decimal,
    nft_coin_id: str,
    target_address: str,
    reuse_puzhash: Optional[bool],
) -> None:
    async with get_wallet_client(wallet_rpc_port, fp) as (wallet_client, fingerprint, config):
        try:
            target_address = ensure_valid_address(target_address, allowed_types={AddressType.XCH}, config=config)
            fee: int = int(d_fee * units["chia"])
            response = await wallet_client.transfer_nft(
                wallet_id, nft_coin_id, target_address, fee, reuse_puzhash=reuse_puzhash
            )
            spend_bundle = response["spend_bundle"]
            print(f"NFT transferred successfully with spend bundle: {spend_bundle}")
        except Exception as e:
            print(f"Failed to transfer NFT: {e}")


def print_nft_info(nft: NFTInfo, *, config: Dict[str, Any]) -> None:
    indent: str = "   "
    owner_did = None if nft.owner_did is None else encode_puzzle_hash(nft.owner_did, AddressType.DID.hrp(config))
    minter_did = None if nft.minter_did is None else encode_puzzle_hash(nft.minter_did, AddressType.DID.hrp(config))
    print()
    print(f"{'NFT identifier:'.ljust(26)} {encode_puzzle_hash(nft.launcher_id, AddressType.NFT.hrp(config))}")
    print(f"{'Launcher coin ID:'.ljust(26)} {nft.launcher_id}")
    print(f"{'Launcher puzhash:'.ljust(26)} {nft.launcher_puzhash}")
    print(f"{'Current NFT coin ID:'.ljust(26)} {nft.nft_coin_id}")
    print(f"{'On-chain data/info:'.ljust(26)} {nft.chain_info}")
    print(f"{'Owner DID:'.ljust(26)} {owner_did}")
    print(f"{'Minter DID:'.ljust(26)} {minter_did}")
    print(f"{'Royalty percentage:'.ljust(26)} {nft.royalty_percentage}")
    print(f"{'Royalty puzhash:'.ljust(26)} {nft.royalty_puzzle_hash}")
    print(f"{'NFT content hash:'.ljust(26)} {nft.data_hash.hex()}")
    print(f"{'Metadata hash:'.ljust(26)} {nft.metadata_hash.hex()}")
    print(f"{'License hash:'.ljust(26)} {nft.license_hash.hex()}")
    print(f"{'NFT edition total:'.ljust(26)} {nft.edition_total}")
    print(f"{'Current NFT number in the edition:'.ljust(26)} {nft.edition_number}")
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


async def list_nfts(wallet_rpc_port: Optional[int], fp: Optional[int], wallet_id: int) -> None:
    async with get_wallet_client(wallet_rpc_port, fp) as (wallet_client, fingerprint, config):
        try:
            response = await wallet_client.list_nfts(wallet_id)
            nft_list = response["nft_list"]
            if len(nft_list) > 0:
                for n in nft_list:
                    nft = NFTInfo.from_json_dict(n)
                    print_nft_info(nft, config=config)
            else:
                print(f"No NFTs found for wallet with id {wallet_id} on key {fingerprint}")
        except Exception as e:
            print(f"Failed to list NFTs for wallet with id {wallet_id} on key {fingerprint}: {e}")


async def set_nft_did(
    *,
    wallet_rpc_port: Optional[int],
    fp: Optional[int],
    wallet_id: int,
    d_fee: Decimal,
    nft_coin_id: str,
    did_id: str,
    reuse_puzhash: Optional[bool],
) -> None:
    async with get_wallet_client(wallet_rpc_port, fp) as (wallet_client, fingerprint, config):
        fee: int = int(d_fee * units["chia"])
        try:
            response = await wallet_client.set_nft_did(wallet_id, did_id, nft_coin_id, fee, reuse_puzhash=reuse_puzhash)
            spend_bundle = response["spend_bundle"]
            print(f"Transaction to set DID on NFT has been initiated with: {spend_bundle}")
        except Exception as e:
            print(f"Failed to set DID on NFT: {e}")


async def get_nft_info(wallet_rpc_port: Optional[int], fp: Optional[int], nft_coin_id: str) -> None:
    async with get_wallet_client(wallet_rpc_port, fp) as (wallet_client, fingerprint, config):
        try:
            response = await wallet_client.get_nft_info(nft_coin_id)
            nft_info = NFTInfo.from_json_dict(response["nft_info"])
            print_nft_info(nft_info, config=config)
        except Exception as e:
            print(f"Failed to get NFT info: {e}")


async def get_nft_royalty_percentage_and_address(
    nft_coin_id: bytes32, wallet_client: WalletRpcClient
) -> Tuple[uint16, bytes32]:
    info = NFTInfo.from_json_dict((await wallet_client.get_nft_info(nft_coin_id.hex()))["nft_info"])
    assert info.royalty_puzzle_hash is not None
    percentage = uint16(info.royalty_percentage) if info.royalty_percentage is not None else 0
    return uint16(percentage), info.royalty_puzzle_hash


def calculate_nft_royalty_amount(
    offered: Dict[str, Any], requested: Dict[str, Any], nft_coin_id: bytes32, nft_royalty_percentage: int
) -> Tuple[str, int, int]:
    nft_asset_id = nft_coin_id.hex()
    amount_dict: Dict[str, Any] = requested if nft_asset_id in offered else offered
    amounts: List[Tuple[str, int]] = list(amount_dict.items())

    if len(amounts) != 1 or not isinstance(amounts[0][1], int):
        raise ValueError("Royalty enabled NFTs only support offering/requesting one NFT for one currency")

    royalty_amount: uint64 = uint64(amounts[0][1] * nft_royalty_percentage / 10000)
    royalty_asset_id = amounts[0][0]
    total_amount_requested = (requested[royalty_asset_id] if amount_dict == requested else 0) + royalty_amount
    return royalty_asset_id, royalty_amount, total_amount_requested


def driver_dict_asset_is_nft_supporting_royalties(driver_dict: Dict[bytes32, PuzzleInfo], asset_id: bytes32) -> bool:
    asset_dict: PuzzleInfo = driver_dict[asset_id]
    return asset_dict.check_type(
        [
            AssetType.SINGLETON.value,
            AssetType.METADATA.value,
            AssetType.OWNERSHIP.value,
        ]
    )


def driver_dict_asset_is_fungible(driver_dict: Dict[bytes32, PuzzleInfo], asset_id: bytes32) -> bool:
    asset_dict: PuzzleInfo = driver_dict[asset_id]
    return not asset_dict.check_type(
        [
            AssetType.SINGLETON.value,
        ]
    )


def nft_coin_ids_supporting_royalties_from_offer(offer: Offer) -> List[bytes32]:
    return [
        key for key in offer.driver_dict.keys() if driver_dict_asset_is_nft_supporting_royalties(offer.driver_dict, key)
    ]


def fungible_assets_from_offer(offer: Offer) -> List[Optional[bytes32]]:
    return [
        asset for asset in offer.arbitrage() if asset is None or driver_dict_asset_is_fungible(offer.driver_dict, asset)
    ]


async def send_notification(
    wallet_rpc_port: Optional[int],
    fp: Optional[int],
    d_fee: Decimal,
    address_str: str,
    message_hex: str,
    d_amount: Decimal,
) -> None:
    async with get_wallet_client(wallet_rpc_port, fp) as (wallet_client, fingerprint, config):
        address: bytes32 = decode_puzzle_hash(address_str)
        amount: uint64 = uint64(d_amount * units["chia"])
        message: bytes = bytes(message_hex, "utf8")
        fee: uint64 = uint64(d_fee * units["chia"])

        tx = await wallet_client.send_notification(address, message, amount, fee)

        print("Notification sent successfully.")
        print(f"To get status, use command: chia wallet get_transaction -f {fingerprint} -tx 0x{tx.name}")


async def get_notifications(
    wallet_rpc_port: Optional[int], fp: Optional[int], str_ids: Sequence[str], start: Optional[int], end: Optional[int]
) -> None:
    async with get_wallet_client(wallet_rpc_port, fp) as (wallet_client, fingerprint, config):
        ids: Optional[List[bytes32]] = [bytes32.from_hexstr(sid) for sid in str_ids]
        if ids is not None and len(ids) == 0:
            ids = None

        notifications = await wallet_client.get_notifications(ids=ids, pagination=(start, end))
        for notification in notifications:
            print("")
            print(f"ID: {notification.coin_id.hex()}")
            print(f"message: {notification.message.decode('utf-8')}")
            print(f"amount: {notification.amount}")


async def delete_notifications(
    wallet_rpc_port: Optional[int], fp: Optional[int], str_ids: Sequence[str], delete_all: bool
) -> None:
    async with get_wallet_client(wallet_rpc_port, fp) as (wallet_client, fingerprint, config):
        ids: Optional[List[bytes32]] = [bytes32.from_hexstr(sid) for sid in str_ids]

        if delete_all:
            print(f"Success: {await wallet_client.delete_notifications()}")
        else:
            print(f"Success: {await wallet_client.delete_notifications(ids=ids)}")


async def sign_message(
    *,
    wallet_rpc_port: Optional[int],
    fp: Optional[int],
    addr_type: AddressType,
    message: str,
    address: Optional[str] = None,
    did_id: Optional[str] = None,
    nft_id: Optional[str] = None,
) -> None:
    async with get_wallet_client(wallet_rpc_port, fp) as (wallet_client, fingerprint, config):
        if addr_type == AddressType.XCH:
            if address is None:
                print("Address is required for XCH address type.")
                return
            pubkey, signature, signing_mode = await wallet_client.sign_message_by_address(address, message)
        elif addr_type == AddressType.DID:
            if did_id is None:
                print("DID id is required for DID address type.")
                return
            pubkey, signature, signing_mode = await wallet_client.sign_message_by_id(did_id, message)
        elif addr_type == AddressType.NFT:
            if nft_id is None:
                print("NFT id is required for NFT address type.")
                return
            pubkey, signature, signing_mode = await wallet_client.sign_message_by_id(nft_id, message)
        else:
            print("Invalid wallet type.")
            return
        print("")
        print(f"Message: {message}")
        print(f"Public Key: {pubkey}")
        print(f"Signature: {signature}")
        print(f"Signing Mode: {signing_mode}")


async def spend_clawback(
    *, wallet_rpc_port: Optional[int], fp: Optional[int], fee: Decimal, tx_ids_str: str
) -> None:  # pragma: no cover
    async with get_wallet_client(wallet_rpc_port, fp) as (wallet_client, _, _):
        tx_ids = []
        for tid in tx_ids_str.split(","):
            tx_ids.append(bytes32.from_hexstr(tid))
        if len(tx_ids) == 0:
            print("Transaction ID is required.")
            return
        if fee < 0:
            print("Batch fee cannot be negative.")
            return
        response = await wallet_client.spend_clawback_coins(tx_ids, int(fee * units["chia"]))
        print(str(response))


async def mint_vc(
    wallet_rpc_port: Optional[int], fp: Optional[int], did: str, d_fee: Decimal, target_address: Optional[str]
) -> None:  # pragma: no cover
    async with get_wallet_client(wallet_rpc_port, fp) as (wallet_client, fingerprint, config):
        vc_record, txs = await wallet_client.vc_mint(
            decode_puzzle_hash(ensure_valid_address(did, allowed_types={AddressType.DID}, config=config)),
            None
            if target_address is None
            else decode_puzzle_hash(
                ensure_valid_address(target_address, allowed_types={AddressType.XCH}, config=config)
            ),
            uint64(int(d_fee * units["chia"])),
        )

        print(f"New VC with launcher ID minted: {vc_record.vc.launcher_id}")
        print("Relevant TX records:")
        print("")
        for tx in txs:
            print_transaction(
                tx,
                verbose=False,
                name="XCH",
                address_prefix=selected_network_address_prefix(config),
                mojo_per_unit=get_mojo_per_unit(wallet_type=WalletType.STANDARD_WALLET),
            )


async def get_vcs(
    wallet_rpc_port: Optional[int], fp: Optional[int], start: int, count: int
) -> None:  # pragma: no cover
    async with get_wallet_client(wallet_rpc_port, fp) as (wallet_client, fingerprint, config):
        vc_records, proofs = await wallet_client.vc_get_list(start, count)
        print("Proofs:")
        for hash, proof_dict in proofs.items():
            if proof_dict is not None:
                print(f"- {hash}")
                for proof in proof_dict:
                    print(f"  - {proof}")
        for record in vc_records:
            print("")
            print(f"Launcher ID: {record.vc.launcher_id.hex()}")
            print(f"Coin ID: {record.vc.coin.name().hex()}")
            print(
                f"Inner Address:"
                f" {encode_puzzle_hash(record.vc.inner_puzzle_hash,selected_network_address_prefix(config))}"
            )
            if record.vc.proof_hash is None:
                pass
            else:
                print(f"Proof Hash: {record.vc.proof_hash.hex()}")


async def spend_vc(
    *,
    wallet_rpc_port: Optional[int],
    fp: Optional[int],
    vc_id: str,
    d_fee: Decimal,
    new_puzhash: Optional[str],
    new_proof_hash: str,
    reuse_puzhash: bool,
) -> None:  # pragma: no cover
    async with get_wallet_client(wallet_rpc_port, fp) as (wallet_client, fingerprint, config):
        txs = await wallet_client.vc_spend(
            bytes32.from_hexstr(vc_id),
            new_puzhash=None if new_puzhash is None else bytes32.from_hexstr(new_puzhash),
            new_proof_hash=bytes32.from_hexstr(new_proof_hash),
            fee=uint64(int(d_fee * units["chia"])),
            reuse_puzhash=reuse_puzhash,
        )

        print("Proofs successfully updated!")
        print("Relevant TX records:")
        print("")
        for tx in txs:
            print_transaction(
                tx,
                verbose=False,
                name="XCH",
                address_prefix=selected_network_address_prefix(config),
                mojo_per_unit=get_mojo_per_unit(wallet_type=WalletType.STANDARD_WALLET),
            )


async def add_proof_reveal(
    wallet_rpc_port: Optional[int], fp: Optional[int], proofs: Sequence[str], root_only: bool
) -> None:  # pragma: no cover
    async with get_wallet_client(wallet_rpc_port, fp) as (wallet_client, fingerprint, config):
        if len(proofs) == 0:
            print("Must specify at least one proof")
            return

        proof_dict: Dict[str, str] = {proof: "1" for proof in proofs}
        if root_only:
            print(f"Proof Hash: {VCProofs(proof_dict).root()}")
            return
        else:
            await wallet_client.vc_add_proofs(proof_dict)
            print("Proofs added to DB successfully!")
            return


async def get_proofs_for_root(
    wallet_rpc_port: Optional[int], fp: Optional[int], proof_hash: str
) -> None:  # pragma: no cover
    async with get_wallet_client(wallet_rpc_port, fp) as (wallet_client, fingerprint, config):
        proof_dict: Dict[str, str] = await wallet_client.vc_get_proofs_for_root(bytes32.from_hexstr(proof_hash))
        print("Proofs:")
        for proof in proof_dict:
            print(f" - {proof}")


async def revoke_vc(
    wallet_rpc_port: Optional[int],
    fp: Optional[int],
    parent_coin_id: Optional[str],
    vc_id: Optional[str],
    fee: Decimal,
    reuse_puzhash: bool,
) -> None:  # pragma: no cover
    async with get_wallet_client(wallet_rpc_port, fp) as (wallet_client, fingerprint, config):
        if parent_coin_id is None:
            if vc_id is None:
                print("Must specify either --parent-coin-id or --vc-id")
                return
            record = await wallet_client.vc_get(bytes32.from_hexstr(vc_id))
            if record is None:
                print(f"Cannot find a VC with ID {vc_id}")
                return
            parent_id: bytes32 = record.vc.coin.parent_coin_info
        else:
            parent_id = bytes32.from_hexstr(parent_coin_id)
        txs = await wallet_client.vc_revoke(
            parent_id,
            fee=uint64(fee * units["chia"]),
            reuse_puzhash=reuse_puzhash,
        )

        print("VC successfully revoked!")
        print("Relevant TX records:")
        print("")
        for tx in txs:
            print_transaction(
                tx,
                verbose=False,
                name="XCH",
                address_prefix=selected_network_address_prefix(config),
                mojo_per_unit=get_mojo_per_unit(wallet_type=WalletType.STANDARD_WALLET),
            )
