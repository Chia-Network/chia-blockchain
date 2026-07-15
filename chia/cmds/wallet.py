from __future__ import annotations

import pathlib
from collections.abc import Sequence
from typing import cast

import click
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint32, uint64

from chia.cmds.check_wallet_db import help_text as check_help_text
from chia.cmds.cmd_classes import ChiaCliContext, argument, chia_command, get_chia_command_metadata, option
from chia.cmds.cmd_helpers import (
    NeedsWalletRPC,
    TransactionEndpoint,
    TransactionEndpointWithTimelocks,
    transaction_endpoint_runner,
)
from chia.cmds.coins import coins_cmd
from chia.cmds.param_types import (
    AddressParamType,
    AmountParamType,
    Bytes32ParamType,
    CliAddress,
    CliAmount,
    TransactionFeeParamType,
)
from chia.cmds.signer import PushTransactionsCMD, signer_cmd
from chia.cmds.units import units
from chia.cmds.wallet_funcs import delete_notifications, get_notifications, send_notification
from chia.wallet.conditions import ConditionValidTimes
from chia.wallet.transaction_record import TransactionRecord
from chia.wallet.transaction_sorting import SortKey
from chia.wallet.util.address_type import AddressType
from chia.wallet.util.wallet_types import WalletType


@click.group("wallet", help="Manage your wallet")
@click.pass_context
def wallet_cmd(ctx: click.Context) -> None:
    pass


wallet_cmd.add_command(signer_cmd)
wallet_cmd.add_command(get_chia_command_metadata(PushTransactionsCMD).command)


@chia_command(group=wallet_cmd, name="get_transaction", short_help="Get a transaction", help="Get a transaction")
class GetTransactionCMD:
    rpc_info: NeedsWalletRPC
    wallet_id: int = option(
        "-i", "--id", help="Id of the wallet to use", type=int, default=1, show_default=True, required=True
    )
    tx_id: str = option("-tx", "--tx_id", help="transaction id to search for", type=str, required=True)
    verbose: int = option("--verbose", "-v", count=True, type=int)

    async def run(self) -> None:
        from chia.cmds.wallet_funcs import get_transaction

        async with self.rpc_info.wallet_rpc() as wallet_info:
            await get_transaction(wallet_info=wallet_info, tx_id=self.tx_id, verbose=self.verbose)


@chia_command(group=wallet_cmd, name="get_transactions", short_help="Get all transactions", help="Get all transactions")
class GetTransactionsCMD:
    rpc_info: NeedsWalletRPC
    wallet_id: int = option(
        "-i", "--id", help="Id of the wallet to use", type=int, default=1, show_default=True, required=True
    )
    offset: int = option(
        "-o",
        "--offset",
        help="Skip transactions from the beginning of the list",
        type=int,
        default=0,
        show_default=True,
        required=True,
    )
    limit: int = option(
        "-l", "--limit", help="Max number of transactions to return", type=int, default=2**32 - 1, show_default=True
    )
    verbose: int = option("--verbose", "-v", count=True, type=int)
    paginate: bool | None = option(
        "--paginate/--no-paginate",
        default=None,
        help="Prompt for each page of data.  Defaults to true for interactive consoles, otherwise false.",
    )
    sort_key: SortKey = option(
        "--sort-by-relevance",
        flag_value=SortKey.RELEVANCE,
        type=SortKey,
        default=SortKey.RELEVANCE,
        help="Sort transactions by {confirmed, height, time}",
    )
    sort_by_height: bool = option("--sort-by-height", is_flag=True, default=False, help="Sort transactions by height")
    reverse: bool = option("--reverse", is_flag=True, default=False, help="Reverse the transaction ordering")
    clawback: bool = option("--clawback", is_flag=True, default=False, help="Only show clawback transactions")

    async def run(self) -> None:
        from chia.cmds.wallet_funcs import get_transactions

        async with self.rpc_info.wallet_rpc() as wallet_info:
            await get_transactions(
                wallet_info=wallet_info,
                wallet_id=self.wallet_id,
                verbose=self.verbose,
                paginate=self.paginate,
                offset=self.offset,
                limit=self.limit,
                sort_key=SortKey.CONFIRMED_AT_HEIGHT if self.sort_by_height else self.sort_key,
                reverse=self.reverse,
                clawback=self.clawback,
            )


@chia_command(
    group=wallet_cmd,
    name="send",
    short_help="Send chia or other assets to another wallet",
    help="Send chia or other assets to another wallet",
)
class SendCMD(TransactionEndpoint):
    wallet_id: int = option(
        "-i", "--id", help="Id of the wallet to use", type=int, default=1, show_default=True, required=True
    )
    amount: CliAmount = option(
        "-a", "--amount", help="How much chia to send, in XCH or CAT units", type=AmountParamType(), required=True
    )
    memo: str | None = option("-e", "--memo", help="Additional memo for the transaction", type=str, default=None)
    address: CliAddress = option(
        "-t", "--address", help="Address to send the XCH", type=AddressParamType(), required=True
    )
    override: bool = option(
        "-o", "--override", help="Submits transaction without checking for unusual values", is_flag=True, default=False
    )
    clawback_time: int = option(
        "--clawback_time",
        help="The seconds that the recipient needs to wait to claim the fund. "
        "A positive number will enable the Clawback features.",
        type=int,
        default=0,
    )

    @transaction_endpoint_runner
    async def run(self) -> list[TransactionRecord]:
        from chia.cmds.wallet_funcs import send

        async with self.rpc_info.wallet_rpc() as wallet_info:
            return await send(
                wallet_info=wallet_info,
                wallet_id=self.wallet_id,
                amount=self.amount,
                memo=self.memo,
                fee=self.fee,
                address=self.address,
                override=self.override,
                clawback_time_lock=self.clawback_time,
                push=self.push,
                condition_valid_times=self.load_condition_valid_times(),
                tx_config_loader=self.tx_config_loader,
            )


@chia_command(group=wallet_cmd, name="show", short_help="Show wallet information", help="Show wallet information")
class ShowCMD:
    rpc_info: NeedsWalletRPC
    wallet_type: str | None = option(
        "-w",
        "--wallet_type",
        help="Choose a specific wallet type to return",
        type=click.Choice([x.name.lower() for x in WalletType]),
        default=None,
    )

    async def run(self) -> None:
        from chia.cmds.wallet_funcs import print_balances

        async with self.rpc_info.wallet_rpc() as wallet_info:
            await print_balances(wallet_info, WalletType[self.wallet_type.upper()] if self.wallet_type else None)


