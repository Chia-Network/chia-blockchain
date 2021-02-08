import time
from typing import Tuple, Optional, Callable

import aiohttp
import asyncio

from src.rpc.wallet_rpc_client import WalletRpcClient
from src.util.byte_types import hexstr_to_bytes
from src.util.config import load_config
from src.util.default_root import DEFAULT_ROOT_PATH
from src.wallet.util.wallet_types import WalletType
from src.cmds.units import units


command_list = ["send", "show", "get_transaction"]


def help_message():
    print("usage: chia wallet command")
    print(f"command can be any of {command_list}")
    print("")
    print("chia wallet send -f [optional fingerprint] -i [optional wallet_id] -a [amount] -f [fee] -t [target address]")
    print("chia wallet show -f [optional fingerprint] -i [optional wallet_id]")
    print("chia wallet get_transaction -f [optional fingerprint] -i [optional wallet_id] -tx [transaction id]")


def make_parser(parser):
    parser.add_argument(
        "-wp",
        "--wallet-rpc-port",
        help="Set the port where the Wallet is hosting the RPC interface."
        + " See the rpc_port under wallet in config.yaml."
        + "Defaults to 9256",
        type=int,
        default=9256,
    )
    parser.add_argument(
        "-f",
        "--fingerprint",
        help="Set the fingerprint to specify which wallet to use.",
        type=int,
    )
    parser.add_argument("-i", "--id", help="Id of the wallet to use.", type=int, default=1)
    parser.add_argument(
        "-a",
        "--amount",
        help="How much chia to send, in TXCH/XCH",
        type=int,
    )
    parser.add_argument("-m", "--fee", help="Set the fees for the transaction.", type=int, default=0)
    parser.add_argument(
        "-t",
        "--address",
        help="Address to send the TXCH/XCH",
        type=str,
    )
    parser.add_argument(
        "-tx",
        "--tx_id",
        help="transaction id to search for",
        type=str,
    )
    parser.add_argument(
        "command",
        help=f"Command can be any one of {command_list}",
        type=str,
        nargs="?",
    )
    parser.set_defaults(function=handler)
    parser.print_help = lambda self=parser: help_message()


async def get_transaction(args, wallet_client, fingerprint: int):
    if args.id is None:
        print("Please specify a wallet id with -i")
        return
    else:
        wallet_id = args.id
    if args.tx_id is None:
        print("Please specify a transaction id -tx")
        return
    else:
        transaction_id = hexstr_to_bytes(args.tx_id)
    tx = await wallet_client.get_transaction(wallet_id, transaction_id=transaction_id)
    print(tx)


async def send(args, wallet_client, fingerprint: int):
    if args.id is None:
        print("Please specify a wallet id with -i")
        return
    else:
        wallet_id = args.id
    if args.amount is None:
        print("Please specify an amount with -a")
        return
    else:
        amount = args.amount
    if args.amount is None:
        print("Please specify the transaction fees with -m")
        return
    else:
        fee = args.fee
    if args.address is None:
        print("Please specify a target address with -t")
        return
    else:
        address = args.address

    print("Submitting transaction...")
    res = await wallet_client.send_transaction(wallet_id, amount, address, fee)
    tx_id = res.name
    start = time.time()
    while time.time() - start < 10:
        await asyncio.sleep(0.1)
        tx = await wallet_client.get_transaction(wallet_id, tx_id)
        if len(tx.sent_to) > 0:
            print(f"Transaction submitted to nodes: {tx.sent_to}")
            print(f"Do chia wallet get_transaction -f {fingerprint} -tx 0x{tx_id} to get status")
            return

    print("Transaction not yet submitted to nodes.")
    print(f"Do chia wallet get_transaction -f {fingerprint} -tx 0x{tx_id} to get status")


async def print_balances(args, wallet_client, fingerprint: int):
    summaries_response = await wallet_client.get_wallets()
    print(f"Balances, fingerprint: {fingerprint}")
    for summary in summaries_response:
        wallet_id = summary["id"]
        balances = await wallet_client.get_wallet_balance(wallet_id)
        typ = WalletType(int(summary["type"])).name
        if typ != "STANDARD_WALLET":
            print(f"Wallet ID {wallet_id} type {typ} {summary['name']}")
            print(
                f"   -Confirmed: balances['confirmed_wallet_balance']"
                f"{balances['confirmed_wallet_balance']/units['colouredcoin']}"
            )
            print(f"   -Unconfirmed: {balances['unconfirmed_wallet_balance']/units['colouredcoin']}")
            print(f"   -Spendable: {balances['spendable_balance']/units['colouredcoin']}")
            print(f"   -Frozen: {balances['frozen_balance']/units['colouredcoin']}")
            print(f"   -Pending change: {balances['pending_change']/units['colouredcoin']}")
        else:
            print(f"Wallet ID {wallet_id} type {typ}")
            print(
                f"   -Confirmed: {balances['confirmed_wallet_balance']} mojo "
                f"({balances['confirmed_wallet_balance']/units['chia']} TXCH)"
            )
            print(
                f"   -Unconfirmed: {balances['unconfirmed_wallet_balance']} mojo "
                f"({balances['unconfirmed_wallet_balance']/units['chia']} TXCH)"
            )
            print(
                f"   -Spendable: {balances['spendable_balance']} mojo "
                f"({balances['spendable_balance']/units['chia']} TXCH)"
            )
            print(
                f"   -Pending change: {balances['pending_change']} mojo "
                f"({balances['pending_change']/units['chia']} TXCH)"
            )


