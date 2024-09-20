from __future__ import annotations

import asyncio
import pathlib
from typing import List, Optional, Sequence

import click

from chia.cmds import options
from chia.cmds.check_wallet_db import help_text as check_help_text
from chia.cmds.cmds_util import timelock_args, tx_out_cmd
from chia.cmds.coins import coins_cmd
from chia.cmds.param_types import (
    AddressParamType,
    AmountParamType,
    Bytes32ParamType,
    CliAddress,
    CliAmount,
    cli_amount_none,
)
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.ints import uint32, uint64
from chia.wallet.conditions import ConditionValidTimes
from chia.wallet.transaction_record import TransactionRecord
from chia.wallet.transaction_sorting import SortKey
from chia.wallet.util.address_type import AddressType
from chia.wallet.util.wallet_types import WalletType


@click.group("wallet", help="Manage your wallet")
@click.pass_context
def wallet_cmd(ctx: click.Context) -> None:
    pass


@wallet_cmd.command("get_transaction", help="Get a transaction")
@click.option(
    "-wp",
    "--wallet-rpc-port",
    help="Set the port where the Wallet is hosting the RPC interface. See the rpc_port under wallet in config.yaml",
    type=int,
    default=None,
)
@options.create_fingerprint()
# TODO: Remove unused wallet id option
@click.option("-i", "--id", help="Id of the wallet to use", type=int, default=1, show_default=True, required=True)
@click.option("-tx", "--tx_id", help="transaction id to search for", type=str, required=True)
@click.option("--verbose", "-v", count=True, type=int)
def get_transaction_cmd(wallet_rpc_port: Optional[int], fingerprint: int, id: int, tx_id: str, verbose: int) -> None:
    from .wallet_funcs import get_transaction

    asyncio.run(get_transaction(wallet_rpc_port=wallet_rpc_port, fingerprint=fingerprint, tx_id=tx_id, verbose=verbose))


@wallet_cmd.command("get_transactions", help="Get all transactions")
@click.option(
    "-wp",
    "--wallet-rpc-port",
    help="Set the port where the Wallet is hosting the RPC interface. See the rpc_port under wallet in config.yaml",
    type=int,
    default=None,
)
@options.create_fingerprint()
@click.option("-i", "--id", help="Id of the wallet to use", type=int, default=1, show_default=True, required=True)
@click.option(
    "-o",
    "--offset",
    help="Skip transactions from the beginning of the list",
    type=int,
    default=0,
    show_default=True,
    required=True,
)
@click.option(
    "-l",
    "--limit",
    help="Max number of transactions to return",
    type=int,
    default=(2**32 - 1),
    show_default=True,
    required=False,
)
@click.option("--verbose", "-v", count=True, type=int)
@click.option(
    "--paginate/--no-paginate",
    default=None,
    help="Prompt for each page of data.  Defaults to true for interactive consoles, otherwise false.",
)
@click.option(
    "--sort-by-height",
    "sort_key",
    flag_value=SortKey.CONFIRMED_AT_HEIGHT,
    type=SortKey,
    help="Sort transactions by height",
)
@click.option(
    "--sort-by-relevance",
    "sort_key",
    flag_value=SortKey.RELEVANCE,
    type=SortKey,
    default=True,
    help="Sort transactions by {confirmed, height, time}",
)
@click.option(
    "--reverse",
    is_flag=True,
    default=False,
    help="Reverse the transaction ordering",
)
@click.option(
    "--clawback",
    is_flag=True,
    default=False,
    help="Only show clawback transactions",
)
def get_transactions_cmd(
    wallet_rpc_port: Optional[int],
    fingerprint: int,
    id: int,
    offset: int,
    limit: int,
    verbose: bool,
    paginate: Optional[bool],
    sort_key: SortKey,
    reverse: bool,
    clawback: bool,
) -> None:  # pragma: no cover
    from .wallet_funcs import get_transactions

    asyncio.run(
        get_transactions(
            wallet_rpc_port=wallet_rpc_port,
            fp=fingerprint,
            wallet_id=id,
            verbose=verbose,
            paginate=paginate,
            offset=offset,
            limit=limit,
            sort_key=sort_key,
            reverse=reverse,
            clawback=clawback,
        )
    )


@wallet_cmd.command("send", help="Send chia or other assets to another wallet")
@click.option(
    "-wp",
    "--wallet-rpc-port",
    help="Set the port where the Wallet is hosting the RPC interface. See the rpc_port under wallet in config.yaml",
    type=int,
    default=None,
)
@options.create_fingerprint()
@click.option("-i", "--id", help="Id of the wallet to use", type=int, default=1, show_default=True, required=True)
@click.option(
    "-a", "--amount", help="How much chia to send, in XCH or CAT units", type=AmountParamType(), required=True
)
@click.option("-e", "--memo", help="Additional memo for the transaction", type=str, default=None)
@options.create_fee()
# TODO: Fix RPC as this should take a puzzle_hash not an address.
@click.option("-t", "--address", help="Address to send the XCH", type=AddressParamType(), required=True)
@click.option(
    "-o", "--override", help="Submits transaction without checking for unusual values", is_flag=True, default=False
)
@click.option(
    "-ma",
    "--min-coin-amount",
    help="Ignore coins worth less then this much XCH or CAT units",
    type=AmountParamType(),
    required=False,
    default=cli_amount_none,
)
@click.option(
    "-l",
    "--max-coin-amount",
    help="Ignore coins worth more then this much XCH or CAT units",
    type=AmountParamType(),
    required=False,
    default=cli_amount_none,
)
@click.option(
    "--exclude-coin",
    "coins_to_exclude",
    multiple=True,
    type=Bytes32ParamType(),
    help="Exclude this coin from being spent.",
)
@click.option(
    "--reuse",
    help="Reuse existing address for the change.",
    is_flag=True,
    default=False,
)
@click.option(
    "--clawback_time",
    help="The seconds that the recipient needs to wait to claim the fund."
    " A positive number will enable the Clawback features.",
    type=int,
    default=0,
)
@tx_out_cmd()
def send_cmd(
    wallet_rpc_port: Optional[int],
    fingerprint: int,
    id: int,
    amount: CliAmount,
    memo: Optional[str],
    fee: uint64,
    address: CliAddress,
    override: bool,
    min_coin_amount: CliAmount,
    max_coin_amount: CliAmount,
    coins_to_exclude: Sequence[bytes32],
    reuse: bool,
    clawback_time: int,
    push: bool,
    condition_valid_times: ConditionValidTimes,
) -> List[TransactionRecord]:
    from .wallet_funcs import send

    return asyncio.run(
        send(
            wallet_rpc_port=wallet_rpc_port,
            fp=fingerprint,
            wallet_id=id,
            amount=amount,
            memo=memo,
            fee=fee,
            address=address,
            override=override,
            min_coin_amount=min_coin_amount,
            max_coin_amount=max_coin_amount,
            excluded_coin_ids=coins_to_exclude,
            reuse_puzhash=True if reuse else None,
            clawback_time_lock=clawback_time,
            push=push,
            condition_valid_times=condition_valid_times,
        )
    )