@chia_command(
    group=wallet_cmd, name="get_address", short_help="Get a wallet receive address", help="Get a wallet receive address"
)
class GetAddressCMD:
    rpc_info: NeedsWalletRPC
    wallet_id: int = option(
        "-i", "--id", help="Id of the wallet to use", type=int, default=1, show_default=True, required=True
    )
    new_address: bool = option(
        "-n/-l",
        "--new-address/--latest-address",
        help="Create a new wallet receive address, or show the most recently created wallet receive address"
        " [default: show most recent address]",
        is_flag=True,
        default=False,
    )

    async def run(self) -> None:
        from chia.cmds.wallet_funcs import get_address

        async with self.rpc_info.wallet_rpc() as wallet_info:
            await get_address(wallet_info, self.wallet_id, self.new_address)


@chia_command(
    group=wallet_cmd,
    name="clawback",
    short_help="Claim or revert a Clawback transaction.",
    help="Claim or revert a Clawback transaction. "
    "The wallet will automatically detect if you are able to revert or claim.",
)
class ClawbackCMD(TransactionEndpoint):
    fee: uint64 = option(
        "-m",
        "--fee",
        help="A fee to add to the offer when it gets taken, in XCH",
        type=TransactionFeeParamType(),
        default="0",
        show_default=True,
        required=True,
    )
    wallet_id: int = option(
        "-i", "--id", help="Id of the wallet to use", type=int, default=1, show_default=True, required=True
    )
    tx_ids: str = option(
        "-ids",
        "--tx_ids",
        help="IDs of the Clawback transactions you want to revert or claim. Separate multiple IDs by comma (,).",
        type=str,
        default="",
        required=True,
    )
    force: bool = option(
        "--force", help="Force to push the spend bundle even it may be a double spend", is_flag=True, default=False
    )

    @transaction_endpoint_runner
    async def run(self) -> list[TransactionRecord]:
        from chia.cmds.wallet_funcs import spend_clawback

        async with self.rpc_info.wallet_rpc() as wallet_info:
            return await spend_clawback(
                wallet_info=wallet_info,
                fee=self.fee,
                tx_ids_str=self.tx_ids,
                force=self.force,
                push=self.push,
                condition_valid_times=self.load_condition_valid_times(),
                tx_config=self.tx_config_loader.load_tx_config(
                    units["chia"], wallet_info.config, wallet_info.fingerprint
                ),
            )


@chia_command(
    group=wallet_cmd,
    name="delete_unconfirmed_transactions",
    short_help="Deletes all unconfirmed transactions for this wallet ID",
    help="Deletes all unconfirmed transactions for this wallet ID",
)
class DeleteUnconfirmedTransactionsCMD:
    rpc_info: NeedsWalletRPC
    wallet_id: int = option(
        "-i", "--id", help="Id of the wallet to use", type=int, default=1, show_default=True, required=True
    )

    async def run(self) -> None:
        from chia.cmds.wallet_funcs import delete_unconfirmed_transactions

        async with self.rpc_info.wallet_rpc() as wallet_info:
            await delete_unconfirmed_transactions(wallet_info, self.wallet_id)


@chia_command(
    group=wallet_cmd,
    name="get_derivation_index",
    short_help="Get the last puzzle hash derivation path index",
    help="Get the last puzzle hash derivation path index",
)
class GetDerivationIndexCMD:
    rpc_info: NeedsWalletRPC

    async def run(self) -> None:
        from chia.cmds.wallet_funcs import get_derivation_index

        async with self.rpc_info.wallet_rpc() as wallet_info:
            await get_derivation_index(wallet_info)


@chia_command(
    group=wallet_cmd,
    name="sign_message",
    short_help="Sign a message by a derivation address",
    help="Sign a message by a derivation address",
)
class SignMessageCMD:
    rpc_info: NeedsWalletRPC
    address: CliAddress = option(
        "-a", "--address", help="The address you want to use for signing", type=AddressParamType(), required=True
    )
    hex_message: str = option("-m", "--hex_message", help="The hex message you want sign", type=str, required=True)

    async def run(self) -> None:
        from chia.cmds.wallet_funcs import sign_message

        async with self.rpc_info.wallet_rpc() as wallet_info:
            await sign_message(
                wallet_info=wallet_info, addr_type=AddressType.XCH, message=self.hex_message, address=self.address
            )


@chia_command(
    group=wallet_cmd,
    name="update_derivation_index",
    short_help="Generate additional derived puzzle hashes starting at the provided index",
    help="Generate additional derived puzzle hashes starting at the provided index",
)
class UpdateDerivationIndexCMD:
    rpc_info: NeedsWalletRPC
    index: int = option(
        "-i", "--index", help="Index to set. Must be greater than the current derivation index", type=int, required=True
    )

    async def run(self) -> None:
        from chia.cmds.wallet_funcs import update_derivation_index

        async with self.rpc_info.wallet_rpc() as wallet_info:
            await update_derivation_index(wallet_info, self.index)


@chia_command(
    group=wallet_cmd,
    name="add_token",
    short_help="Add/Rename a CAT to the wallet by its asset ID",
    help="Add/Rename a CAT to the wallet by its asset ID",
)
class AddTokenCMD:
    rpc_info: NeedsWalletRPC
    asset_id: bytes32 = option(
        "-id",
        "--asset-id",
        help="The Asset ID of the coin you wish to add/rename (the treehash of the TAIL program)",
        type=Bytes32ParamType(),
        required=True,
    )
    token_name: str | None = option(
        "-n",
        "--token-name",
        help="The name you wish to designate to the token",
        type=str,
        default=None,
    )

    async def run(self) -> None:
        from chia.cmds.wallet_funcs import add_token

        async with self.rpc_info.wallet_rpc() as wallet_info:
            # Preserve the legacy command's optional Click option. If omitted, None is
            # passed through to the RPC as it was before this command was ported.
            await add_token(wallet_info, self.asset_id, cast(str, self.token_name))


