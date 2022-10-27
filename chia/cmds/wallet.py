import sys
from typing import Any, Dict, List, Optional, Tuple

import click

from chia.cmds.coins import coins_cmd
from chia.cmds.plotnft import validate_fee
from chia.wallet.transaction_sorting import SortKey
from chia.wallet.util.address_type import AddressType
from chia.wallet.util.wallet_types import WalletType
from chia.cmds.cmds_util import execute_with_wallet


@click.group("wallet", short_help="Manage your wallet")
@click.pass_context
def wallet_cmd(ctx: click.Context) -> None:
    pass


@wallet_cmd.command("get_transaction", short_help="Get a transaction")
@click.option(
    "-wp",
    "--wallet-rpc-port",
    help="Set the port where the Wallet is hosting the RPC interface. See the rpc_port under wallet in config.yaml",
    type=int,
    default=None,
)
@click.option("-f", "--fingerprint", help="Set the fingerprint to specify which wallet to use", type=int)
@click.option("-i", "--id", help="Id of the wallet to use", type=int, default=1, show_default=True, required=True)
@click.option("-tx", "--tx_id", help="transaction id to search for", type=str, required=True)
@click.option("--verbose", "-v", count=True, type=int)
def get_transaction_cmd(wallet_rpc_port: Optional[int], fingerprint: int, id: int, tx_id: str, verbose: int) -> None:
    extra_params = {"id": id, "tx_id": tx_id, "verbose": verbose}
    import asyncio
    from .wallet_funcs import get_transaction

    asyncio.run(execute_with_wallet(wallet_rpc_port, fingerprint, extra_params, get_transaction))


@wallet_cmd.command("get_transactions", short_help="Get all transactions")
@click.option(
    "-wp",
    "--wallet-rpc-port",
    help="Set the port where the Wallet is hosting the RPC interface. See the rpc_port under wallet in config.yaml",
    type=int,
    default=None,
)
@click.option("-f", "--fingerprint", help="Set the fingerprint to specify which wallet to use", type=int)
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
) -> None:
    extra_params = {
        "id": id,
        "verbose": verbose,
        "offset": offset,
        "paginate": paginate,
        "limit": limit,
        "sort_key": sort_key,
        "reverse": reverse,
    }

    import asyncio
    from .wallet_funcs import get_transactions

    asyncio.run(execute_with_wallet(wallet_rpc_port, fingerprint, extra_params, get_transactions))

    # The flush/close avoids output like below when piping through `head -n 1`
    # which will close stdout.
    #
    # Exception ignored in: <_io.TextIOWrapper name='<stdout>' mode='w' encoding='utf-8'>
    # BrokenPipeError: [Errno 32] Broken pipe
    sys.stdout.flush()
    sys.stdout.close()


@wallet_cmd.command("send", short_help="Send chia to another wallet")
@click.option(
    "-wp",
    "--wallet-rpc-port",
    help="Set the port where the Wallet is hosting the RPC interface. See the rpc_port under wallet in config.yaml",
    type=int,
    default=None,
)
@click.option("-f", "--fingerprint", help="Set the fingerprint to specify which wallet to use", type=int)
@click.option("-i", "--id", help="Id of the wallet to use", type=int, default=1, show_default=True, required=True)
@click.option("-a", "--amount", help="How much chia to send, in XCH", type=str, required=True)
@click.option("-e", "--memo", help="Additional memo for the transaction", type=str, default=None)
@click.option(
    "-m",
    "--fee",
    help="Set the fees for the transaction, in XCH",
    type=str,
    default="0",
    show_default=True,
    required=True,
)
@click.option("-t", "--address", help="Address to send the XCH", type=str, required=True)
@click.option(
    "-o", "--override", help="Submits transaction without checking for unusual values", is_flag=True, default=False
)
@click.option(
    "-ma",
    "--min-coin-amount",
    help="Ignore coins worth less then this much XCH or CAT units",
    type=str,
    required=False,
    default="0",
)
@click.option(
    "-l",
    "--max-coin-amount",
    help="Ignore coins worth more then this much XCH or CAT units",
    type=str,
    required=False,
    default="0",
)
@click.option(
    "-e",
    "--exclude-coin-ids",
    multiple=True,
    help="Exclude this coin from being spent.",
)
def send_cmd(
    wallet_rpc_port: Optional[int],
    fingerprint: int,
    id: int,
    amount: str,
    memo: Optional[str],
    fee: str,
    address: str,
    override: bool,
    min_coin_amount: str,
    max_coin_amount: str,
    exclude_coin_ids: Tuple[str],
) -> None:
    extra_params = {
        "id": id,
        "amount": amount,
        "memo": memo,
        "fee": fee,
        "address": address,
        "override": override,
        "min_coin_amount": min_coin_amount,
        "max_coin_amount": max_coin_amount,
        "exclude_coin_ids": list(exclude_coin_ids),
    }
    import asyncio
    from .wallet_funcs import send

    asyncio.run(execute_with_wallet(wallet_rpc_port, fingerprint, extra_params, send))