@wallet_cmd.command("show", help="Show wallet information")
@click.option(
    "-wp",
    "--wallet-rpc-port",
    help="Set the port where the Wallet is hosting the RPC interface. See the rpc_port under wallet in config.yaml",
    type=int,
    default=None,
)
@options.create_fingerprint()
@click.option(
    "-w",
    "--wallet_type",
    help="Choose a specific wallet type to return",
    type=click.Choice([x.name.lower() for x in WalletType]),
    default=None,
)
def show_cmd(wallet_rpc_port: Optional[int], fingerprint: int, wallet_type: Optional[str]) -> None:
    from .wallet_funcs import print_balances

    asyncio.run(print_balances(wallet_rpc_port, fingerprint, WalletType[wallet_type.upper()] if wallet_type else None))


@wallet_cmd.command("get_address", help="Get a wallet receive address")
@click.option(
    "-wp",
    "--wallet-rpc-port",
    help="Set the port where the Wallet is hosting the RPC interface. See the rpc_port under wallet in config.yaml",
    type=int,
    default=None,
)
@click.option("-i", "--id", help="Id of the wallet to use", type=int, default=1, show_default=True, required=True)
@options.create_fingerprint()
@click.option(
    "-n/-l",
    "--new-address/--latest-address",
    help=(
        "Create a new wallet receive address, or show the most recently created wallet receive address"
        "  [default: show most recent address]"
    ),
    is_flag=True,
    default=False,
)
def get_address_cmd(wallet_rpc_port: Optional[int], id: int, fingerprint: int, new_address: bool) -> None:
    from .wallet_funcs import get_address

    asyncio.run(get_address(wallet_rpc_port, fingerprint, id, new_address))


@wallet_cmd.command(
    "clawback",
    help="Claim or revert a Clawback transaction."
    " The wallet will automatically detect if you are able to revert or claim.",
)
@click.option(
    "-wp",
    "--wallet-rpc-port",
    help="Set the port where the Wallet is hosting the RPC interface. See the rpc_port under wallet in config.yaml",
    type=int,
    default=None,
)
# TODO: Remove unused wallet id option
@click.option("-i", "--id", help="Id of the wallet to use", type=int, default=1, show_default=True, required=True)
@options.create_fingerprint()
@click.option(
    "-ids",
    "--tx_ids",
    help="IDs of the Clawback transactions you want to revert or claim. Separate multiple IDs by comma (,).",
    type=str,
    default="",
    required=True,
)
@options.create_fee("A fee to add to the offer when it gets taken, in XCH")
@click.option(
    "--force",
    help="Force to push the spend bundle even it may be a double spend",
    is_flag=True,
    default=False,
)
@tx_out_cmd()
def clawback(
    wallet_rpc_port: Optional[int],
    id: int,
    fingerprint: int,
    tx_ids: str,
    fee: uint64,
    force: bool,
    push: bool,
    condition_valid_times: ConditionValidTimes,
) -> List[TransactionRecord]:
    from .wallet_funcs import spend_clawback

    return asyncio.run(
        spend_clawback(
            wallet_rpc_port=wallet_rpc_port,
            fp=fingerprint,
            fee=fee,
            tx_ids_str=tx_ids,
            force=force,
            push=push,
            condition_valid_times=condition_valid_times,
        )
    )


@wallet_cmd.command("delete_unconfirmed_transactions", help="Deletes all unconfirmed transactions for this wallet ID")
@click.option(
    "-wp",
    "--wallet-rpc-port",
    help="Set the port where the Wallet is hosting the RPC interface. See the rpc_port under wallet in config.yaml",
    type=int,
    default=None,
)
@click.option("-i", "--id", help="Id of the wallet to use", type=int, default=1, show_default=True, required=True)
@options.create_fingerprint()
def delete_unconfirmed_transactions_cmd(wallet_rpc_port: Optional[int], id: int, fingerprint: int) -> None:
    from .wallet_funcs import delete_unconfirmed_transactions

    asyncio.run(delete_unconfirmed_transactions(wallet_rpc_port, fingerprint, id))


@wallet_cmd.command("get_derivation_index", help="Get the last puzzle hash derivation path index")
@click.option(
    "-wp",
    "--wallet-rpc-port",
    help="Set the port where the Wallet is hosting the RPC interface. See the rpc_port under wallet in config.yaml",
    type=int,
    default=None,
)
@options.create_fingerprint()
def get_derivation_index_cmd(wallet_rpc_port: Optional[int], fingerprint: int) -> None:
    from .wallet_funcs import get_derivation_index

    asyncio.run(get_derivation_index(wallet_rpc_port, fingerprint))


@wallet_cmd.command("sign_message", help="Sign a message by a derivation address")
@click.option(
    "-wp",
    "--wallet-rpc-port",
    help="Set the port where the Wallet is hosting the RPC interface. See the rpc_port under wallet in config.yaml",
    type=int,
    default=None,
)
@options.create_fingerprint()
# TODO: Change RPC's to use the puzzle hash instead of address
@click.option("-a", "--address", help="The address you want to use for signing", type=AddressParamType(), required=True)
@click.option("-m", "--hex_message", help="The hex message you want sign", type=str, required=True)
def address_sign_message(
    wallet_rpc_port: Optional[int], fingerprint: int, address: CliAddress, hex_message: str
) -> None:
    from .wallet_funcs import sign_message

    asyncio.run(
        sign_message(
            wallet_rpc_port=wallet_rpc_port,
            fp=fingerprint,
            addr_type=AddressType.XCH,
            message=hex_message,
            address=address,
        )
    )


@wallet_cmd.command(
    "update_derivation_index", help="Generate additional derived puzzle hashes starting at the provided index"
)
@click.option(
    "-wp",
    "--wallet-rpc-port",
    help="Set the port where the Wallet is hosting the RPC interface. See the rpc_port under wallet in config.yaml",
    type=int,
    default=None,
)
@options.create_fingerprint()
@click.option(
    "-i", "--index", help="Index to set. Must be greater than the current derivation index", type=int, required=True
)
def update_derivation_index_cmd(wallet_rpc_port: Optional[int], fingerprint: int, index: int) -> None:
    from .wallet_funcs import update_derivation_index

    asyncio.run(update_derivation_index(wallet_rpc_port, fingerprint, index))


@wallet_cmd.command("add_token", help="Add/Rename a CAT to the wallet by its asset ID")
@click.option(
    "-wp",
    "--wallet-rpc-port",
    help="Set the port where the Wallet is hosting the RPC interface. See the rpc_port under wallet in config.yaml",
    type=int,
    default=None,
)
@click.option(
    "-id",
    "--asset-id",
    help="The Asset ID of the coin you wish to add/rename (the treehash of the TAIL program)",
    type=Bytes32ParamType(),
    required=True,
)
@click.option(
    "-n",
    "--token-name",
    help="The name you wish to designate to the token",
)
@options.create_fingerprint()
def add_token_cmd(wallet_rpc_port: Optional[int], asset_id: bytes32, token_name: str, fingerprint: int) -> None:
    from .wallet_funcs import add_token

    asyncio.run(add_token(wallet_rpc_port, fingerprint, asset_id, token_name))