@chia_command(
    group=wallet_cmd,
    name="make_offer",
    short_help="Create an offer of XCH/CATs/NFTs for XCH/CATs/NFTs",
    help="Create an offer of XCH/CATs/NFTs for XCH/CATs/NFTs",
)
class MakeOfferCMD:
    rpc_info: NeedsWalletRPC
    offers: Sequence[str] = option(
        "-o",
        "--offer",
        help="A wallet id to offer and the amount to offer (formatted like wallet_id:amount)",
        required=True,
        multiple=True,
    )
    requests: Sequence[str] = option(
        "-r",
        "--request",
        help="A wallet id of an asset to receive and the amount you wish to receive (formatted like wallet_id:amount)",
        multiple=True,
    )
    filepath: pathlib.Path = option(
        "-p",
        "--filepath",
        help="The path to write the generated offer file to",
        required=True,
        type=click.Path(dir_okay=False, writable=True, path_type=pathlib.Path),
    )
    fee: uint64 = option(
        "-m",
        "--fee",
        help="A fee to add to the offer when it gets taken, in XCH",
        type=TransactionFeeParamType(),
        default="0",
        show_default=True,
        required=True,
    )
    reuse: bool = option("--reuse", help="Reuse existing address for the offer.", is_flag=True, default=False)
    override: bool = option(
        "--override", help="Creates offer without checking for unusual values", is_flag=True, default=False
    )
    valid_at: int | None = option(
        "--valid-at",
        help="UNIX timestamp at which the associated transactions become valid",
        type=int,
        required=False,
        default=None,
    )
    expires_at: int | None = option(
        "--expires-at",
        help="UNIX timestamp at which the associated transactions expire",
        type=int,
        required=False,
        default=None,
    )

    async def run(self) -> None:
        from chia.cmds.wallet_funcs import make_offer

        if len(self.requests) == 0 and not self.override:
            print("Cannot make an offer without requesting something without --override")
            return
        async with self.rpc_info.wallet_rpc() as wallet_info:
            await make_offer(
                wallet_info=wallet_info,
                fee=self.fee,
                offers=self.offers,
                requests=self.requests,
                filepath=self.filepath,
                reuse_puzhash=True if self.reuse else None,
                condition_valid_times=ConditionValidTimes(
                    min_time=uint64.construct_optional(self.valid_at),
                    max_time=uint64.construct_optional(self.expires_at),
                ),
            )


@chia_command(
    group=wallet_cmd,
    name="get_offers",
    short_help="Get the status of existing offers.",
    help="Get the status of existing offers. Displays only active/pending offers by default.",
)
class GetOffersCMD:
    rpc_info: NeedsWalletRPC
    offer_id: bytes32 | None = option(
        "-id", "--id", help="The ID of the offer that you wish to examine", type=Bytes32ParamType(), default=None
    )
    filepath: str | None = option(
        "-p",
        "--filepath",
        help="The path to rewrite the offer file to (must be used in conjunction with --id)",
        default=None,
    )
    exclude_my_offers: bool = option(
        "-em", "--exclude-my-offers", help="Exclude your own offers from the output", is_flag=True, default=False
    )
    exclude_taken_offers: bool = option(
        "-et",
        "--exclude-taken-offers",
        help="Exclude offers that you've accepted from the output",
        is_flag=True,
        default=False,
    )
    include_completed: bool = option(
        "-ic",
        "--include-completed",
        help="Include offers that have been confirmed/cancelled or failed",
        is_flag=True,
        default=False,
    )
    summaries: bool = option(
        "-s",
        "--summaries",
        help="Show the assets being offered and requested for each offer",
        is_flag=True,
        default=False,
    )
    sort_by_relevance: bool = option(
        "--sort-by-relevance/--sort-by-confirmed-height",
        help="Sort the offers one of two ways",
        is_flag=True,
        default=False,
    )
    reverse: bool = option("-r", "--reverse", help="Reverse the order of the output", is_flag=True, default=False)

    async def run(self) -> None:
        from chia.cmds.wallet_funcs import get_offers

        async with self.rpc_info.wallet_rpc() as wallet_info:
            await get_offers(
                wallet_info=wallet_info,
                offer_id=self.offer_id,
                filepath=self.filepath,
                exclude_my_offers=self.exclude_my_offers,
                exclude_taken_offers=self.exclude_taken_offers,
                include_completed=self.include_completed,
                summaries=self.summaries,
                reverse=self.reverse,
                sort_by_relevance=self.sort_by_relevance,
            )


@chia_command(
    group=wallet_cmd, name="take_offer", short_help="Examine or take an offer", help="Examine or take an offer"
)
class TakeOfferCMD(TransactionEndpoint):
    fee: uint64 = option(
        "-m",
        "--fee",
        help="The fee to use when pushing the completed offer, in XCH",
        type=TransactionFeeParamType(),
        default="0",
        show_default=True,
        required=True,
    )
    path_or_hex: str = argument("path_or_hex", type=str, nargs=1, required=True)
    examine_only: bool = option(
        "-e",
        "--examine-only",
        help="Print the summary of the offer file but do not take it",
        is_flag=True,
        default=False,
    )

    @transaction_endpoint_runner
    async def run(self) -> list[TransactionRecord]:
        from chia.cmds.wallet_funcs import take_offer

        async with self.rpc_info.wallet_rpc() as wallet_info:
            return await take_offer(
                wallet_info,
                self.fee,
                self.path_or_hex,
                self.examine_only,
                self.push,
                self.load_condition_valid_times(),
                self.tx_config_loader.load_tx_config(units["chia"], wallet_info.config, wallet_info.fingerprint),
            )


@chia_command(
    group=wallet_cmd, name="cancel_offer", short_help="Cancel an existing offer", help="Cancel an existing offer"
)
class CancelOfferCMD(TransactionEndpoint):
    fee: uint64 = option(
        "-m",
        "--fee",
        help="The fee to use when cancelling the offer securely, in XCH",
        type=TransactionFeeParamType(),
        default="0",
        show_default=True,
        required=True,
    )
    offer_id: bytes32 = option(
        "-id", "--id", help="The offer ID that you wish to cancel", required=True, type=Bytes32ParamType()
    )
    insecure: bool = option(
        "--insecure",
        help="Don't make an on-chain transaction, simply mark the offer as cancelled",
        is_flag=True,
        default=False,
    )

    @transaction_endpoint_runner
    async def run(self) -> list[TransactionRecord]:
        from chia.cmds.wallet_funcs import cancel_offer

        async with self.rpc_info.wallet_rpc() as wallet_info:
            return await cancel_offer(
                wallet_info,
                self.fee,
                self.offer_id,
                not self.insecure,
                self.push,
                self.load_condition_valid_times(),
                self.tx_config_loader.load_tx_config(units["chia"], wallet_info.config, wallet_info.fingerprint),
            )