@wallet_cmd.command("show", short_help="Show wallet information")
@click.option(
    "-wp",
    "--wallet-rpc-port",
    help="Set the port where the Wallet is hosting the RPC interface. See the rpc_port under wallet in config.yaml",
    type=int,
    default=None,
)
@click.option("-f", "--fingerprint", help="Set the fingerprint to specify which wallet to use", type=int)
@click.option(
    "-w",
    "--wallet_type",
    help="Choose a specific wallet type to return",
    type=click.Choice([x.name.lower() for x in WalletType]),
    default=None,
)
def show_cmd(wallet_rpc_port: Optional[int], fingerprint: int, wallet_type: Optional[str]) -> None:
    import asyncio
    from .wallet_funcs import print_balances

    args: Dict[str, Any] = {}
    if wallet_type is not None:
        args["type"] = WalletType[wallet_type.upper()]
    asyncio.run(execute_with_wallet(wallet_rpc_port, fingerprint, args, print_balances))


@wallet_cmd.command("get_address", short_help="Get a wallet receive address")
@click.option(
    "-wp",
    "--wallet-rpc-port",
    help="Set the port where the Wallet is hosting the RPC interface. See the rpc_port under wallet in config.yaml",
    type=int,
    default=None,
)
@click.option("-i", "--id", help="Id of the wallet to use", type=int, default=1, show_default=True, required=True)
@click.option("-f", "--fingerprint", help="Set the fingerprint to specify which wallet to use", type=int)
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
def get_address_cmd(wallet_rpc_port: Optional[int], id, fingerprint: int, new_address: bool) -> None:
    extra_params = {"id": id, "new_address": new_address}
    import asyncio
    from .wallet_funcs import get_address

    asyncio.run(execute_with_wallet(wallet_rpc_port, fingerprint, extra_params, get_address))


@wallet_cmd.command(
    "delete_unconfirmed_transactions", short_help="Deletes all unconfirmed transactions for this wallet ID"
)
@click.option(
    "-wp",
    "--wallet-rpc-port",
    help="Set the port where the Wallet is hosting the RPC interface. See the rpc_port under wallet in config.yaml",
    type=int,
    default=None,
)
@click.option("-i", "--id", help="Id of the wallet to use", type=int, default=1, show_default=True, required=True)
@click.option("-f", "--fingerprint", help="Set the fingerprint to specify which wallet to use", type=int)
def delete_unconfirmed_transactions_cmd(wallet_rpc_port: Optional[int], id, fingerprint: int) -> None:
    extra_params = {"id": id}
    import asyncio
    from .wallet_funcs import delete_unconfirmed_transactions

    asyncio.run(execute_with_wallet(wallet_rpc_port, fingerprint, extra_params, delete_unconfirmed_transactions))


@wallet_cmd.command("get_derivation_index", short_help="Get the last puzzle hash derivation path index")
@click.option(
    "-wp",
    "--wallet-rpc-port",
    help="Set the port where the Wallet is hosting the RPC interface. See the rpc_port under wallet in config.yaml",
    type=int,
    default=None,
)
@click.option("-f", "--fingerprint", help="Set the fingerprint to specify which wallet to use", type=int)
def get_derivation_index_cmd(wallet_rpc_port: Optional[int], fingerprint: int) -> None:
    extra_params: Dict[str, Any] = {}
    import asyncio
    from .wallet_funcs import get_derivation_index

    asyncio.run(execute_with_wallet(wallet_rpc_port, fingerprint, extra_params, get_derivation_index))