@wallet_cmd.command("make_offer", help="Create an offer of XCH/CATs/NFTs for XCH/CATs/NFTs")
@click.option(
    "-wp",
    "--wallet-rpc-port",
    help="Set the port where the Wallet is hosting the RPC interface. See the rpc_port under wallet in config.yaml",
    type=int,
    default=None,
)
@options.create_fingerprint()
@click.option(
    "-o",
    "--offer",
    help="A wallet id to offer and the amount to offer (formatted like wallet_id:amount)",
    required=True,
    multiple=True,
)
@click.option(
    "-r",
    "--request",
    help="A wallet id of an asset to receive and the amount you wish to receive (formatted like wallet_id:amount)",
    multiple=True,
)
@click.option(
    "-p",
    "--filepath",
    help="The path to write the generated offer file to",
    required=True,
    type=click.Path(dir_okay=False, writable=True, path_type=pathlib.Path),
)
@options.create_fee("A fee to add to the offer when it gets taken, in XCH")
@click.option(
    "--reuse",
    help="Reuse existing address for the offer.",
    is_flag=True,
    default=False,
)
@click.option("--override", help="Creates offer without checking for unusual values", is_flag=True, default=False)
@timelock_args(enable=True)
# This command looks like a good candidate for @tx_out_cmd however, pushing an incomplete tx is nonsensical and
# we already have a canonical offer file format which the idea of exporting a different transaction conflicts with
def make_offer_cmd(
    wallet_rpc_port: Optional[int],
    fingerprint: int,
    offer: Sequence[str],
    request: Sequence[str],
    filepath: pathlib.Path,
    fee: uint64,
    reuse: bool,
    override: bool,
    condition_valid_times: ConditionValidTimes,
) -> None:
    from .wallet_funcs import make_offer

    if len(request) == 0 and not override:
        print("Cannot make an offer without requesting something without --override")
        return

    asyncio.run(
        make_offer(
            wallet_rpc_port=wallet_rpc_port,
            fp=fingerprint,
            fee=fee,
            offers=offer,
            requests=request,
            filepath=filepath,
            reuse_puzhash=True if reuse else None,
            condition_valid_times=condition_valid_times,
        )
    )


@wallet_cmd.command(
    "get_offers", help="Get the status of existing offers. Displays only active/pending offers by default."
)
@click.option(
    "-wp",
    "--wallet-rpc-port",
    help="Set the port where the Wallet is hosting the RPC interface. See the rpc_port under wallet in config.yaml",
    type=int,
    default=None,
)
@options.create_fingerprint()
@click.option("-id", "--id", help="The ID of the offer that you wish to examine", type=Bytes32ParamType())
@click.option("-p", "--filepath", help="The path to rewrite the offer file to (must be used in conjunction with --id)")
@click.option("-em", "--exclude-my-offers", help="Exclude your own offers from the output", is_flag=True)
@click.option("-et", "--exclude-taken-offers", help="Exclude offers that you've accepted from the output", is_flag=True)
@click.option(
    "-ic", "--include-completed", help="Include offers that have been confirmed/cancelled or failed", is_flag=True
)
@click.option("-s", "--summaries", help="Show the assets being offered and requested for each offer", is_flag=True)
@click.option("-r", "--reverse", help="Reverse the order of the output", is_flag=True)
def get_offers_cmd(
    wallet_rpc_port: Optional[int],
    fingerprint: int,
    id: Optional[bytes32],
    filepath: Optional[str],
    exclude_my_offers: bool,
    exclude_taken_offers: bool,
    include_completed: bool,
    summaries: bool,
    reverse: bool,
) -> None:
    from .wallet_funcs import get_offers

    asyncio.run(
        get_offers(
            wallet_rpc_port=wallet_rpc_port,
            fp=fingerprint,
            offer_id=id,
            filepath=filepath,
            exclude_my_offers=exclude_my_offers,
            exclude_taken_offers=exclude_taken_offers,
            include_completed=include_completed,
            summaries=summaries,
            reverse=reverse,
        )
    )


@wallet_cmd.command("take_offer", help="Examine or take an offer")
@click.argument("path_or_hex", type=str, nargs=1, required=True)
@click.option(
    "-wp",
    "--wallet-rpc-port",
    help="Set the port where the Wallet is hosting the RPC interface. See the rpc_port under wallet in config.yaml",
    type=int,
    default=None,
)
@options.create_fingerprint()
@click.option("-e", "--examine-only", help="Print the summary of the offer file but do not take it", is_flag=True)
@options.create_fee("The fee to use when pushing the completed offer, in XCH")
# TODO: Reuse is not used
@click.option(
    "--reuse",
    help="Reuse existing address for the offer.",
    is_flag=True,
    default=False,
)
@tx_out_cmd()
def take_offer_cmd(
    path_or_hex: str,
    wallet_rpc_port: Optional[int],
    fingerprint: int,
    examine_only: bool,
    fee: uint64,
    reuse: bool,
    push: bool,
    condition_valid_times: ConditionValidTimes,
) -> List[TransactionRecord]:
    from .wallet_funcs import take_offer

    return asyncio.run(
        take_offer(
            wallet_rpc_port,
            fingerprint,
            fee,
            path_or_hex,
            examine_only,
            push,
            condition_valid_times=condition_valid_times,
        )
    )


@wallet_cmd.command("cancel_offer", help="Cancel an existing offer")
@click.option(
    "-wp",
    "--wallet-rpc-port",
    help="Set the port where the Wallet is hosting the RPC interface. See the rpc_port under wallet in config.yaml",
    type=int,
    default=None,
)
@options.create_fingerprint()
@click.option("-id", "--id", help="The offer ID that you wish to cancel", required=True, type=Bytes32ParamType())
@click.option("--insecure", help="Don't make an on-chain transaction, simply mark the offer as cancelled", is_flag=True)
@options.create_fee("The fee to use when cancelling the offer securely, in XCH")
@tx_out_cmd()
def cancel_offer_cmd(
    wallet_rpc_port: Optional[int],
    fingerprint: int,
    id: bytes32,
    insecure: bool,
    fee: uint64,
    push: bool,
    condition_valid_times: ConditionValidTimes,
) -> List[TransactionRecord]:
    from .wallet_funcs import cancel_offer

    return asyncio.run(
        cancel_offer(
            wallet_rpc_port,
            fingerprint,
            fee,
            id,
            not insecure,
            push,
            condition_valid_times=condition_valid_times,
        )
    )


@wallet_cmd.command("check", short_help="Check wallet DB integrity", help=check_help_text)
@click.option("-v", "--verbose", help="Print more information", is_flag=True)
@click.option("--db-path", help="The path to a wallet DB. Default is to scan all active wallet DBs.")
@click.pass_context
# TODO: accept multiple dbs on commandline
# TODO: Convert to Path earlier
def check_wallet_cmd(ctx: click.Context, db_path: str, verbose: bool) -> None:
    """check, scan, diagnose, fsck Chia Wallet DBs"""

    from chia.cmds.check_wallet_db import scan

    asyncio.run(scan(ctx.obj["root_path"], db_path, verbose=verbose))