@chia_command(group=wallet_cmd, name="check", short_help="Check wallet DB integrity", help=check_help_text)
class CheckWalletCMD:
    context: ChiaCliContext
    verbose: bool = option("-v", "--verbose", help="Print more information", is_flag=True, default=False)
    db_path: str | None = option(
        "--db-path", help="The path to a wallet DB. Default is to scan all active wallet DBs.", default=None
    )

    async def run(self) -> None:
        from chia.cmds.check_wallet_db import scan

        await scan(self.context.root_path, self.db_path, verbose=self.verbose)


@wallet_cmd.group("did", help="DID related actions")
def did_cmd() -> None:  # pragma: no cover
    pass


@chia_command(
    group=did_cmd,
    name="create",
    short_help="Create DID wallet",
    help="Create DID wallet",
)
class CreateDidWalletCMD(TransactionEndpointWithTimelocks):
    name: str | None = option("-n", "--name", help="Set the DID wallet name", type=str, default=None)
    amount: int = option(
        "-a",
        "--amount",
        help="Set the DID amount in mojos. Value must be an odd number.",
        type=int,
        default=1,
        show_default=True,
    )
    metadata: Sequence[str] = option(
        "--metadata",
        help="A key value pair of metadata to set on the created DID (format == key:value)",
        type=str,
        multiple=True,
        default=tuple(),
    )

    @transaction_endpoint_runner
    async def run(self) -> list[TransactionRecord]:
        from chia.cmds.wallet_funcs import create_did_wallet

        async with self.rpc_info.wallet_rpc() as wallet_info:
            return await create_did_wallet(
                wallet_info,
                self.fee,
                self.name,
                self.amount,
                self.push,
                self.metadata,
                condition_valid_times=self.load_condition_valid_times(),
                tx_config=self.tx_config_loader.load_tx_config(
                    units["chia"], wallet_info.config, wallet_info.fingerprint
                ),
            )


@chia_command(
    group=did_cmd,
    name="sign_message",
    short_help="Sign a message by a DID",
    help="Sign a message by a DID",
)
class DidSignMessageCMD:
    rpc_info: NeedsWalletRPC
    did_id: CliAddress = option(
        "-i", "--did_id", help="DID ID you want to use for signing", type=AddressParamType(), required=True
    )
    hex_message: str = option("-m", "--hex_message", help="The hex message you want to sign", type=str, required=True)

    async def run(self) -> None:
        from chia.cmds.wallet_funcs import sign_message

        async with self.rpc_info.wallet_rpc() as wallet_info:
            await sign_message(
                wallet_info=wallet_info,
                addr_type=AddressType.DID,
                message=self.hex_message,
                did_id=self.did_id,
            )


@chia_command(
    group=did_cmd,
    name="set_name",
    short_help="Set DID wallet name",
    help="Set DID wallet name",
)
class DidSetWalletNameCMD:
    rpc_info: NeedsWalletRPC
    wallet_id: int = option("-i", "--id", help="Id of the wallet to use", type=int, required=True)
    name: str = option("-n", "--name", help="Set the DID wallet name", type=str, required=True)

    async def run(self) -> None:
        from chia.cmds.wallet_funcs import did_set_wallet_name

        async with self.rpc_info.wallet_rpc() as wallet_info:
            await did_set_wallet_name(wallet_info, self.wallet_id, self.name)


@chia_command(
    group=did_cmd,
    name="get_did",
    short_help="Get DID from wallet",
    help="Get DID from wallet",
)
class DidGetDidCMD:
    rpc_info: NeedsWalletRPC
    wallet_id: int = option("-i", "--id", help="Id of the wallet to use", type=int, required=True)

    async def run(self) -> None:
        from chia.cmds.wallet_funcs import get_did

        async with self.rpc_info.wallet_rpc() as wallet_info:
            await get_did(wallet_info, self.wallet_id)


@chia_command(
    group=did_cmd,
    name="get_details",
    short_help="Get more details of any DID",
    help="Get more details of any DID",
)
class DidGetDetailsCMD:
    rpc_info: NeedsWalletRPC
    coin_id: str = option("-id", "--coin_id", help="Id of the DID or any coin ID of the DID", type=str, required=True)
    latest: bool = option("-l", "--latest", help="Return latest DID information", is_flag=True, default=True)

    async def run(self) -> None:
        from chia.cmds.wallet_funcs import get_did_info

        async with self.rpc_info.wallet_rpc() as wallet_info:
            await get_did_info(wallet_info, self.coin_id, self.latest)


@chia_command(
    group=did_cmd,
    name="update_metadata",
    short_help="Update the metadata of a DID",
    help="Update the metadata of a DID",
)
class DidUpdateMetadataCMD(TransactionEndpointWithTimelocks):
    wallet_id: int = option("-i", "--id", help="Id of the DID wallet to use", type=int, required=True)
    metadata: str = option("-d", "--metadata", help="The new whole metadata in json format", type=str, required=True)

    @transaction_endpoint_runner
    async def run(self) -> list[TransactionRecord]:
        from chia.cmds.wallet_funcs import update_did_metadata

        async with self.rpc_info.wallet_rpc() as wallet_info:
            return await update_did_metadata(
                wallet_info,
                self.wallet_id,
                self.metadata,
                self.fee,
                self.push,
                condition_valid_times=self.load_condition_valid_times(),
                tx_config=self.tx_config_loader.load_tx_config(
                    units["chia"], wallet_info.config, wallet_info.fingerprint
                ),
            )


