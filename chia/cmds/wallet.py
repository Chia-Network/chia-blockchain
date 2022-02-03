import sys
from typing import Optional, Tuple

import click


@click.group("wallet", short_help="Manage your wallet")
def wallet_cmd() -> None:
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
    from .wallet_funcs import execute_with_wallet, get_transaction

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
@click.option("--verbose", "-v", count=True, type=int)
@click.option(
    "--paginate/--no-paginate",
    default=None,
    help="Prompt for each page of data.  Defaults to true for interactive consoles, otherwise false.",
)
def get_transactions_cmd(
    wallet_rpc_port: Optional[int],
    fingerprint: int,
    id: int,
    offset: int,
    verbose: bool,
    paginate: Optional[bool],
) -> None:
    extra_params = {"id": id, "verbose": verbose, "offset": offset, "paginate": paginate}
    import asyncio
    from .wallet_funcs import execute_with_wallet, get_transactions

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
def send_cmd(
    wallet_rpc_port: Optional[int],
    fingerprint: int,
    id: int,
    amount: str,
    memo: Optional[str],
    fee: str,
    address: str,
    override: bool,
) -> None:
    extra_params = {"id": id, "amount": amount, "memo": memo, "fee": fee, "address": address, "override": override}
    import asyncio
    from .wallet_funcs import execute_with_wallet, send

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
def show_cmd(wallet_rpc_port: Optional[int], fingerprint: int) -> None:
    import asyncio
    from .wallet_funcs import execute_with_wallet, print_balances

    asyncio.run(execute_with_wallet(wallet_rpc_port, fingerprint, {}, print_balances))


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
def get_address_cmd(wallet_rpc_port: Optional[int], id, fingerprint: int) -> None:
    extra_params = {"id": id}
    import asyncio
    from .wallet_funcs import execute_with_wallet, get_address

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
    from .wallet_funcs import execute_with_wallet, delete_unconfirmed_transactions

    asyncio.run(execute_with_wallet(wallet_rpc_port, fingerprint, extra_params, delete_unconfirmed_transactions))


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
    from .wallet_funcs import execute_with_wallet, add_token

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
@click.option("-p", "--filepath", help="The path to write the genrated offer file to", required=True)
@click.option("-m", "--fee", help="A fee to add to the offer when it gets taken", default="0")
def make_offer_cmd(
    wallet_rpc_port: Optional[int], fingerprint: int, offer: Tuple[str], request: Tuple[str], filepath: str, fee: str
) -> None:
    extra_params = {"offers": offer, "requests": request, "filepath": filepath, "fee": fee}
    import asyncio
    from .wallet_funcs import execute_with_wallet, make_offer

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
    from .wallet_funcs import execute_with_wallet, get_offers

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
    from .wallet_funcs import execute_with_wallet, take_offer

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
    from .wallet_funcs import execute_with_wallet, cancel_offer

    asyncio.run(execute_with_wallet(wallet_rpc_port, fingerprint, extra_params, cancel_offer))