@wallet_cmd.group("did", help="DID related actions")
def did_cmd() -> None:
    pass


@did_cmd.command("create", help="Create DID wallet")
@click.option(
    "-wp",
    "--wallet-rpc-port",
    help="Set the port where the Wallet is hosting the RPC interface. See the rpc_port under wallet in config.yaml",
    type=int,
    default=None,
)
@options.create_fingerprint()
@click.option("-n", "--name", help="Set the DID wallet name", type=str)
@click.option(
    "-a",
    "--amount",
    help="Set the DID amount in mojos. Value must be an odd number.",
    type=int,
    default=1,
    show_default=True,
)
@options.create_fee()
@tx_out_cmd()
def did_create_wallet_cmd(
    wallet_rpc_port: Optional[int],
    fingerprint: int,
    name: Optional[str],
    amount: int,
    fee: uint64,
    push: bool,
    condition_valid_times: ConditionValidTimes,
) -> List[TransactionRecord]:
    from .wallet_funcs import create_did_wallet

    return asyncio.run(
        create_did_wallet(
            wallet_rpc_port,
            fingerprint,
            fee,
            name,
            amount,
            push,
            condition_valid_times=condition_valid_times,
        )
    )


@did_cmd.command("sign_message", help="Sign a message by a DID")
@click.option(
    "-wp",
    "--wallet-rpc-port",
    help="Set the port where the Wallet is hosting the RPC interface. See the rpc_port under wallet in config.yaml",
    type=int,
    default=None,
)
@options.create_fingerprint()
@click.option("-i", "--did_id", help="DID ID you want to use for signing", type=AddressParamType(), required=True)
@click.option("-m", "--hex_message", help="The hex message you want to sign", type=str, required=True)
def did_sign_message(wallet_rpc_port: Optional[int], fingerprint: int, did_id: CliAddress, hex_message: str) -> None:
    from .wallet_funcs import sign_message

    asyncio.run(
        sign_message(
            wallet_rpc_port=wallet_rpc_port,
            fp=fingerprint,
            addr_type=AddressType.DID,
            message=hex_message,
            did_id=did_id,
        )
    )


@did_cmd.command("set_name", help="Set DID wallet name")
@click.option(
    "-wp",
    "--wallet-rpc-port",
    help="Set the port where the Wallet is hosting the RPC interface. See the rpc_port under wallet in config.yaml",
    type=int,
    default=None,
)
@options.create_fingerprint()
@click.option("-i", "--id", help="Id of the wallet to use", type=int, required=True)
@click.option("-n", "--name", help="Set the DID wallet name", type=str, required=True)
def did_wallet_name_cmd(wallet_rpc_port: Optional[int], fingerprint: int, id: int, name: str) -> None:
    from .wallet_funcs import did_set_wallet_name

    asyncio.run(did_set_wallet_name(wallet_rpc_port, fingerprint, id, name))


@did_cmd.command("get_did", help="Get DID from wallet")
@click.option(
    "-wp",
    "--wallet-rpc-port",
    help="Set the port where the Wallet is hosting the RPC interface. See the rpc_port under wallet in config.yaml",
    type=int,
    default=None,
)
@options.create_fingerprint()
@click.option("-i", "--id", help="Id of the wallet to use", type=int, required=True)
def did_get_did_cmd(wallet_rpc_port: Optional[int], fingerprint: int, id: int) -> None:
    from .wallet_funcs import get_did

    asyncio.run(get_did(wallet_rpc_port, fingerprint, id))


@did_cmd.command("get_details", help="Get more details of any DID")
@click.option(
    "-wp",
    "--wallet-rpc-port",
    help="Set the port where the Wallet is hosting the RPC interface. See the rpc_port under wallet in config.yaml",
    type=int,
    default=None,
)
@options.create_fingerprint()
@click.option("-id", "--coin_id", help="Id of the DID or any coin ID of the DID", type=str, required=True)
@click.option("-l", "--latest", help="Return latest DID information", is_flag=True, default=True)
def did_get_details_cmd(wallet_rpc_port: Optional[int], fingerprint: int, coin_id: str, latest: bool) -> None:
    from .wallet_funcs import get_did_info

    asyncio.run(get_did_info(wallet_rpc_port, fingerprint, coin_id, latest))


@did_cmd.command("update_metadata", help="Update the metadata of a DID")
@click.option(
    "-wp",
    "--wallet-rpc-port",
    help="Set the port where the Wallet is hosting the RPC interface. See the rpc_port under wallet in config.yaml",
    type=int,
    default=None,
)
@options.create_fingerprint()
@click.option("-i", "--id", help="Id of the DID wallet to use", type=int, required=True)
@click.option("-d", "--metadata", help="The new whole metadata in json format", type=str, required=True)
@click.option(
    "--reuse",
    help="Reuse existing address for the change.",
    is_flag=True,
    default=False,
)
@tx_out_cmd()
def did_update_metadata_cmd(
    wallet_rpc_port: Optional[int],
    fingerprint: int,
    id: int,
    metadata: str,
    reuse: bool,
    push: bool,
    condition_valid_times: ConditionValidTimes,
) -> List[TransactionRecord]:
    from .wallet_funcs import update_did_metadata

    return asyncio.run(
        update_did_metadata(
            wallet_rpc_port,
            fingerprint,
            id,
            metadata,
            reuse,
            push=push,
            condition_valid_times=condition_valid_times,
        )
    )


@did_cmd.command("find_lost", help="Find the did you should own and recovery the DID wallet")
@click.option(
    "-wp",
    "--wallet-rpc-port",
    help="Set the port where the Wallet is hosting the RPC interface. See the rpc_port under wallet in config.yaml",
    type=int,
    default=None,
)
@options.create_fingerprint()
@click.option("-id", "--coin_id", help="Id of the DID or any coin ID of the DID", type=str, required=True)
@click.option("-m", "--metadata", help="The new whole metadata in json format", type=str, required=False)
@click.option(
    "-r",
    "--recovery_list_hash",
    help="Override the recovery list hash of the DID. Only set this if your last DID spend updated the recovery list",
    type=str,
    required=False,
)
@click.option(
    "-n",
    "--num_verification",
    help="Override the required verification number of the DID."
    " Only set this if your last DID spend updated the required verification number",
    type=int,
    required=False,
)
def did_find_lost_cmd(
    wallet_rpc_port: Optional[int],
    fingerprint: int,
    coin_id: str,
    metadata: Optional[str],
    recovery_list_hash: Optional[str],
    num_verification: Optional[int],
) -> None:
    from .wallet_funcs import find_lost_did

    asyncio.run(
        find_lost_did(
            wallet_rpc_port=wallet_rpc_port,
            fp=fingerprint,
            coin_id=coin_id,
            metadata=metadata,
            recovery_list_hash=recovery_list_hash,
            num_verification=num_verification,
        )
    )