@chia_command(
    group=did_cmd,
    name="find_lost",
    short_help="Find the did you should own and recovery the DID wallet",
    help="Find the did you should own and recovery the DID wallet",
)
class DidFindLostCMD:
    rpc_info: NeedsWalletRPC
    coin_id: str = option("-id", "--coin_id", help="Id of the DID or any coin ID of the DID", type=str, required=True)
    metadata: str | None = option(
        "-m", "--metadata", help="The new whole metadata in json format", type=str, required=False
    )
    recovery_list_hash: str | None = option(
        "-r",
        "--recovery_list_hash",
        help="Override the recovery list hash of the DID. Only set this "
        "if your last DID spend updated the recovery list",
        type=str,
        required=False,
    )
    num_verification: int | None = option(
        "-n",
        "--num_verification",
        help="Override the required verification number of the DID."
        " Only set this if your last DID spend updated the required verification number",
        type=int,
        required=False,
    )

    async def run(self) -> None:
        from chia.cmds.wallet_funcs import find_lost_did

        async with self.rpc_info.wallet_rpc() as wallet_info:
            await find_lost_did(
                wallet_info,
                self.coin_id,
                self.metadata,
                self.recovery_list_hash,
                self.num_verification,
            )


@chia_command(
    group=did_cmd,
    name="message_spend",
    short_help="Generate a DID spend bundle for announcements",
    help="Generate a DID spend bundle for announcements",
)
class DidMessageSpendCMD(TransactionEndpointWithTimelocks):
    wallet_id: int = option("-i", "--id", help="Id of the DID wallet to use", type=int, required=True)
    puzzle_announcements: str | None = option(
        "-pa",
        "--puzzle_announcements",
        help="The list of puzzle announcement hex strings, split by comma (,)",
        type=str,
        required=False,
    )
    coin_announcements: str | None = option(
        "-ca",
        "--coin_announcements",
        help="The list of coin announcement hex strings, split by comma (,)",
        type=str,
        required=False,
    )

    @transaction_endpoint_runner
    async def run(self) -> list[TransactionRecord]:
        from chia.cmds.wallet_funcs import did_message_spend

        puzzle_list: list[str] = []
        coin_list: list[str] = []
        if self.puzzle_announcements is not None:
            try:
                puzzle_list = self.puzzle_announcements.split(",")
                for announcement in puzzle_list:
                    bytes.fromhex(announcement)
            except ValueError:
                print("Invalid puzzle announcement format, should be a list of hex strings.")
                return []
        if self.coin_announcements is not None:
            try:
                coin_list = self.coin_announcements.split(",")
                for announcement in coin_list:
                    bytes.fromhex(announcement)
            except ValueError:
                print("Invalid coin announcement format, should be a list of hex strings.")
                return []

        async with self.rpc_info.wallet_rpc() as wallet_info:
            return await did_message_spend(
                wallet_info,
                self.wallet_id,
                puzzle_list,
                coin_list,
                self.fee,
                self.push,
                condition_valid_times=self.load_condition_valid_times(),
                tx_config=self.tx_config_loader.load_tx_config(
                    units["chia"], wallet_info.config, wallet_info.fingerprint
                ),
            )


@chia_command(
    group=did_cmd,
    name="transfer",
    short_help="Transfer a DID",
    help="Transfer a DID",
)
class DidTransferDidCMD(TransactionEndpointWithTimelocks):
    wallet_id: int = option("-i", "--id", help="Id of the DID wallet to use", type=int, required=True)
    # TODO: Change RPC to use puzzlehash instead of address
    target_address: CliAddress = option(
        "-ta", "--target-address", help="Target recipient wallet address", type=AddressParamType(), required=True
    )
    reset_recovery: bool = option(
        "-rr", "--reset_recovery", help="If you want to reset the recovery DID settings.", is_flag=True, default=False
    )

    @transaction_endpoint_runner
    async def run(self) -> list[TransactionRecord]:
        from chia.cmds.wallet_funcs import transfer_did

        async with self.rpc_info.wallet_rpc() as wallet_info:
            return await transfer_did(
                wallet_info,
                self.wallet_id,
                self.fee,
                self.target_address,
                not self.reset_recovery,
                self.push,
                condition_valid_times=self.load_condition_valid_times(),
                tx_config=self.tx_config_loader.load_tx_config(
                    units["chia"], wallet_info.config, wallet_info.fingerprint
                ),
            )


@wallet_cmd.group("nft", help="NFT related actions")
def nft_cmd() -> None:  # pragma: no cover
    pass


@chia_command(
    group=nft_cmd,
    name="create",
    short_help="Create an NFT wallet",
    help="Create an NFT wallet",
)
class CreateNftWalletCMD:
    rpc_info: NeedsWalletRPC
    # TODO: Change RPC to use puzzlehash instead of address
    did_id: CliAddress | None = option("-di", "--did-id", help="DID Id to use", type=AddressParamType(), default=None)
    name: str | None = option("-n", "--name", help="Set the NFT wallet name", type=str, default=None)

    async def run(self) -> None:
        from chia.cmds.wallet_funcs import create_nft_wallet

        async with self.rpc_info.wallet_rpc() as wallet_info:
            await create_nft_wallet(wallet_info, self.did_id, self.name)


@chia_command(
    group=nft_cmd,
    name="sign_message",
    short_help="Sign a message by a NFT",
    help="Sign a message by a NFT",
)
class NftSignMessageCMD:
    rpc_info: NeedsWalletRPC
    nft_id: CliAddress = option(
        "-i", "--nft_id", help="NFT ID you want to use for signing", type=AddressParamType(), required=True
    )
    hex_message: str = option("-m", "--hex_message", help="The hex message you want to sign", type=str, required=True)

    async def run(self) -> None:
        from chia.cmds.wallet_funcs import sign_message

        async with self.rpc_info.wallet_rpc() as wallet_info:
            await sign_message(
                wallet_info=wallet_info,
                addr_type=AddressType.NFT,
                message=self.hex_message,
                nft_id=self.nft_id,
            )