@wallet_cmd.command("sign_message", short_help="Sign a message by a derivation address")
@click.option(
    "-wp",
    "--wallet-rpc-port",
    help="Set the port where the Wallet is hosting the RPC interface. See the rpc_port under wallet in config.yaml",
    type=int,
    default=None,
)
@click.option("-f", "--fingerprint", help="Set the fingerprint to specify which wallet to use", type=int)
@click.option("-a", "--address", help="The address you want to use for signing", type=str, required=True)
@click.option("-m", "--hex_message", help="The hex message you want sign", type=str, required=True)
def address_sign_message(wallet_rpc_port: Optional[int], fingerprint: int, address: str, hex_message: str) -> None:
    extra_params: Dict[str, Any] = {"address": address, "message": hex_message, "type": AddressType.XCH}
    import asyncio
    from .wallet_funcs import sign_message

    asyncio.run(execute_with_wallet(wallet_rpc_port, fingerprint, extra_params, sign_message))


@wallet_cmd.command(
    "update_derivation_index", short_help="Generate additional derived puzzle hashes starting at the provided index"
)
@click.option(
    "-wp",
    "--wallet-rpc-port",
    help="Set the port where the Wallet is hosting the RPC interface. See the rpc_port under wallet in config.yaml",
    type=int,
    default=None,
)
@click.option("-f", "--fingerprint", help="Set the fingerprint to specify which wallet to use", type=int)
@click.option(
    "-i", "--index", help="Index to set. Must be greater than the current derivation index", type=int, required=True
)
def update_derivation_index_cmd(wallet_rpc_port: Optional[int], fingerprint: int, index: int) -> None:
    extra_params = {"index": index}
    import asyncio
    from .wallet_funcs import update_derivation_index

    asyncio.run(execute_with_wallet(wallet_rpc_port, fingerprint, extra_params, update_derivation_index))


@wallet_cmd.command("add_token", short_help="Add/Rename a CAT to the wallet by its asset ID")
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
    required=True,
)
@click.option(
    "-n",
    "--token-name",
    help="The name you wish to designate to the token",
)
@click.option(
    "-f",
    "--fingerprint",
    type=int,
    default=None,
    help="The wallet fingerprint you wish to add the token to",
)
def add_token_cmd(wallet_rpc_port: Optional[int], asset_id: str, token_name: str, fingerprint: int) -> None:
    extra_params = {"asset_id": asset_id, "token_name": token_name}
    import asyncio
    from .wallet_funcs import add_token

    asyncio.run(execute_with_wallet(wallet_rpc_port, fingerprint, extra_params, add_token))


@wallet_cmd.command("make_offer", short_help="Create an offer of XCH/CATs for XCH/CATs")
@click.option(
    "-wp",
    "--wallet-rpc-port",
    help="Set the port where the Wallet is hosting the RPC interface. See the rpc_port under wallet in config.yaml",
    type=int,
    default=None,
)
@click.option("-f", "--fingerprint", help="Set the fingerprint to specify which wallet to use", type=int)
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
    required=True,
    multiple=True,
)
@click.option("-p", "--filepath", help="The path to write the generated offer file to", required=True)
@click.option("-m", "--fee", help="A fee to add to the offer when it gets taken", default="0")
def make_offer_cmd(
    wallet_rpc_port: Optional[int], fingerprint: int, offer: Tuple[str], request: Tuple[str], filepath: str, fee: str
) -> None:
    extra_params = {"offers": offer, "requests": request, "filepath": filepath, "fee": fee}
    import asyncio
    from .wallet_funcs import make_offer

    asyncio.run(execute_with_wallet(wallet_rpc_port, fingerprint, extra_params, make_offer))


@wallet_cmd.command(
    "get_offers", short_help="Get the status of existing offers. Displays only active/pending offers by default."
)
@click.option(
    "-wp",
    "--wallet-rpc-port",
    help="Set the port where the Wallet is hosting the RPC interface. See the rpc_port under wallet in config.yaml",
    type=int,
    default=None,
)
@click.option("-f", "--fingerprint", help="Set the fingerprint to specify which wallet to use", type=int)
@click.option("-id", "--id", help="The ID of the offer that you wish to examine")
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
    id: Optional[str],
    filepath: Optional[str],
    exclude_my_offers: bool,
    exclude_taken_offers: bool,
    include_completed: bool,
    summaries: bool,
    reverse: bool,
) -> None:
    extra_params = {
        "id": id,
        "filepath": filepath,
        "exclude_my_offers": exclude_my_offers,
        "exclude_taken_offers": exclude_taken_offers,
        "include_completed": include_completed,
        "summaries": summaries,
        "reverse": reverse,
    }
    import asyncio
    from .wallet_funcs import get_offers

    asyncio.run(execute_with_wallet(wallet_rpc_port, fingerprint, extra_params, get_offers))