@did_cmd.command("message_spend", help="Generate a DID spend bundle for announcements")
@click.option(
    "-wp",
    "--wallet-rpc-port",
    help="Set the port where the Wallet is hosting the RPC interface. See the rpc_port under wallet in config.yaml",
    type=int,
    default=None,
)
@options.create_fingerprint()
@click.option("-i", "--id", help="Id of the DID wallet to use", type=int, required=True)
@click.option(
    "-pa",
    "--puzzle_announcements",
    help="The list of puzzle announcement hex strings, split by comma (,)",
    type=str,
    required=False,
)
@click.option(
    "-ca",
    "--coin_announcements",
    help="The list of coin announcement hex strings, split by comma (,)",
    type=str,
    required=False,
)
@tx_out_cmd()
def did_message_spend_cmd(
    wallet_rpc_port: Optional[int],
    fingerprint: int,
    id: int,
    puzzle_announcements: Optional[str],
    coin_announcements: Optional[str],
    push: bool,
    condition_valid_times: ConditionValidTimes,
) -> List[TransactionRecord]:
    from .wallet_funcs import did_message_spend

    puzzle_list: List[str] = []
    coin_list: List[str] = []
    if puzzle_announcements is not None:
        try:
            puzzle_list = puzzle_announcements.split(",")
            # validate puzzle announcements is list of hex strings
            for announcement in puzzle_list:
                bytes.fromhex(announcement)
        except ValueError:
            print("Invalid puzzle announcement format, should be a list of hex strings.")
            return []
    if coin_announcements is not None:
        try:
            coin_list = coin_announcements.split(",")
            # validate that coin announcements is a list of hex strings
            for announcement in coin_list:
                bytes.fromhex(announcement)
        except ValueError:
            print("Invalid coin announcement format, should be a list of hex strings.")
            return []

    return asyncio.run(
        did_message_spend(
            wallet_rpc_port,
            fingerprint,
            id,
            puzzle_list,
            coin_list,
            push=push,
            condition_valid_times=condition_valid_times,
        )
    )


@did_cmd.command("transfer", help="Transfer a DID")
@click.option(
    "-wp",
    "--wallet-rpc-port",
    help="Set the port where the Wallet is hosting the RPC interface. See the rpc_port under wallet in config.yaml",
    type=int,
    default=None,
)
@options.create_fingerprint()
@click.option("-i", "--id", help="Id of the DID wallet to use", type=int, required=True)
# TODO: Change RPC to use puzzlehash instead of address
@click.option("-ta", "--target-address", help="Target recipient wallet address", type=AddressParamType(), required=True)
@click.option(
    "-rr", "--reset_recovery", help="If you want to reset the recovery DID settings.", is_flag=True, default=False
)
@options.create_fee()
@click.option(
    "--reuse",
    help="Reuse existing address for the change.",
    is_flag=True,
    default=False,
)
@tx_out_cmd()
def did_transfer_did(
    wallet_rpc_port: Optional[int],
    fingerprint: int,
    id: int,
    target_address: CliAddress,
    reset_recovery: bool,
    fee: uint64,
    reuse: bool,
    push: bool,
    condition_valid_times: ConditionValidTimes,
) -> List[TransactionRecord]:
    from .wallet_funcs import transfer_did

    return asyncio.run(
        transfer_did(
            wallet_rpc_port,
            fingerprint,
            id,
            fee,
            target_address,
            reset_recovery is False,
            True if reuse else None,
            push=push,
            condition_valid_times=condition_valid_times,
        )
    )


@wallet_cmd.group("nft", help="NFT related actions")
def nft_cmd() -> None:
    pass


@nft_cmd.command("create", help="Create an NFT wallet")
@click.option(
    "-wp",
    "--wallet-rpc-port",
    help="Set the port where the Wallet is hosting the RPC interface. See the rpc_port under wallet in config.yaml",
    type=int,
    default=None,
)
@options.create_fingerprint()
# TODO: Change RPC to use puzzlehash instead of address
@click.option("-di", "--did-id", help="DID Id to use", type=AddressParamType())
@click.option("-n", "--name", help="Set the NFT wallet name", type=str)
def nft_wallet_create_cmd(
    wallet_rpc_port: Optional[int], fingerprint: int, did_id: Optional[CliAddress], name: Optional[str]
) -> None:
    from .wallet_funcs import create_nft_wallet

    asyncio.run(create_nft_wallet(wallet_rpc_port, fingerprint, did_id, name))


@nft_cmd.command("sign_message", help="Sign a message by a NFT")
@click.option(
    "-wp",
    "--wallet-rpc-port",
    help="Set the port where the Wallet is hosting the RPC interface. See the rpc_port under wallet in config.yaml",
    type=int,
    default=None,
)
@options.create_fingerprint()
@click.option("-i", "--nft_id", help="NFT ID you want to use for signing", type=AddressParamType(), required=True)
@click.option("-m", "--hex_message", help="The hex message you want to sign", type=str, required=True)
def nft_sign_message(wallet_rpc_port: Optional[int], fingerprint: int, nft_id: CliAddress, hex_message: str) -> None:
    from .wallet_funcs import sign_message

    asyncio.run(
        sign_message(
            wallet_rpc_port=wallet_rpc_port,
            fp=fingerprint,
            addr_type=AddressType.NFT,
            message=hex_message,
            nft_id=nft_id,
        )
    )