@chia_command(
    group=nft_cmd,
    name="mint",
    short_help="Mint an NFT",
    help="Mint an NFT",
)
class MintNftCMD(TransactionEndpointWithTimelocks):
    wallet_id: int = option("-i", "--id", help="Id of the NFT wallet to use", type=int, required=True)
    royalty_address: CliAddress | None = option(
        "-ra", "--royalty-address", help="Royalty address", type=AddressParamType(), default=None
    )
    target_address: CliAddress | None = option(
        "-ta", "--target-address", help="Target address", type=AddressParamType(), default=None
    )
    no_did_ownership: bool = option(
        "--no-did-ownership", help="Disable DID ownership support", is_flag=True, default=False
    )
    hash: str = option("-nh", "--hash", help="NFT content hash", type=str, required=True)
    uris: str = option("-u", "--uris", help="Comma separated list of URIs", type=str, required=True)
    metadata_hash: str | None = option("-mh", "--metadata-hash", help="NFT metadata hash", type=str, default=None)
    metadata_uris: str | None = option(
        "-mu", "--metadata-uris", help="Comma separated list of metadata URIs", type=str, default=None
    )
    license_hash: str | None = option("-lh", "--license-hash", help="NFT license hash", type=str, default=None)
    license_uris: str | None = option(
        "-lu", "--license-uris", help="Comma separated list of license URIs", type=str, default=None
    )
    edition_total: int = option(
        "-et", "--edition-total", help="NFT edition total", type=int, show_default=True, default=1
    )
    edition_number: int = option(
        "-en", "--edition-number", help="NFT edition number", show_default=True, default=1, type=int
    )
    royalty_percentage_fraction: int = option(
        "-rp",
        "--royalty-percentage-fraction",
        help="NFT royalty percentage fraction in basis points. Example: 175 would represent 1.75%",
        type=int,
        default=0,
        show_default=True,
    )

    @transaction_endpoint_runner
    async def run(self) -> list[TransactionRecord]:
        from chia.cmds.wallet_funcs import mint_nft

        metadata_uris_list = [] if self.metadata_uris is None else [mu.strip() for mu in self.metadata_uris.split(",")]
        license_uris_list = [] if self.license_uris is None else [lu.strip() for lu in self.license_uris.split(",")]

        async with self.rpc_info.wallet_rpc() as wallet_info:
            return await mint_nft(
                wallet_info=wallet_info,
                wallet_id=self.wallet_id,
                royalty_cli_address=self.royalty_address,
                target_cli_address=self.target_address,
                no_did_ownership=self.no_did_ownership,
                hash=self.hash,
                uris=[u.strip() for u in self.uris.split(",")],
                metadata_hash=self.metadata_hash,
                metadata_uris=metadata_uris_list,
                license_hash=self.license_hash,
                license_uris=license_uris_list,
                edition_total=self.edition_total,
                edition_number=self.edition_number,
                fee=self.fee,
                royalty_percentage=self.royalty_percentage_fraction,
                push=self.push,
                condition_valid_times=self.load_condition_valid_times(),
                tx_config=self.tx_config_loader.load_tx_config(
                    units["chia"], wallet_info.config, wallet_info.fingerprint
                ),
            )


@chia_command(
    group=nft_cmd,
    name="add_uri",
    short_help="Add an URI to an NFT",
    help="Add an URI to an NFT",
)
class AddUriToNftCMD(TransactionEndpointWithTimelocks):
    wallet_id: int = option("-i", "--id", help="Id of the NFT wallet to use", type=int, required=True)
    # TODO: change rpc to take bytes instead of a hex string
    nft_coin_id: str = option(
        "-ni", "--nft-coin-id", help="Id of the NFT coin to add the URI to", type=str, required=True
    )
    uri: str | None = option("-u", "--uri", help="URI to add to the NFT", type=str, default=None)
    metadata_uri: str | None = option(
        "-mu", "--metadata-uri", help="Metadata URI to add to the NFT", type=str, default=None
    )
    license_uri: str | None = option(
        "-lu", "--license-uri", help="License URI to add to the NFT", type=str, default=None
    )

    @transaction_endpoint_runner
    async def run(self) -> list[TransactionRecord]:
        from chia.cmds.wallet_funcs import add_uri_to_nft

        async with self.rpc_info.wallet_rpc() as wallet_info:
            return await add_uri_to_nft(
                wallet_info=wallet_info,
                wallet_id=self.wallet_id,
                fee=self.fee,
                nft_coin_id=self.nft_coin_id,
                uri=self.uri,
                metadata_uri=self.metadata_uri,
                license_uri=self.license_uri,
                push=self.push,
                condition_valid_times=self.load_condition_valid_times(),
                tx_config=self.tx_config_loader.load_tx_config(
                    units["chia"], wallet_info.config, wallet_info.fingerprint
                ),
            )


@chia_command(
    group=nft_cmd,
    name="transfer",
    short_help="Transfer an NFT",
    help="Transfer an NFT",
)
class TransferNftCMD(TransactionEndpointWithTimelocks):
    wallet_id: int = option("-i", "--id", help="Id of the NFT wallet to use", type=int, required=True)
    nft_coin_id: str = option("-ni", "--nft-coin-id", help="Id of the NFT coin to transfer", type=str, required=True)
    # TODO: Change RPC to use puzzlehash instead of address
    target_address: CliAddress = option(
        "-ta", "--target-address", help="Target recipient wallet address", type=AddressParamType(), required=True
    )

    @transaction_endpoint_runner
    async def run(self) -> list[TransactionRecord]:
        from chia.cmds.wallet_funcs import transfer_nft

        async with self.rpc_info.wallet_rpc() as wallet_info:
            return await transfer_nft(
                wallet_info=wallet_info,
                wallet_id=self.wallet_id,
                fee=self.fee,
                nft_coin_id=self.nft_coin_id,
                target_cli_address=self.target_address,
                push=self.push,
                condition_valid_times=self.load_condition_valid_times(),
                tx_config=self.tx_config_loader.load_tx_config(
                    units["chia"], wallet_info.config, wallet_info.fingerprint
                ),
            )


@chia_command(
    group=nft_cmd,
    name="list",
    short_help="List the current NFTs",
    help="List the current NFTs",
)
class ListNftsCMD:
    rpc_info: NeedsWalletRPC
    wallet_id: int = option("-i", "--id", help="Id of the NFT wallet to use", type=int, required=True)
    num: int = option("--num", help="Number of NFTs to return", type=int, default=50)
    start_index: int = option(
        "--start-index", help="Which starting index to start listing NFTs from", type=int, default=0
    )

    async def run(self) -> None:
        from chia.cmds.wallet_funcs import list_nfts

        async with self.rpc_info.wallet_rpc() as wallet_info:
            await list_nfts(wallet_info, self.wallet_id, self.num, self.start_index)