@wallet_cmd.command("take_offer", short_help="Examine or take an offer")
@click.argument("path_or_hex", type=str, nargs=1, required=True)
@click.option(
    "-wp",
    "--wallet-rpc-port",
    help="Set the port where the Wallet is hosting the RPC interface. See the rpc_port under wallet in config.yaml",
    type=int,
    default=None,
)
@click.option("-f", "--fingerprint", help="Set the fingerprint to specify which wallet to use", type=int)
@click.option("-e", "--examine-only", help="Print the summary of the offer file but do not take it", is_flag=True)
@click.option("-m", "--fee", help="The fee to use when pushing the completed offer", default="0")
def take_offer_cmd(
    path_or_hex: str, wallet_rpc_port: Optional[int], fingerprint: int, examine_only: bool, fee: str
) -> None:
    extra_params = {"file": path_or_hex, "examine_only": examine_only, "fee": fee}
    import asyncio
    from .wallet_funcs import take_offer

    asyncio.run(execute_with_wallet(wallet_rpc_port, fingerprint, extra_params, take_offer))


@wallet_cmd.command("cancel_offer", short_help="Cancel an existing offer")
@click.option(
    "-wp",
    "--wallet-rpc-port",
    help="Set the port where the Wallet is hosting the RPC interface. See the rpc_port under wallet in config.yaml",
    type=int,
    default=None,
)
@click.option("-f", "--fingerprint", help="Set the fingerprint to specify which wallet to use", type=int)
@click.option("-id", "--id", help="The offer ID that you wish to cancel")
@click.option("--insecure", help="Don't make an on-chain transaction, simply mark the offer as cancelled", is_flag=True)
@click.option("-m", "--fee", help="The fee to use when cancelling the offer securely", default="0")
def cancel_offer_cmd(wallet_rpc_port: Optional[int], fingerprint: int, id: str, insecure: bool, fee: str) -> None:
    extra_params = {"id": id, "insecure": insecure, "fee": fee}
    import asyncio
    from .wallet_funcs import cancel_offer

    asyncio.run(execute_with_wallet(wallet_rpc_port, fingerprint, extra_params, cancel_offer))


@wallet_cmd.group("did", short_help="DID related actions")
def did_cmd():
    pass


@did_cmd.command("create", short_help="Create DID wallet")
@click.option(
    "-wp",
    "--wallet-rpc-port",
    help="Set the port where the Wallet is hosting the RPC interface. See the rpc_port under wallet in config.yaml",
    type=int,
    default=None,
)
@click.option("-f", "--fingerprint", help="Set the fingerprint to specify which wallet to use", type=int)
@click.option("-n", "--name", help="Set the DID wallet name", type=str)
@click.option(
    "-a",
    "--amount",
    help="Set the DID amount in mojos. Value must be an odd number.",
    type=int,
    default=1,
    show_default=True,
)
@click.option(
    "-m",
    "--fee",
    help="Set the fees per transaction, in XCH.",
    type=str,
    default="0",
    show_default=True,
    callback=validate_fee,
)
def did_create_wallet_cmd(
    wallet_rpc_port: Optional[int], fingerprint: int, name: Optional[str], amount: Optional[int], fee: Optional[int]
) -> None:
    import asyncio
    from .wallet_funcs import create_did_wallet

    extra_params = {"amount": amount, "fee": fee, "name": name}
    asyncio.run(execute_with_wallet(wallet_rpc_port, fingerprint, extra_params, create_did_wallet))


@did_cmd.command("sign_message", short_help="Sign a message by a DID")
@click.option(
    "-wp",
    "--wallet-rpc-port",
    help="Set the port where the Wallet is hosting the RPC interface. See the rpc_port under wallet in config.yaml",
    type=int,
    default=None,
)
@click.option("-f", "--fingerprint", help="Set the fingerprint to specify which wallet to use", type=int)
@click.option("-i", "--did_id", help="DID ID you want to use for signing", type=str, required=True)
@click.option("-m", "--hex_message", help="The hex message you want to sign", type=str, required=True)
def did_sign_message(wallet_rpc_port: Optional[int], fingerprint: int, did_id: str, hex_message: str) -> None:
    extra_params: Dict[str, Any] = {"did_id": did_id, "message": hex_message, "type": AddressType.DID}
    import asyncio
    from .wallet_funcs import sign_message

    asyncio.run(execute_with_wallet(wallet_rpc_port, fingerprint, extra_params, sign_message))