@nft_cmd.command("mint", help="Mint an NFT")
@click.option(
    "-wp",
    "--wallet-rpc-port",
    help="Set the port where the Wallet is hosting the RPC interface. See the rpc_port under wallet in config.yaml",
    type=int,
    default=None,
)
@options.create_fingerprint()
@click.option("-i", "--id", help="Id of the NFT wallet to use", type=int, required=True)
@click.option("-ra", "--royalty-address", help="Royalty address", type=AddressParamType())
@click.option("-ta", "--target-address", help="Target address", type=AddressParamType())
@click.option("--no-did-ownership", help="Disable DID ownership support", is_flag=True, default=False)
@click.option("-nh", "--hash", help="NFT content hash", type=str, required=True)
@click.option("-u", "--uris", help="Comma separated list of URIs", type=str, required=True)
@click.option("-mh", "--metadata-hash", help="NFT metadata hash", type=str, default="")
@click.option("-mu", "--metadata-uris", help="Comma separated list of metadata URIs", type=str)
@click.option("-lh", "--license-hash", help="NFT license hash", type=str, default="")
@click.option("-lu", "--license-uris", help="Comma separated list of license URIs", type=str)
@click.option("-et", "--edition-total", help="NFT edition total", type=int, show_default=True, default=1)
@click.option("-en", "--edition-number", help="NFT edition number", show_default=True, default=1, type=int)
@options.create_fee()
@click.option(
    "-rp",
    "--royalty-percentage-fraction",
    help="NFT royalty percentage fraction in basis points. Example: 175 would represent 1.75%",
    type=int,
    default=0,
    show_default=True,
)
@click.option(
    "--reuse",
    help="Reuse existing address for the change.",
    is_flag=True,
    default=False,
)
@tx_out_cmd()
def nft_mint_cmd(
    wallet_rpc_port: Optional[int],
    fingerprint: int,
    id: int,
    royalty_address: Optional[CliAddress],
    target_address: Optional[CliAddress],
    no_did_ownership: bool,
    hash: str,
    uris: str,
    metadata_hash: Optional[str],
    metadata_uris: Optional[str],
    license_hash: Optional[str],
    license_uris: Optional[str],
    edition_total: Optional[int],
    edition_number: Optional[int],
    fee: uint64,
    royalty_percentage_fraction: int,
    reuse: bool,
    push: bool,
    condition_valid_times: ConditionValidTimes,
) -> List[TransactionRecord]:
    from .wallet_funcs import mint_nft

    if metadata_uris is None:
        metadata_uris_list = []
    else:
        metadata_uris_list = [mu.strip() for mu in metadata_uris.split(",")]

    if license_uris is None:
        license_uris_list = []
    else:
        license_uris_list = [lu.strip() for lu in license_uris.split(",")]

    return asyncio.run(
        mint_nft(
            wallet_rpc_port=wallet_rpc_port,
            fp=fingerprint,
            wallet_id=id,
            royalty_cli_address=royalty_address,
            target_cli_address=target_address,
            no_did_ownership=no_did_ownership,
            hash=hash,
            uris=[u.strip() for u in uris.split(",")],
            metadata_hash=metadata_hash,
            metadata_uris=metadata_uris_list,
            license_hash=license_hash,
            license_uris=license_uris_list,
            edition_total=edition_total,
            edition_number=edition_number,
            fee=fee,
            royalty_percentage=royalty_percentage_fraction,
            reuse_puzhash=True if reuse else None,
            push=push,
            condition_valid_times=condition_valid_times,
        )
    )


@nft_cmd.command("add_uri", help="Add an URI to an NFT")
@click.option(
    "-wp",
    "--wallet-rpc-port",
    help="Set the port where the Wallet is hosting the RPC interface. See the rpc_port under wallet in config.yaml",
    type=int,
    default=None,
)
@options.create_fingerprint()
@click.option("-i", "--id", help="Id of the NFT wallet to use", type=int, required=True)
# TODO: change rpc to take bytes instead of a hex string
@click.option("-ni", "--nft-coin-id", help="Id of the NFT coin to add the URI to", type=str, required=True)
@click.option("-u", "--uri", help="URI to add to the NFT", type=str)
@click.option("-mu", "--metadata-uri", help="Metadata URI to add to the NFT", type=str)
@click.option("-lu", "--license-uri", help="License URI to add to the NFT", type=str)
@options.create_fee()
@click.option(
    "--reuse",
    help="Reuse existing address for the change.",
    is_flag=True,
    default=False,
)
@tx_out_cmd()
def nft_add_uri_cmd(
    wallet_rpc_port: Optional[int],
    fingerprint: int,
    id: int,
    nft_coin_id: str,
    uri: str,
    metadata_uri: str,
    license_uri: str,
    fee: uint64,
    reuse: bool,
    push: bool,
    condition_valid_times: ConditionValidTimes,
) -> List[TransactionRecord]:
    from .wallet_funcs import add_uri_to_nft

    return asyncio.run(
        add_uri_to_nft(
            wallet_rpc_port=wallet_rpc_port,
            fp=fingerprint,
            wallet_id=id,
            fee=fee,
            nft_coin_id=nft_coin_id,
            uri=uri,
            metadata_uri=metadata_uri,
            license_uri=license_uri,
            reuse_puzhash=True if reuse else None,
            push=push,
            condition_valid_times=condition_valid_times,
        )
    )


@nft_cmd.command("transfer", help="Transfer an NFT")
@click.option(
    "-wp",
    "--wallet-rpc-port",
    help="Set the port where the Wallet is hosting the RPC interface. See the rpc_port under wallet in config.yaml",
    type=int,
    default=None,
)
@options.create_fingerprint()
@click.option("-i", "--id", help="Id of the NFT wallet to use", type=int, required=True)
@click.option("-ni", "--nft-coin-id", help="Id of the NFT coin to transfer", type=str, required=True)
# TODO: Change RPC to use puzzlehash instead of address
@click.option("-ta", "--target-address", help="Target recipient wallet address", type=AddressParamType(), required=True)
@options.create_fee()
@click.option(
    "--reuse",
    help="Reuse existing address for the change.",
    is_flag=True,
    default=False,
)
@tx_out_cmd()
def nft_transfer_cmd(
    wallet_rpc_port: Optional[int],
    fingerprint: int,
    id: int,
    nft_coin_id: str,
    target_address: CliAddress,
    fee: uint64,
    reuse: bool,
    push: bool,
    condition_valid_times: ConditionValidTimes,
) -> List[TransactionRecord]:
    from .wallet_funcs import transfer_nft

    return asyncio.run(
        transfer_nft(
            wallet_rpc_port=wallet_rpc_port,
            fp=fingerprint,
            wallet_id=id,
            fee=fee,
            nft_coin_id=nft_coin_id,
            target_cli_address=target_address,
            reuse_puzhash=True if reuse else None,
            push=push,
            condition_valid_times=condition_valid_times,
        )
    )


@nft_cmd.command("list", help="List the current NFTs")
@click.option(
    "-wp",
    "--wallet-rpc-port",
    help="Set the port where the Wallet is hosting the RPC interface. See the rpc_port under wallet in config.yaml",
    type=int,
    default=None,
)
@options.create_fingerprint()
@click.option("-i", "--id", help="Id of the NFT wallet to use", type=int, required=True)
@click.option("--num", help="Number of NFTs to return", type=int, default=50)
@click.option("--start-index", help="Which starting index to start listing NFTs from", type=int, default=0)
def nft_list_cmd(wallet_rpc_port: Optional[int], fingerprint: int, id: int, num: int, start_index: int) -> None:
    from .wallet_funcs import list_nfts

    asyncio.run(list_nfts(wallet_rpc_port, fingerprint, id, num, start_index))


@nft_cmd.command("set_did", help="Set a DID on an NFT")
@click.option(
    "-wp",
    "--wallet-rpc-port",
    help="Set the port where the Wallet is hosting the RPC interface. See the rpc_port under wallet in config.yaml",
    type=int,
    default=None,
)
@options.create_fingerprint()
@click.option("-i", "--id", help="Id of the NFT wallet to use", type=int, required=True)
# TODO: Change RPC to use bytes instead of hex string
@click.option("-di", "--did-id", help="DID Id to set on the NFT", type=str, required=True)
@click.option("-ni", "--nft-coin-id", help="Id of the NFT coin to set the DID on", type=str, required=True)
@options.create_fee()
@click.option(
    "--reuse",
    help="Reuse existing address for the change.",
    is_flag=True,
    default=False,
)
@tx_out_cmd()
def nft_set_did_cmd(
    wallet_rpc_port: Optional[int],
    fingerprint: int,
    id: int,
    did_id: str,
    nft_coin_id: str,
    fee: uint64,
    reuse: bool,
    push: bool,
    condition_valid_times: ConditionValidTimes,
) -> List[TransactionRecord]:
    from .wallet_funcs import set_nft_did

    return asyncio.run(
        set_nft_did(
            wallet_rpc_port=wallet_rpc_port,
            fp=fingerprint,
            wallet_id=id,
            fee=fee,
            nft_coin_id=nft_coin_id,
            did_id=did_id,
            reuse_puzhash=True if reuse else None,
            push=push,
            condition_valid_times=condition_valid_times,
        )
    )