@chia_command(
    group=nft_cmd,
    name="set_did",
    short_help="Set a DID on an NFT",
    help="Set a DID on an NFT",
)
class SetNftDidCMD(TransactionEndpointWithTimelocks):
    wallet_id: int = option("-i", "--id", help="Id of the NFT wallet to use", type=int, required=True)
    # TODO: Change RPC to use bytes instead of hex string
    did_id: str = option("-di", "--did-id", help="DID Id to set on the NFT", type=str, required=True)
    nft_coin_id: str = option(
        "-ni", "--nft-coin-id", help="Id of the NFT coin to set the DID on", type=str, required=True
    )

    @transaction_endpoint_runner
    async def run(self) -> list[TransactionRecord]:
        from chia.cmds.wallet_funcs import set_nft_did

        async with self.rpc_info.wallet_rpc() as wallet_info:
            return await set_nft_did(
                wallet_info=wallet_info,
                wallet_id=self.wallet_id,
                fee=self.fee,
                nft_coin_id=self.nft_coin_id,
                did_id=self.did_id,
                push=self.push,
                condition_valid_times=self.load_condition_valid_times(),
                tx_config=self.tx_config_loader.load_tx_config(
                    units["chia"], wallet_info.config, wallet_info.fingerprint
                ),
            )


@chia_command(
    group=nft_cmd,
    name="get_info",
    short_help="Get NFT information",
    help="Get NFT information",
)
class GetNftInfoCMD:
    rpc_info: NeedsWalletRPC
    # TODO: Change RPC to use bytes instead of hex string
    nft_coin_id: str = option(
        "-ni", "--nft-coin-id", help="Id of the NFT coin to get information on", type=str, required=True
    )

    async def run(self) -> None:
        from chia.cmds.wallet_funcs import get_nft_info

        async with self.rpc_info.wallet_rpc() as wallet_info:
            await get_nft_info(wallet_info, self.nft_coin_id)


# Keep at bottom.
wallet_cmd.add_command(coins_cmd)


@click.group("notifications", help="Send/Manage notifications")
@click.pass_context
def notification_cmd(ctx: click.Context) -> None:
    pass


@chia_command(
    group=notification_cmd,
    name="send",
    short_help="Send a notification to the owner of an address",
    help="Send a notification to the owner of an address",
)
class SendNotificationCMD(TransactionEndpoint):
    to_address: CliAddress = option(
        "-t",
        "--to-address",
        help="The address to send the notification to",
        type=AddressParamType(),
        required=True,
    )
    amount: CliAmount = option(
        "-a",
        "--amount",
        help="The amount (in XCH) to send to get the notification past the recipient's spam filter",
        type=AmountParamType(),
        default=CliAmount(mojos=True, amount=uint64(10000000)),
        required=True,
        show_default=True,
    )
    message: str = option(
        "-n",
        "--message",
        help="The message of the notification",
        type=str,
        required=True,
    )

    @transaction_endpoint_runner
    async def run(self) -> list[TransactionRecord]:

        message_bytes: bytes = bytes(self.message, "utf8")
        async with self.rpc_info.wallet_rpc() as wallet_info:
            return await send_notification(
                wallet_info=wallet_info,
                fee=self.fee,
                address=self.to_address,
                message=message_bytes,
                cli_amount=self.amount,
                push=self.push,
                condition_valid_times=self.load_condition_valid_times(),
                tx_config=self.tx_config_loader.load_tx_config(
                    units["chia"], wallet_info.config, wallet_info.fingerprint
                ),
            )


@chia_command(
    group=notification_cmd,
    name="get",
    short_help="Get notification(s) that are in your wallet",
    help="Get notification(s) that are in your wallet",
)
class GetNotificationsCMD:
    rpc_info: NeedsWalletRPC
    ids: Sequence[bytes32] = option(
        "-i",
        "--id",
        help="The specific notification ID to show",
        type=Bytes32ParamType(),
        multiple=True,
        required=False,
    )
    start: int | None = option(
        "-s",
        "--start",
        help="The number of notifications to skip",
        type=int,
        default=None,
    )
    end: int | None = option(
        "-e",
        "--end",
        help="The number of notifications to stop at",
        type=int,
        default=None,
    )

    async def run(self) -> None:
        async with self.rpc_info.wallet_rpc() as wallet_info:
            await get_notifications(
                wallet_info,
                self.ids,
                self.start,
                self.end,
            )


@chia_command(
    group=notification_cmd,
    name="delete",
    short_help="Delete notification(s) that are in your wallet",
    help="Delete notification(s) that are in your wallet",
)
class DeleteNotificationsCMD:
    rpc_info: NeedsWalletRPC
    ids: Sequence[bytes32] = option(
        "-i",
        "--id",
        help="A specific notification ID to delete",
        type=Bytes32ParamType(),
        multiple=True,
        required=False,
    )
    delete_all: bool = option(
        "--all",
        help="All notifications can be deleted (they will be recovered during resync)",
        is_flag=True,
        default=False,
    )

    async def run(self) -> None:
        async with self.rpc_info.wallet_rpc() as wallet_info:
            await delete_notifications(
                wallet_info,
                self.ids,
                self.delete_all,
            )


wallet_cmd.add_command(notification_cmd)


@wallet_cmd.group("vcs", short_help="Verifiable Credential related actions")
def vcs_cmd() -> None:  # pragma: no cover
    pass


@chia_command(
    group=vcs_cmd,
    name="mint",
    short_help="Mint a VC",
    help="Mint a VC",
)
class MintVCCMD(TransactionEndpointWithTimelocks):
    did: CliAddress = option(
        "-d", "--did", help="The DID of the VC's proof provider", type=AddressParamType(), required=True
    )
    target_address: CliAddress | None = option(
        "-t",
        "--target-address",
        help="The address to send the VC to once it's minted",
        type=AddressParamType(),
        required=False,
    )

    @transaction_endpoint_runner
    async def run(self) -> list[TransactionRecord]:
        from chia.cmds.wallet_funcs import mint_vc

        async with self.rpc_info.wallet_rpc() as wallet_info:
            return await mint_vc(
                wallet_info,
                self.did,
                self.fee,
                self.target_address,
                self.push,
                condition_valid_times=self.load_condition_valid_times(),
            )