async def get_wallet(wallet_client, fingerprint=None) -> Optional[Tuple[WalletRpcClient, int]]:
    fingerprints = await wallet_client.get_public_keys()
    if len(fingerprints) == 0:
        print("No keys loaded. Run 'chia keys generate' or import a key.")
        return None
    if fingerprint is not None:
        if fingerprint not in fingerprints:
            print(f"Fingerprint {fingerprint} does not exist")
            return None
    if len(fingerprints) == 1:
        fingerprint = fingerprints[0]
    if fingerprint is not None:
        log_in_response = await wallet_client.log_in(fingerprint)
    else:
        print("Choose wallet key:")
        for i, fp in enumerate(fingerprints):
            print(f"{i+1}) {fp}")
        val = None
        while val is None:
            val = input("Enter a number to pick or q to quit: ")
            if val == "q":
                return None
            if not val.isdigit():
                val = None
            else:
                index = int(val) - 1
                if index >= len(fingerprints):
                    print("Invalid value")
                    val = None
                    continue
                else:
                    fingerprint = fingerprints[index]
        log_in_response = await wallet_client.log_in(fingerprint)
    if log_in_response["success"] is False:
        if log_in_response["error"] == "not_initialized":
            use_cloud = True
            if "backup_path" in log_in_response:
                path = log_in_response["backup_path"]
                print(f"Backup file from backup.chia.net downloaded and written to: {path}")
                val = input("Do you want to use this file to restore from backup? (Y/N) ")
                if val.lower() == "y":
                    log_in_response = await wallet_client.log_in_and_restore(fingerprint, path)
                else:
                    use_cloud = False

            if "backup_path" not in log_in_response or use_cloud is False:
                if use_cloud is True:
                    val = input(
                        "No online backup file found, \n Press S to skip restore from backup"
                        " \n Press F to use your own backup file: "
                    )
                else:
                    val = input(
                        "Cloud backup declined, \n Press S to skip restore from backup"
                        " \n Press F to use your own backup file: "
                    )

                if val.lower() == "s":
                    log_in_response = await wallet_client.log_in_and_skip(fingerprint)
                elif val.lower() == "f":
                    val = input("Please provide the full path to your backup file: ")
                    log_in_response = await wallet_client.log_in_and_restore(fingerprint, val)

    if "success" not in log_in_response or log_in_response["success"] is False:
        if "error" in log_in_response:
            error = log_in_response["error"]
            print(f"Error: {log_in_response[error]}")
        return None
    return wallet_client, fingerprint


async def execute_with_wallet(args, parser, function: Callable):
    if args.fingerprint is None:
        fingerprint = None
    else:
        fingerprint = args.fingerprint

    try:
        config = load_config(DEFAULT_ROOT_PATH, "config.yaml")
        self_hostname = config["self_hostname"]
        if "wallet_rpc_port" not in args or args.wallet_rpc_port is None:
            wallet_rpc_port = config["wallet"]["rpc_port"]
        else:
            wallet_rpc_port = args.wallet_rpc_port
        wallet_client = await WalletRpcClient.create(self_hostname, wallet_rpc_port, DEFAULT_ROOT_PATH, config)
        wallet_client_f = await get_wallet(wallet_client, fingerprint=fingerprint)
        if wallet_client_f is None:
            wallet_client.close()
            await wallet_client.await_closed()
            return
        wallet_client, fingerprint = wallet_client_f
        await function(args, wallet_client, fingerprint)

    except Exception as e:
        if isinstance(e, aiohttp.client_exceptions.ClientConnectorError):
            print(f"Connection error. Check if wallet is running at {args.wallet_rpc_port}")
        else:
            print(f"Exception from 'wallet' {e}")

    wallet_client.close()
    await wallet_client.await_closed()


def handler(args, parser):
    if args.command is None or len(args.command) < 1:
        help_message()
        parser.exit(1)
    command = args.command
    if command not in command_list:
        help_message()
        parser.exit(1)

    if command == "get_transaction":
        return asyncio.run(execute_with_wallet(args, parser, get_transaction))
    if command == "send":
        return asyncio.run(execute_with_wallet(args, parser, send))
    elif command == "show":
        return asyncio.run(execute_with_wallet(args, parser, print_balances))