@did_cmd.command("set_name", short_help="Set DID wallet name")
@click.option(
    "-wp",
    "--wallet-rpc-port",
    help="Set the port where the Wallet is hosting the RPC interface. See the rpc_port under wallet in config.yaml",
    type=int,
    default=None,
)
@click.option("-f", "--fingerprint", help="Set the fingerprint to specify which wallet to use", type=int)
@click.option("-i", "--id", help="Id of the wallet to use", type=int, required=True)
@click.option("-n", "--name", help="Set the DID wallet name", type=str, required=True)
def did_wallet_name_cmd(wallet_rpc_port: Optional[int], fingerprint: int, id: int, name: str) -> None:
    import asyncio
    from .wallet_funcs import did_set_wallet_name

    extra_params = {"wallet_id": id, "name": name}
    asyncio.run(execute_with_wallet(wallet_rpc_port, fingerprint, extra_params, did_set_wallet_name))


@did_cmd.command("get_did", short_help="Get DID from wallet")
@click.option(
    "-wp",
    "--wallet-rpc-port",
    help="Set the port where the Wallet is hosting the RPC interface. See the rpc_port under wallet in config.yaml",
    type=int,
    default=None,
)
@click.option("-f", "--fingerprint", help="Set the fingerprint to specify which wallet to use", type=int)
@click.option("-i", "--id", help="Id of the wallet to use", type=int, required=True)
def did_get_did_cmd(wallet_rpc_port: Optional[int], fingerprint: int, id: int) -> None:
    import asyncio
    from .wallet_funcs import get_did

    extra_params = {"did_wallet_id": id}
    asyncio.run(execute_with_wallet(wallet_rpc_port, fingerprint, extra_params, get_did))


@wallet_cmd.group("nft", short_help="NFT related actions")
def nft_cmd():
    pass


@nft_cmd.command("create", short_help="Create an NFT wallet")
@click.option(
    "-wp",
    "--wallet-rpc-port",
    help="Set the port where the Wallet is hosting the RPC interface. See the rpc_port under wallet in config.yaml",
    type=int,
    default=None,
)
@click.option("-f", "--fingerprint", help="Set the fingerprint to specify which wallet to use", type=int)
@click.option("-di", "--did-id", help="DID Id to use", type=str)
@click.option("-n", "--name", help="Set the NFT wallet name", type=str)
def nft_wallet_create_cmd(
    wallet_rpc_port: Optional[int], fingerprint: int, did_id: Optional[str], name: Optional[str]
) -> None:
    import asyncio
    from .wallet_funcs import create_nft_wallet

    extra_params: Dict[str, Any] = {"did_id": did_id, "name": name}
    asyncio.run(execute_with_wallet(wallet_rpc_port, fingerprint, extra_params, create_nft_wallet))


@nft_cmd.command("sign_message", short_help="Sign a message by a NFT")
@click.option(
    "-wp",
    "--wallet-rpc-port",
    help="Set the port where the Wallet is hosting the RPC interface. See the rpc_port under wallet in config.yaml",
    type=int,
    default=None,
)
@click.option("-f", "--fingerprint", help="Set the fingerprint to specify which wallet to use", type=int)
@click.option("-i", "--nft_id", help="NFT ID you want to use for signing", type=str, required=True)
@click.option("-m", "--hex_message", help="The hex message you want to sign", type=str, required=True)
def nft_sign_message(wallet_rpc_port: Optional[int], fingerprint: int, nft_id: str, hex_message: str) -> None:
    extra_params: Dict[str, Any] = {"nft_id": nft_id, "message": hex_message, "type": AddressType.NFT}
    import asyncio
    from .wallet_funcs import sign_message

    asyncio.run(execute_with_wallet(wallet_rpc_port, fingerprint, extra_params, sign_message))