@chia_command(
    group=vcs_cmd,
    name="get",
    short_help="Get a list of existing VCs",
    help="Get a list of existing VCs",
)
class GetVcsCMD:
    rpc_info: NeedsWalletRPC
    start: int = option(
        "-s", "--start", help="The index to start the list at", type=int, required=False, default=0, show_default=True
    )
    count: int = option(
        "-c", "--count", help="How many results to return", type=int, required=False, default=50, show_default=True
    )

    async def run(self) -> None:  # pragma: no cover
        from chia.cmds.wallet_funcs import get_vcs

        await get_vcs(
            self.rpc_info.context.root_path,
            self.rpc_info.wallet_rpc_port,
            self.rpc_info.fingerprint,
            self.start,
            self.count,
        )


@chia_command(
    group=vcs_cmd,
    name="update_proofs",
    short_help="Update a VC's proofs if you have the provider DID",
    help="Update a VC's proofs if you have the provider DID",
)
class UpdateProofsVCCMD(TransactionEndpointWithTimelocks):
    vc_id: bytes32 = option(
        "--vc-id",
        help="The launcher ID of the VC whose proofs should be updated",
        type=Bytes32ParamType(),
        required=True,
    )
    new_puzhash: bytes32 | None = option(
        "-t",
        "--new-puzhash",
        help="The address to send the VC after the proofs have been updated",
        type=Bytes32ParamType(),
        required=False,
    )
    new_proof_hash: str | None = option(
        "-p", "--new-proof-hash", help="The new proof hash to update the VC to", type=str, required=False, default=None
    )

    @transaction_endpoint_runner
    async def run(self) -> list[TransactionRecord]:
        from chia.cmds.wallet_funcs import spend_vc

        reuse_puzhash = self.tx_config_loader.reuse if self.tx_config_loader.reuse is not None else False
        async with self.rpc_info.wallet_rpc() as wallet_info:
            return await spend_vc(
                wallet_info=wallet_info,
                vc_id=self.vc_id,
                fee=self.fee,
                new_puzhash=self.new_puzhash,
                new_proof_hash=self.new_proof_hash,
                reuse_puzhash=reuse_puzhash,
                push=self.push,
                condition_valid_times=self.load_condition_valid_times(),
            )


@chia_command(
    group=vcs_cmd,
    name="add_proof_reveal",
    short_help="Add a series of proofs that will combine to a single proof hash",
    help="Add a series of proofs that will combine to a single proof hash",
)
class AddProofRevealVCCMD:
    rpc_info: NeedsWalletRPC
    proof: Sequence[str] = option("-p", "--proof", help="A flag to add as a proof", type=str, multiple=True)
    root_only: bool = option(
        "-r", "--root-only", help="Do not add the proofs to the DB, just output the root", is_flag=True
    )

    async def run(self) -> None:  # pragma: no cover
        from chia.cmds.wallet_funcs import add_proof_reveal

        async with self.rpc_info.wallet_rpc() as wallet_info:
            await add_proof_reveal(
                wallet_info,
                self.proof,
                self.root_only,
            )


@chia_command(
    group=vcs_cmd,
    name="get_proofs_for_root",
    short_help="Get the stored proof flags for a given proof hash",
    help="Get the stored proof flags for a given proof hash",
)
class GetProofsForRootVCCMD:
    rpc_info: NeedsWalletRPC
    proof_hash: str = option("-r", "--proof-hash", help="The root to search for", type=str, required=True)

    async def run(self) -> None:  # pragma: no cover
        from chia.cmds.wallet_funcs import get_proofs_for_root

        async with self.rpc_info.wallet_rpc() as wallet_info:
            await get_proofs_for_root(
                wallet_info,
                self.proof_hash,
            )


@chia_command(
    group=vcs_cmd,
    name="revoke",
    short_help="Revoke any VC if you have the proper DID and the VCs parent coin",
    help="Revoke any VC if you have the proper DID and the VCs parent coin",
)
class RevokeVCCMD(TransactionEndpointWithTimelocks):
    parent_coin_id: bytes32 | None = option(
        "-p",
        "--parent-coin-id",
        help="The ID of the parent coin of the VC (optional if VC ID is used)",
        type=Bytes32ParamType(),
        required=False,
    )
    vc_id: bytes32 | None = option(
        "--vc-id",
        help="The launcher ID of the VC to revoke (must be tracked by wallet) (optional if Parent ID is used)",
        type=Bytes32ParamType(),
        required=False,
    )

    @transaction_endpoint_runner
    async def run(self) -> list[TransactionRecord]:
        from chia.cmds.wallet_funcs import revoke_vc

        reuse_puzhash = self.tx_config_loader.reuse if self.tx_config_loader.reuse is not None else False
        async with self.rpc_info.wallet_rpc() as wallet_info:
            return await revoke_vc(
                wallet_info,
                self.parent_coin_id,
                self.vc_id,
                self.fee,
                reuse_puzhash,
                self.push,
                condition_valid_times=self.load_condition_valid_times(),
            )


@chia_command(
    group=vcs_cmd,
    name="approve_r_cats",
    short_help="Claim any R-CATs that are currently pending VC approval",
    help="Claim any R-CATs that are currently pending VC approval",
)
class ApproveRCATsVCCMD(TransactionEndpointWithTimelocks):
    wallet_id: int = option(
        "-i", "--id", help="Id of the wallet with the pending approval balance", type=int, required=True
    )
    min_amount_to_claim: CliAmount = option(
        "-a",
        "--min-amount-to-claim",
        help="The minimum amount (in CAT units) to approve to move into the wallet",
        type=AmountParamType(),
        required=True,
    )

    @transaction_endpoint_runner
    async def run(self) -> list[TransactionRecord]:
        from chia.cmds.wallet_funcs import approve_r_cats

        reuse = self.tx_config_loader.reuse if self.tx_config_loader.reuse is not None else False
        async with self.rpc_info.wallet_rpc() as wallet_info:
            return await approve_r_cats(
                wallet_info,
                uint32(self.wallet_id),
                self.min_amount_to_claim,
                self.fee,
                self.tx_config_loader.min_coin_amount,
                self.tx_config_loader.max_coin_amount,
                reuse,
                self.push,
                condition_valid_times=self.load_condition_valid_times(),
            )