@nft_cmd.command("get_info", help="Get NFT information")
@click.option(
    "-wp",
    "--wallet-rpc-port",
    help="Set the port where the Wallet is hosting the RPC interface. See the rpc_port under wallet in config.yaml",
    type=int,
    default=None,
)
@options.create_fingerprint()
# TODO: Change RPC to use bytes instead of hex string
@click.option("-ni", "--nft-coin-id", help="Id of the NFT coin to get information on", type=str, required=True)
def nft_get_info_cmd(
    wallet_rpc_port: Optional[int],
    fingerprint: int,
    nft_coin_id: str,
) -> None:
    from .wallet_funcs import get_nft_info

    asyncio.run(get_nft_info(wallet_rpc_port, fingerprint, nft_coin_id))


# Keep at bottom.
wallet_cmd.add_command(coins_cmd)


@wallet_cmd.group("notifications", help="Send/Manage notifications")
def notification_cmd() -> None:
    pass


@notification_cmd.command("send", help="Send a notification to the owner of an address")
@click.option(
    "-wp",
    "--wallet-rpc-port",
    help="Set the port where the Wallet is hosting the RPC interface. See the rpc_port under wallet in config.yaml",
    type=int,
    default=None,
)
@options.create_fingerprint()
@click.option(
    "-t", "--to-address", help="The address to send the notification to", type=AddressParamType(), required=True
)
@click.option(
    "-a",
    "--amount",
    help="The amount (in XCH) to send to get the notification past the recipient's spam filter",
    type=AmountParamType(),
    default=CliAmount(mojos=True, amount=uint64(10000000)),
    required=True,
    show_default=True,
)
@click.option("-n", "--message", help="The message of the notification", type=str)
@options.create_fee()
@tx_out_cmd()
def send_notification_cmd(
    wallet_rpc_port: Optional[int],
    fingerprint: int,
    to_address: CliAddress,
    amount: CliAmount,
    message: str,
    fee: uint64,
    push: bool,
    condition_valid_times: ConditionValidTimes,
) -> List[TransactionRecord]:
    from .wallet_funcs import send_notification

    message_bytes: bytes = bytes(message, "utf8")
    return asyncio.run(
        send_notification(
            wallet_rpc_port,
            fingerprint,
            fee,
            to_address,
            message_bytes,
            amount,
            push,
            condition_valid_times=condition_valid_times,
        )
    )


@notification_cmd.command("get", help="Get notification(s) that are in your wallet")
@click.option(
    "-wp",
    "--wallet-rpc-port",
    help="Set the port where the Wallet is hosting the RPC interface. See the rpc_port under wallet in config.yaml",
    type=int,
    default=None,
)
@options.create_fingerprint()
@click.option("-i", "--id", help="The specific notification ID to show", type=Bytes32ParamType(), multiple=True)
@click.option("-s", "--start", help="The number of notifications to skip", type=int, default=None)
@click.option("-e", "--end", help="The number of notifications to stop at", type=int, default=None)
def get_notifications_cmd(
    wallet_rpc_port: Optional[int],
    fingerprint: int,
    id: Sequence[bytes32],
    start: Optional[int],
    end: Optional[int],
) -> None:
    from .wallet_funcs import get_notifications

    asyncio.run(get_notifications(wallet_rpc_port, fingerprint, id, start, end))


@notification_cmd.command("delete", help="Delete notification(s) that are in your wallet")
@click.option(
    "-wp",
    "--wallet-rpc-port",
    help="Set the port where the Wallet is hosting the RPC interface. See the rpc_port under wallet in config.yaml",
    type=int,
    default=None,
)
@options.create_fingerprint()
@click.option("-i", "--id", help="A specific notification ID to delete", type=Bytes32ParamType(), multiple=True)
@click.option("--all", help="All notifications can be deleted (they will be recovered during resync)", is_flag=True)
def delete_notifications_cmd(
    wallet_rpc_port: Optional[int],
    fingerprint: int,
    id: Sequence[bytes32],
    all: bool,
) -> None:
    from .wallet_funcs import delete_notifications

    asyncio.run(delete_notifications(wallet_rpc_port, fingerprint, id, all))


@wallet_cmd.group("vcs", short_help="Verifiable Credential related actions")
def vcs_cmd() -> None:  # pragma: no cover
    pass


@vcs_cmd.command("mint", short_help="Mint a VC")
@click.option(
    "-wp",
    "--wallet-rpc-port",
    help="Set the port where the Wallet is hosting the RPC interface. See the rpc_port under wallet in config.yaml",
    type=int,
    default=None,
)
@options.create_fingerprint()
@click.option("-d", "--did", help="The DID of the VC's proof provider", type=AddressParamType(), required=True)
@click.option(
    "-t",
    "--target-address",
    help="The address to send the VC to once it's minted",
    type=AddressParamType(),
    required=False,
)
@options.create_fee("Blockchain fee for mint transaction, in XCH")
@tx_out_cmd()
def mint_vc_cmd(
    wallet_rpc_port: Optional[int],
    fingerprint: int,
    did: CliAddress,
    target_address: Optional[CliAddress],
    fee: uint64,
    push: bool,
    condition_valid_times: ConditionValidTimes,
) -> List[TransactionRecord]:
    from .wallet_funcs import mint_vc

    return asyncio.run(
        mint_vc(
            wallet_rpc_port,
            fingerprint,
            did,
            fee,
            target_address,
            push,
            condition_valid_times=condition_valid_times,
        )
    )


@vcs_cmd.command("get", short_help="Get a list of existing VCs")
@click.option(
    "-wp",
    "--wallet-rpc-port",
    help="Set the port where the Wallet is hosting the RPC interface. See the rpc_port under wallet in config.yaml",
    type=int,
    default=None,
)
@options.create_fingerprint()
@click.option(
    "-s", "--start", help="The index to start the list at", type=int, required=False, default=0, show_default=True
)
@click.option(
    "-c", "--count", help="How many results to return", type=int, required=False, default=50, show_default=True
)
def get_vcs_cmd(
    wallet_rpc_port: Optional[int],
    fingerprint: int,
    start: int,
    count: int,
) -> None:  # pragma: no cover
    from .wallet_funcs import get_vcs

    asyncio.run(get_vcs(wallet_rpc_port, fingerprint, start, count))