@nft_cmd.command("mint", short_help="Mint an NFT")
@click.option(
    "-wp",
    "--wallet-rpc-port",
    help="Set the port where the Wallet is hosting the RPC interface. See the rpc_port under wallet in config.yaml",
    type=int,
    default=None,
)
@click.option("-f", "--fingerprint", help="Set the fingerprint to specify which wallet to use", type=int)
@click.option("-i", "--id", help="Id of the NFT wallet to use", type=int, required=True)
@click.option("-ra", "--royalty-address", help="Royalty address", type=str)
@click.option("-ta", "--target-address", help="Target address", type=str)
@click.option("--no-did-ownership", help="Disable DID ownership support", is_flag=True, default=False)
@click.option("-nh", "--hash", help="NFT content hash", type=str, required=True)
@click.option("-u", "--uris", help="Comma separated list of URIs", type=str, required=True)
@click.option("-mh", "--metadata-hash", help="NFT metadata hash", type=str, default="")
@click.option("-mu", "--metadata-uris", help="Comma separated list of metadata URIs", type=str)
@click.option("-lh", "--license-hash", help="NFT license hash", type=str, default="")
@click.option("-lu", "--license-uris", help="Comma separated list of license URIs", type=str)
@click.option("-et", "--edition-total", help="NFT edition total", type=int, show_default=True, default=1)
@click.option("-en", "--edition-number", help="NFT edition number", show_default=True, default=1, type=int)
@click.option(
    "-m",
    "--fee",
    help="Set the fees per transaction, in XCH.",
    type=str,
    default="0",
    show_default=True,
    callback=validate_fee,
)
@click.option(
    "-rp",
    "--royalty-percentage-fraction",
    help="NFT royalty percentage fraction in basis points. Example: 175 would represent 1.75%",
    type=int,
    default=0,
    show_default=True,
)
def nft_mint_cmd(
    wallet_rpc_port: Optional[int],
    fingerprint: int,
    id: int,
    royalty_address: Optional[str],
    target_address: Optional[str],
    no_did_ownership: bool,
    hash: str,
    uris: str,
    metadata_hash: Optional[str],
    metadata_uris: Optional[str],
    license_hash: Optional[str],
    license_uris: Optional[str],
    edition_total: Optional[int],
    edition_number: Optional[int],
    fee: str,
    royalty_percentage_fraction: int,
) -> None:
    import asyncio
    from .wallet_funcs import mint_nft

    if metadata_uris is None:
        metadata_uris_list = []
    else:
        metadata_uris_list = [mu.strip() for mu in metadata_uris.split(",")]

    if license_uris is None:
        license_uris_list = []
    else:
        license_uris_list = [lu.strip() for lu in license_uris.split(",")]

    extra_params = {
        "wallet_id": id,
        "royalty_address": royalty_address,
        "target_address": target_address,
        "no_did_ownership": no_did_ownership,
        "hash": hash,
        "uris": [u.strip() for u in uris.split(",")],
        "metadata_hash": metadata_hash,
        "metadata_uris": metadata_uris_list,
        "license_hash": license_hash,
        "license_uris": license_uris_list,
        "edition_total": edition_total,
        "edition_number": edition_number,
        "fee": fee,
        "royalty_percentage": royalty_percentage_fraction,
    }
    asyncio.run(execute_with_wallet(wallet_rpc_port, fingerprint, extra_params, mint_nft))


@nft_cmd.command("add_uri", short_help="Add an URI to an NFT")
@click.option(
    "-wp",
    "--wallet-rpc-port",
    help="Set the port where the Wallet is hosting the RPC interface. See the rpc_port under wallet in config.yaml",
    type=int,
    default=None,
)
@click.option("-f", "--fingerprint", help="Set the fingerprint to specify which wallet to use", type=int)
@click.option("-i", "--id", help="Id of the NFT wallet to use", type=int, required=True)
@click.option("-ni", "--nft-coin-id", help="Id of the NFT coin to add the URI to", type=str, required=True)
@click.option("-u", "--uri", help="URI to add to the NFT", type=str)
@click.option("-mu", "--metadata-uri", help="Metadata URI to add to the NFT", type=str)
@click.option("-lu", "--license-uri", help="License URI to add to the NFT", type=str)
@click.option(
    "-m",
    "--fee",
    help="Set the fees per transaction, in XCH.",
    type=str,
    default="0",
    show_default=True,
    callback=validate_fee,
)
def nft_add_uri_cmd(
    wallet_rpc_port: Optional[int],
    fingerprint: int,
    id: int,
    nft_coin_id: str,
    uri: str,
    metadata_uri: str,
    license_uri: str,
    fee: str,
) -> None:
    import asyncio
    from .wallet_funcs import add_uri_to_nft

    extra_params = {
        "wallet_id": id,
        "nft_coin_id": nft_coin_id,
        "uri": uri,
        "metadata_uri": metadata_uri,
        "license_uri": license_uri,
        "fee": fee,
    }
    asyncio.run(execute_with_wallet(wallet_rpc_port, fingerprint, extra_params, add_uri_to_nft))


