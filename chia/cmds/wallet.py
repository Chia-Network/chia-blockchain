import click
import sys
from typing import Any, Dict

from decimal import Decimal


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
@click.option("-a", "--amount", help="How much chia to send, in XCH", type=str, required=True)
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
    wallet_rpc_port: int, fingerprint: int, id: int, amount: str, fee: str, address: str, override: bool
) -> None:
    extra_params = {"id": id, "amount": amount, "fee": fee, "address": address, "override": override}
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


@wallet_cmd.group("create", short_help="Create new wallets")
def wallet_create_cmd():
    pass


@wallet_create_cmd.command("coloured-coin", short_help="Create a coloured coin wallet")
@click.option(
    "-wp",
    "--wallet-rpc-port",
    help="Set the port where the Wallet is hosting the RPC interface. See the rpc_port under wallet in config.yaml",
    type=int,
    default=9256,
    show_default=True,
)
@click.option("-c", "--colour-id", help="Id of the colour for the new wallet", type=str)
@click.option("-a", "--amount", help="How much chia to destroy to create this coloured coin, in TXCH/XCH", type=str)
@click.option(
    "-m", "--fee", help="Set the fees for the transaction", type=str, default="0", show_default=True, required=True
)
@click.option("-f", "--fingerprint", help="Set the fingerprint to specify which wallet to use", type=int)
def create_coloured_coin_cmd(wallet_rpc_port: int, colour_id: str, amount: str, fee: str, fingerprint: int) -> None:
    if not colour_id and not amount:
        print(
            (
                "You must use --amount to create a new coloured coin or --colour-id "
                "to create a wallet of an existing colour, but at least one."
            )
        )
        sys.exit(1)
    if colour_id and amount:
        print(
            (
                "You can use --amount to create a new coloured coin or --colour-id "
                "to create a wallet of an existing colour, but not both."
            )
        )
        sys.exit(1)

    import asyncio
    from .wallet_funcs import execute_with_wallet, create_new_wallet
    from chia.cmds.units import units
    from chia.util.ints import uint64

    final_fee = uint64(int(Decimal(fee) * units["chia"]))
    data: Dict[str, Any] = {"fee": final_fee}
    if colour_id:
        data["mode"] = "existing"
        data["colour"] = colour_id
    else:
        data["mode"] = "new"
        final_amount = uint64(int(Decimal(amount) * units["chia"]))
        data["amount"] = final_amount
    extra_params = {"wallet_type": "cc_wallet", "data": data}
    asyncio.run(execute_with_wallet(wallet_rpc_port, fingerprint, extra_params, create_new_wallet))


@wallet_create_cmd.command("rate-limited-admin", short_help="Create a rate limited admin wallet")
@click.option(
    "-wp",
    "--wallet-rpc-port",
    help="Set the port where the Wallet is hosting the RPC interface. See the rpc_port under wallet in config.yaml",
    type=int,
    default=9256,
    show_default=True,
)
@click.option("-i", "--interval", help="Spending interval length (Number of blocks).", type=int, required=True)
@click.option("-l", "--limit", help="Spendable amount per interval, in TXCH/XCH.", type=str, required=True)
@click.option("-a", "--amount", help="Amount for initial coin. in TXCH/XCH.", type=str, required=True)
@click.option(
    "-m", "--fee", help="Set the fees for the transaction", type=str, default="0", show_default=True, required=True
)
@click.option("--public_key", "-p", default=None, help="Enter the pk in hex", type=str, required=True)
@click.option("-f", "--fingerprint", help="Set the fingerprint to specify which wallet to use", type=int)
def create_rate_limited_admin_cmd(
    wallet_rpc_port: int, interval: int, limit: str, amount: str, fee: str, public_key: str, fingerprint: int
) -> None:
    import asyncio
    from .wallet_funcs import execute_with_wallet, create_new_wallet
    from chia.cmds.units import units
    from chia.util.ints import uint64

    final_fee = uint64(int(Decimal(fee) * units["chia"]))
    final_amount = uint64(int(Decimal(amount) * units["chia"]))
    final_limit = uint64(int(Decimal(limit) * units["chia"]))
    data: Dict[str, Any] = {
        "fee": final_fee,
        "amount": final_amount,
        "pubkey": public_key,
        "limit": final_limit,
        "rl_type": "admin",
        "interval": interval,
    }
    extra_params = {"wallet_type": "rl_wallet", "data": data}
    asyncio.run(execute_with_wallet(wallet_rpc_port, fingerprint, extra_params, create_new_wallet))


@wallet_create_cmd.command("rate-limited-user", short_help="Create a rate limited user wallet")
@click.option(
    "-wp",
    "--wallet-rpc-port",
    help="Set the port where the Wallet is hosting the RPC interface. See the rpc_port under wallet in config.yaml",
    type=int,
    default=9256,
    show_default=True,
)
@click.option("-f", "--fingerprint", help="Set the fingerprint to specify which wallet to use", type=int)
def create_rate_limited_user_cmd(wallet_rpc_port: int, fingerprint: int) -> None:
    import asyncio
    from .wallet_funcs import execute_with_wallet, create_new_wallet

    extra_params = {"wallet_type": "rl_wallet", "data": {"rl_type": "user"}}
    asyncio.run(execute_with_wallet(wallet_rpc_port, fingerprint, extra_params, create_new_wallet))

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
def delete_unconfirmed_transactions_cmd(wallet_rpc_port: int, id, fingerprint: int) -> None:
    extra_params = {"id": id}
    import asyncio
    from .wallet_funcs import execute_with_wallet, delete_unconfirmed_transactions

    asyncio.run(execute_with_wallet(wallet_rpc_port, fingerprint, extra_params, delete_unconfirmed_transactions))