@vcs_cmd.command("update_proofs", short_help="Update a VC's proofs if you have the provider DID")
@click.option(
    "-wp",
    "--wallet-rpc-port",
    help="Set the port where the Wallet is hosting the RPC interface. See the rpc_port under wallet in config.yaml",
    type=int,
    default=None,
)
@options.create_fingerprint()
@click.option(
    "-l",
    "--vc-id",
    help="The launcher ID of the VC whose proofs should be updated",
    type=Bytes32ParamType(),
    required=True,
)
@click.option(
    "-t",
    "--new-puzhash",
    help="The address to send the VC after the proofs have been updated",
    type=Bytes32ParamType(),
    required=False,
)
@click.option("-p", "--new-proof-hash", help="The new proof hash to update the VC to", type=str, required=True)
@options.create_fee("Blockchain fee for update transaction, in XCH")
@click.option(
    "--reuse-puzhash/--generate-new-puzhash",
    help="Send the VC back to the same puzzle hash it came from (ignored if --new-puzhash is specified)",
    default=False,
    show_default=True,
)
@tx_out_cmd()
def spend_vc_cmd(
    wallet_rpc_port: Optional[int],
    fingerprint: int,
    vc_id: bytes32,
    new_puzhash: Optional[bytes32],
    new_proof_hash: str,
    fee: uint64,
    reuse_puzhash: bool,
    push: bool,
    condition_valid_times: ConditionValidTimes,
) -> List[TransactionRecord]:
    from .wallet_funcs import spend_vc

    return asyncio.run(
        spend_vc(
            wallet_rpc_port=wallet_rpc_port,
            fp=fingerprint,
            vc_id=vc_id,
            fee=fee,
            new_puzhash=new_puzhash,
            new_proof_hash=new_proof_hash,
            reuse_puzhash=reuse_puzhash,
            push=push,
            condition_valid_times=condition_valid_times,
        )
    )


@vcs_cmd.command("add_proof_reveal", short_help="Add a series of proofs that will combine to a single proof hash")
@click.option(
    "-wp",
    "--wallet-rpc-port",
    help="Set the port where the Wallet is hosting the RPC interface. See the rpc_port under wallet in config.yaml",
    type=int,
    default=None,
)
@options.create_fingerprint()
@click.option("-p", "--proof", help="A flag to add as a proof", type=str, multiple=True)
@click.option("-r", "--root-only", help="Do not add the proofs to the DB, just output the root", is_flag=True)
def add_proof_reveal_cmd(
    wallet_rpc_port: Optional[int],
    fingerprint: int,
    proof: Sequence[str],
    root_only: bool,
) -> None:  # pragma: no cover
    from .wallet_funcs import add_proof_reveal

    asyncio.run(add_proof_reveal(wallet_rpc_port, fingerprint, proof, root_only))


@vcs_cmd.command("get_proofs_for_root", short_help="Get the stored proof flags for a given proof hash")
@click.option(
    "-wp",
    "--wallet-rpc-port",
    help="Set the port where the Wallet is hosting the RPC interface. See the rpc_port under wallet in config.yaml",
    type=int,
    default=None,
)
@options.create_fingerprint()
@click.option("-r", "--proof-hash", help="The root to search for", type=str, required=True)
def get_proofs_for_root_cmd(
    wallet_rpc_port: Optional[int],
    fingerprint: int,
    proof_hash: str,
) -> None:  # pragma: no cover
    from .wallet_funcs import get_proofs_for_root

    asyncio.run(get_proofs_for_root(wallet_rpc_port, fingerprint, proof_hash))


@vcs_cmd.command("revoke", short_help="Revoke any VC if you have the proper DID and the VCs parent coin")
@click.option(
    "-wp",
    "--wallet-rpc-port",
    help="Set the port where the Wallet is hosting the RPC interface. See the rpc_port under wallet in config.yaml",
    type=int,
    default=None,
)
@options.create_fingerprint()
@click.option(
    "-p",
    "--parent-coin-id",
    help="The ID of the parent coin of the VC (optional if VC ID is used)",
    type=Bytes32ParamType(),
    required=False,
)
@click.option(
    "-l",
    "--vc-id",
    help="The launcher ID of the VC to revoke (must be tracked by wallet) (optional if Parent ID is used)",
    type=Bytes32ParamType(),
    required=False,
)
@options.create_fee("Blockchain fee for revocation transaction, in XCH")
@click.option(
    "--reuse-puzhash/--generate-new-puzhash",
    help="Send the VC back to the same puzzle hash it came from (ignored if --new-puzhash is specified)",
    default=False,
    show_default=True,
)
@tx_out_cmd()
def revoke_vc_cmd(
    wallet_rpc_port: Optional[int],
    fingerprint: int,
    parent_coin_id: Optional[bytes32],
    vc_id: Optional[bytes32],
    fee: uint64,
    reuse_puzhash: bool,
    push: bool,
    condition_valid_times: ConditionValidTimes,
) -> List[TransactionRecord]:
    from .wallet_funcs import revoke_vc

    return asyncio.run(
        revoke_vc(
            wallet_rpc_port,
            fingerprint,
            parent_coin_id,
            vc_id,
            fee,
            reuse_puzhash,
            push,
            condition_valid_times=condition_valid_times,
        )
    )


@vcs_cmd.command("approve_r_cats", help="Claim any R-CATs that are currently pending VC approval")
@click.option(
    "-wp",
    "--wallet-rpc-port",
    help="Set the port where the Wallet is hosting the RPC interface. See the rpc_port under wallet in config.yaml",
    type=int,
    default=None,
)
@options.create_fingerprint()
@click.option("-i", "--id", help="Id of the wallet with the pending approval balance", type=int, required=True)
@click.option(
    "-a",
    "--min-amount-to-claim",
    help="The minimum amount (in CAT units) to approve to move into the wallet",
    type=AmountParamType(),
    required=True,
)
@options.create_fee("Blockchain fee for approval transaction, in XCH")
@click.option(
    "-ma",
    "--min-coin-amount",
    type=AmountParamType(),
    default=cli_amount_none,
    help="The minimum coin amount (in CAT units) to select",
)
@click.option(
    "-l",
    "--max-coin-amount",
    type=AmountParamType(),
    default=cli_amount_none,
    help="The maximum coin amount (in CAT units) to select",
)
@click.option(
    "--reuse",
    help="Reuse existing address for the change.",
    is_flag=True,
    default=False,
)
@tx_out_cmd()
def approve_r_cats_cmd(
    wallet_rpc_port: Optional[int],
    fingerprint: int,
    id: int,
    min_amount_to_claim: CliAmount,
    fee: uint64,
    min_coin_amount: CliAmount,
    max_coin_amount: CliAmount,
    reuse: bool,
    push: bool,
    condition_valid_times: ConditionValidTimes,
) -> List[TransactionRecord]:
    from .wallet_funcs import approve_r_cats

    return asyncio.run(
        approve_r_cats(
            wallet_rpc_port,
            fingerprint,
            uint32(id),
            min_amount_to_claim,
            fee,
            min_coin_amount,
            max_coin_amount,
            reuse,
            push,
            condition_valid_times=condition_valid_times,
        )
    )
