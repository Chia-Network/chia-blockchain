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
def get_transaction_cmd(wallet_rpc_port: int, fingerprint: int, id: int, tx_id: str, verbose: int) -> None:
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
def get_transactions_cmd(wallet_rpc_port: int, fingerprint: int, id: int, offset: int, verbose: bool) -> None:
    extra_params = {"id": id, "verbose": verbose, "offset": offset}
    import asyncio
    from .wallet_funcs import execute_with_wallet, get_transactions

    asyncio.run(execute_with_wallet(wallet_rpc_port, fingerprint, extra_params, get_transactions))


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
@click.option("-a", "--amount", help="How much chia to send, in TXCH/XCH", type=str, required=True)
@click.option(
    "-m", "--fee", help="Set the fees for the transaction", type=str, default="0", show_default=True, required=True
)
@click.option("-t", "--address", help="Address to send the TXCH/XCH", type=str, required=True)
def send_cmd(wallet_rpc_port: int, fingerprint: int, id: int, amount: str, fee: str, address: str) -> None:
    extra_params = {"id": id, "amount": amount, "fee": fee, "address": address}
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
def show_cmd(wallet_rpc_port: int, fingerprint: int) -> None:
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
def get_address_cmd(wallet_rpc_port: int, id, fingerprint: int) -> None:
    extra_params = {"id": id}
    import asyncio
    from .wallet_funcs import execute_with_wallet, get_address

    asyncio.run(execute_with_wallet(wallet_rpc_port, fingerprint, extra_params, get_address))