@nft_cmd.command("transfer", short_help="Transfer an NFT")
@click.option(
    "-wp",
    "--wallet-rpc-port",
    help="Set the port where the Wallet is hosting the RPC interface. See the rpc_port under wallet in config.yaml",
    type=int,
    default=None,
)
@click.option("-f", "--fingerprint", help="Set the fingerprint to specify which wallet to use", type=int)
@click.option("-i", "--id", help="Id of the NFT wallet to use", type=int, required=True)
@click.option("-ni", "--nft-coin-id", help="Id of the NFT coin to transfer", type=str, required=True)
@click.option("-ta", "--target-address", help="Target recipient wallet address", type=str, required=True)
@click.option(
    "-m",
    "--fee",
    help="Set the fees per transaction, in XCH.",
    type=str,
    default="0",
    show_default=True,
    callback=validate_fee,
)
def nft_transfer_cmd(
    wallet_rpc_port: Optional[int],
    fingerprint: int,
    id: int,
    nft_coin_id: str,
    target_address: str,
    fee: str,
) -> None:
    import asyncio
    from .wallet_funcs import transfer_nft

    extra_params = {
        "wallet_id": id,
        "nft_coin_id": nft_coin_id,
        "target_address": target_address,
        "fee": fee,
    }
    asyncio.run(execute_with_wallet(wallet_rpc_port, fingerprint, extra_params, transfer_nft))


@nft_cmd.command("list", short_help="List the current NFTs")
@click.option(
    "-wp",
    "--wallet-rpc-port",
    help="Set the port where the Wallet is hosting the RPC interface. See the rpc_port under wallet in config.yaml",
    type=int,
    default=None,
)
@click.option("-f", "--fingerprint", help="Set the fingerprint to specify which wallet to use", type=int)
@click.option("-i", "--id", help="Id of the NFT wallet to use", type=int, required=True)
def nft_list_cmd(wallet_rpc_port: Optional[int], fingerprint: int, id: int) -> None:
    import asyncio
    from .wallet_funcs import list_nfts

    extra_params = {"wallet_id": id}
    asyncio.run(execute_with_wallet(wallet_rpc_port, fingerprint, extra_params, list_nfts))


@nft_cmd.command("set_did", short_help="Set a DID on an NFT")
@click.option(
    "-wp",
    "--wallet-rpc-port",
    help="Set the port where the Wallet is hosting the RPC interface. See the rpc_port under wallet in config.yaml",
    type=int,
    default=None,
)
@click.option("-f", "--fingerprint", help="Set the fingerprint to specify which wallet to use", type=int)
@click.option("-i", "--id", help="Id of the NFT wallet to use", type=int, required=True)
@click.option("-di", "--did-id", help="DID Id to set on the NFT", type=str, required=True)
@click.option("-ni", "--nft-coin-id", help="Id of the NFT coin to set the DID on", type=str, required=True)
@click.option(
    "-m",
    "--fee",
    help="Set the fees per transaction, in XCH.",
    type=str,
    default="0",
    show_default=True,
    callback=validate_fee,
)
def nft_set_did_cmd(
    wallet_rpc_port: Optional[int],
    fingerprint: int,
    id: int,
    did_id: str,
    nft_coin_id: str,
    fee: str,
) -> None:
    import asyncio
    from .wallet_funcs import set_nft_did

    extra_params = {
        "wallet_id": id,
        "did_id": did_id,
        "nft_coin_id": nft_coin_id,
        "fee": fee,
    }
    asyncio.run(execute_with_wallet(wallet_rpc_port, fingerprint, extra_params, set_nft_did))


@nft_cmd.command("get_info", short_help="Get NFT information")
@click.option(
    "-wp",
    "--wallet-rpc-port",
    help="Set the port where the Wallet is hosting the RPC interface. See the rpc_port under wallet in config.yaml",
    type=int,
    default=None,
)
@click.option("-f", "--fingerprint", help="Set the fingerprint to specify which wallet to use", type=int)
@click.option("-ni", "--nft-coin-id", help="Id of the NFT coin to get information on", type=str, required=True)
def nft_get_info_cmd(
    wallet_rpc_port: Optional[int],
    fingerprint: int,
    nft_coin_id: str,
) -> None:
    import asyncio
    from .wallet_funcs import get_nft_info

    extra_params = {
        "nft_coin_id": nft_coin_id,
    }
    asyncio.run(execute_with_wallet(wallet_rpc_port, fingerprint, extra_params, get_nft_info))


# Keep at bottom.
wallet_cmd.add_command(coins_cmd)


@wallet_cmd.group("notifications", short_help="Send/Manage notifications")
def notification_cmd():
    pass


@notification_cmd.command("send", short_help="Send a notification to the owner of an address")
@click.option(
    "-wp",
    "--wallet-rpc-port",
    help="Set the port where the Wallet is hosting the RPC interface. See the rpc_port under wallet in config.yaml",
    type=int,
    default=None,
)
@click.option("-f", "--fingerprint", help="Set the fingerprint to specify which wallet to use", type=int)
@click.option("-t", "--to-address", help="The address to send the notification to", type=str, required=True)
@click.option(
    "-a",
    "--amount",
    help="The amount to send to get the notification past the recipient's spam filter",
    type=str,
    default="0.00001",
    required=True,
    show_default=True,
)
@click.option("-n", "--message", help="The message of the notification", type=str)
@click.option("-m", "--fee", help="The fee for the transaction", type=str)
def _send_notification(
    wallet_rpc_port: Optional[int],
    fingerprint: int,
    to_address: str,
    amount: str,
    message: str,
    fee: str,
) -> None:
    import asyncio
    from .wallet_funcs import send_notification
    from chia.cmds.cmds_util import execute_with_wallet

    extra_params = {
        "address": to_address,
        "amount": amount,
        "message": message,
        "fee": fee,
    }
    asyncio.run(execute_with_wallet(wallet_rpc_port, fingerprint, extra_params, send_notification))


@notification_cmd.command("get", short_help="Get notification(s) that are in your wallet")
@click.option(
    "-wp",
    "--wallet-rpc-port",
    help="Set the port where the Wallet is hosting the RPC interface. See the rpc_port under wallet in config.yaml",
    type=int,
    default=None,
)
@click.option("-f", "--fingerprint", help="Set the fingerprint to specify which wallet to use", type=int)
@click.option("-i", "--id", help="The specific notification ID to show", type=str, default=[], multiple=True)
@click.option("-s", "--start", help="The number of notifications to skip", type=int, default=None)
@click.option("-e", "--end", help="The number of notifications to stop at", type=int, default=None)
def _get_notifications(
    wallet_rpc_port: Optional[int],
    fingerprint: int,
    id: List[str],
    start: Optional[int],
    end: Optional[int],
) -> None:
    import asyncio
    from .wallet_funcs import get_notifications
    from chia.cmds.cmds_util import execute_with_wallet

    extra_params = {
        "ids": id,
        "start": start,
        "end": end,
    }
    asyncio.run(execute_with_wallet(wallet_rpc_port, fingerprint, extra_params, get_notifications))


@notification_cmd.command("delete", short_help="Delete notification(s) that are in your wallet")
@click.option(
    "-wp",
    "--wallet-rpc-port",
    help="Set the port where the Wallet is hosting the RPC interface. See the rpc_port under wallet in config.yaml",
    type=int,
    default=None,
)
@click.option("-f", "--fingerprint", help="Set the fingerprint to specify which wallet to use", type=int)
@click.option("-i", "--id", help="A specific notification ID to delete", type=str, multiple=True)
@click.option("--all", help="All notifications can be deleted (they will be recovered during resync)", is_flag=True)
def _delete_notifications(
    wallet_rpc_port: Optional[int],
    fingerprint: int,
    id: List[str],
    all: bool,
) -> None:
    import asyncio
    from .wallet_funcs import delete_notifications
    from chia.cmds.cmds_util import execute_with_wallet

    extra_params = {
        "ids": id,
        "all": all,
    }
    asyncio.run(execute_with_wallet(wallet_rpc_port, fingerprint, extra_params, delete_notifications))
