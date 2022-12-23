from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Callable, Coroutine, Dict, List, Optional, TypeVar, Union

import click

_T = TypeVar("_T")


FC = TypeVar("FC", bound=Union[Callable[..., Any], click.Command])

logger = logging.getLogger(__name__)


# TODO: this is more general and should be part of refactoring the overall CLI code duplication
def run(coro: Coroutine[Any, Any, Optional[Dict[str, Any]]]) -> None:
    import asyncio

    response = asyncio.run(coro)

    success = response is not None and response.get("success", False)
    logger.info(f"data layer cli call response:{success}")
    # todo make sure all cli methods follow this pattern, uncomment
    # if not success:
    # raise click.ClickException(message=f"query unsuccessful, response: {response}")


@click.group("custody", short_help="Manage your custody")
def custody_cmd() -> None:
    pass

@custody_cmd.command("init", short_help="Create a configuration file for the prefarm")
@click.option(
    "-cp",
    "--custody-rpc-port",
    help="Set the port where Custody is hosting the RPC interface. See the rpc_port under custody in config.yaml",
    type=int,
    default=None,
    show_default=True,
)
@click.option(
    "-d",
    "--directory",
    help="The directory in which to create the configuration file",
    default=".",
    show_default=True,
)
@click.option(
    "-wt",
    "--withdrawal-timelock",
    help="The amount of time where nothing has happened before a withdrawal can be made (in seconds)",
    required=True,
)
@click.option(
    "-pc",
    "--payment-clawback",
    help="The amount of time to clawback a payment before it's completed (in seconds)",
    required=True,
)
@click.option(
    "-rc",
    "--rekey-cancel",
    help="The amount of time to cancel a rekey before it's completed (in seconds)",
    required=True,
)
@click.option(
    "-rt",
    "--rekey-timelock",
    help="The amount of time where nothing has happened before a standard rekey can be initiated (in seconds)",
    required=True,
)
@click.option("-sp", "--slow-penalty", help="The time penalty for performing a slow rekey (in seconds)", required=True)
def init_cmd(
    custody_rpc_port: Optional[int],
    directory: str,
    withdrawal_timelock: int,
    payment_clawback: int,
    rekey_cancel: int,
    rekey_timelock: int,
    slow_penalty: int,
) -> None:
    from chia.cmds.custody_funcs import init_cmd

    run(init_cmd(custody_rpc_port, directory, withdrawal_timelock, payment_clawback, rekey_cancel, rekey_timelock, slow_penalty))
    

@custody_cmd.command("derive_root", short_help="Take an existing configuration and pubkey set to derive a puzzle root")
@click.option(
    "-cp",
    "--custody-rpc-port",
    help="Set the port where Custody is hosting the RPC interface. See the rpc_port under custody in config.yaml",
    type=int,
    default=None,
    show_default=True,
)
@click.option(
    "-c",
    "--configuration",
    help="The configuration file with which to derive the root (or the filepath to create it at if using --db-path)",
    default="./Configuration (needs derivation).txt",
    show_default=True,
)
@click.option(
    "-db",
    "--db-path",
    help="Optionally specify a DB path to find the configuration from",
    default=None,
)
@click.option(
    "-pks", "--pubkeys", help="A comma separated list of pubkey files that will control this money", required=True
)
@click.option(
    "-m",
    "--initial-lock-level",
    help="The initial number of pubkeys required to do a withdrawal or standard rekey",
    required=True,
)
@click.option(
    "-n",
    "--maximum-lock-level",
    help="The maximum number of pubkeys required to do a withdrawal or standard rekey",
    required=False,
)
@click.option(
    "-min",
    "--minimum-pks",
    help="The minimum number of pubkeys required to initiate a slow rekey",
    default=1,
    show_default=True,
)
@click.option(
    "-va",
    "--validate-against",
    help="Specify a configuration file to check whether it matches the specified parameters",
    default=None,
)
def derive_cmd(
    custody_rpc_port: Optional[int],
    configuration: str,
    db_path: Optional[str],
    pubkeys: str,
    initial_lock_level: int,
    minimum_pks: int,
    validate_against: Optional[str],
    maximum_lock_level: Optional[int] = None,
):
    from chia.cmds.custody_funcs import derive_cmd

    run(derive_cmd(custody_rpc_port, configuration, db_path, pubkeys, initial_lock_level, minimum_pks, validate_against, maximum_lock_level))


@custody_cmd.command("launch_singleton", short_help="Use 1 mojo to launch the singleton that will control the funds")
@click.option(
    "-cp",
    "--custody-rpc-port",
    help="Set the port where Custody is hosting the RPC interface. See the rpc_port under custody in config.yaml",
    type=int,
    default=None,
    show_default=True,
)
@click.option(
    "-c",
    "--configuration",
    help="The configuration file with which to launch the singleton",
    default="./Configuration (awaiting launch).txt",
    required=True,
)
@click.option(
    "-db",
    "--db-path",
    help="The file path to initialize the sync database at",
    default="./",
    required=True,
)
@click.option(
    "-wp",
    "--wallet-rpc-port",
    help="Set the port where the Wallet is hosting the RPC interface. See the rpc_port under wallet in config.yaml",
    type=int,
    default=None,
)
@click.option("-f", "--fingerprint", help="Set the fingerprint to specify which wallet to use", type=int, default=None)
@click.option(
    "-np",
    "--node-rpc-port",
    help="Set the port where the Node is hosting the RPC interface. See the rpc_port under full_node in config.yaml",
    type=int,
    default=None,
)
@click.option("--fee", help="Fee to use for the launch transaction (in mojos)", default=0)
def launch_cmd(
    custody_rpc_port: Optional[int],
    configuration: str,
    db_path: str,
    wallet_rpc_port: Optional[int],
    fingerprint: Optional[int],
    node_rpc_port: Optional[int],
    fee: int,
):
    from chia.cmds.custody_funcs import launch_cmd

    run(launch_cmd(custody_rpc_port, configuration, db_path, wallet_rpc_port, fingerprint, node_rpc_port, fee))


   

@custody_cmd.command("update_config", short_help="Update an outdated config in a sync DB with a new config")
@click.option(
    "-cp",
    "--custody-rpc-port",
    help="Set the port where Custody is hosting the RPC interface. See the rpc_port under custody in config.yaml",
    type=int,
    default=None,
    show_default=True,
)
@click.option(
    "-c",
    "--configuration",
    help="The configuration file update the sync database with (default: ./Configuration (******).txt)",
    default=None,
)
@click.option(
    "-db",
    "--db-path",
    help="The file path to find the sync database at (default: ./sync (******).sqlite)",
    default="./",
    required=True,
)
def update_cmd(
    custody_rpc_port: Optional[int],
    configuration: Optional[str],
    db_path: str,
):
    from chia.cmds.custody_funcs import update_cmd

    run(update_cmd(custody_rpc_port, configuration, db_path))


@custody_cmd.command("export_config", short_help="Export a copy of the current DB's config")
@click.option(
    "-cp",
    "--custody-rpc-port",
    help="Set the port where Custody is hosting the RPC interface. See the rpc_port under custody in config.yaml",
    type=int,
    default=None,
    show_default=True,
)
@click.option(
    "-f",
    "--filename",
    help="The file path to export the config to (default: ./Configuration Export (******).sqlite)",
    default=None,
)
@click.option(
    "-db",
    "--db-path",
    help="The file path to initialize/find the sync database at (default: ./sync (******).sqlite)",
    default="./",
    required=True,
)
@click.option(
    "-p",
    "--public",
    help="Export the public information only",
    is_flag=True,
)
def export_cmd(
    custody_rpc_port: Optional[int],
    filename: Optional[str],
    db_path: str,
    public: bool,
):
    from chia.cmds.custody_funcs import export_cmd

    run(export_cmd(custody_rpc_port, filename, db_path, public))


@custody_cmd.command("sync", short_help="Sync a singleton from an existing configuration")
@click.option(
    "-cp",
    "--custody-rpc-port",
    help="Set the port where Custody is hosting the RPC interface. See the rpc_port under custody in config.yaml",
    type=int,
    default=None,
    show_default=True,
)
@click.option(
    "-c",
    "--configuration",
    help="The configuration file with which to initialize a sync database (default: ./Configuration (******).txt)",
    default=None,
)
@click.option(
    "-db",
    "--db-path",
    help="The file path to initialize/find the sync database at (default: ./sync (******).sqlite)",
    default="./",
    required=True,
)
@click.option(
    "-np",
    "--node-rpc-port",
    help="Set the port where the Node is hosting the RPC interface. See the rpc_port under full_node in config.yaml",
    type=int,
    default=None,
)
@click.option(
    "-s",
    "--show",
    help="Show a summary of the singleton after sync is complete",
    is_flag=True,
)
def sync_cmd(
    custody_rpc_port: Optional[int],
    configuration: Optional[str],
    db_path: str,
    node_rpc_port: Optional[int],
    show: bool,
):
    from chia.cmds.custody_funcs import sync_cmd

    run(sync_cmd(custody_rpc_port, configuration, db_path, node_rpc_port, show))



@custody_cmd.command("p2_address", short_help="Print the address to pay to the singleton")
@click.option(
    "-cp",
    "--custody-rpc-port",
    help="Set the port where Custody is hosting the RPC interface. See the rpc_port under custody in config.yaml",
    type=int,
    default=None,
    show_default=True,
)
@click.option(
    "-db",
    "--db-path",
    help="The file path to the sync DB (default: ./sync (******).sqlite)",
    default="./",
    required=True,
)
@click.option(
    "-p",
    "--prefix",
    help="The prefix to use when encoding the address",
    default="xch",
    show_default=True,
)
def address_cmd(custody_rpc_port: Optional[int],
    db_path: str,
    prefix: str):
    from chia.cmds.custody_funcs import address_cmd

    run(address_cmd(custody_rpc_port, db_path, prefix))


@custody_cmd.command("push_tx", short_help="Push a signed spend bundle to the network")
@click.option(
    "-cp",
    "--custody-rpc-port",
    help="Set the port where Custody is hosting the RPC interface. See the rpc_port under custody in config.yaml",
    type=int,
    default=None,
    show_default=True,
)
@click.option(
    "-b",
    "--spend-bundle",
    help="The signed spend bundle",
    required=True,
)
@click.option(
    "-wp",
    "--wallet-rpc-port",
    help="Set the port where the Wallet is hosting the RPC interface. See the rpc_port under wallet in config.yaml",
    type=int,
    default=None,
)
@click.option("-f", "--fingerprint", help="Set the fingerprint to specify which wallet to use", type=int, default=None)
@click.option(
    "-np",
    "--node-rpc-port",
    help="Set the port where the Node is hosting the RPC interface. See the rpc_port under full_node in config.yaml",
    type=int,
    default=None,
)
@click.option(
    "-m",
    "--fee",
    help="The fee to attach to this spend (in mojos)",
    type=int,
    default=0,
)
def push_cmd(
    custody_rpc_port: Optional[int],
    spend_bundle: str,
    wallet_rpc_port: Optional[int],
    fingerprint: Optional[int],
    node_rpc_port: Optional[int],
    fee: int,
):
    from chia.cmds.custody_funcs import push_cmd

    run(push_cmd(custody_rpc_port, spend_bundle, wallet_rpc_port, fingerprint, node_rpc_port, fee))


@custody_cmd.command("payment", short_help="Absorb/Withdraw money into/from the singleton")
@click.option(
    "-cp",
    "--custody-rpc-port",
    help="Set the port where Custody is hosting the RPC interface. See the rpc_port under custody in config.yaml",
    type=int,
    default=None,
    show_default=True,
)
@click.option(
    "-db",
    "--db-path",
    help="The file path to the sync DB (default: ./sync (******).sqlite)",
    default="./",
    required=True,
)
@click.option(
    "-f",
    "--filename",
    help="The filepath to dump the spend bundle into",
    default=None,
)
@click.option(
    "-pks",
    "--pubkeys",
    help="A comma separated list of pubkeys that will be signing this spend.",
    required=True,
)
@click.option(
    "-a",
    "--amount",
    help="The outgoing amount (in mojos) to pay",
    default=0,
    show_default=True,
)
@click.option(
    "-t",
    "--recipient-address",
    help="The address that can claim the money after the clawback period is over (must be supplied if amount is > 0)",
    required=True,
)
@click.option(
    "-ap",
    "--absorb-available-payments",
    help="Look for any outstanding payments to the singleton and claim them while doing this spend (adds tx cost)",
    is_flag=True,
)
@click.option(
    "-mc",
    "--maximum-extra-cost",
    help="The maximum extra tx cost to be taken on while absorbing payments (as an estimated percentage)",
    default=50,
    show_default=True,
)
@click.option(
    "-at",
    "--amount-threshold",
    help="The minimum amount required of a payment in order for it to be absorbed",
    default=1000000000000,
    show_default=True,
)
def payments_cmd(
    custody_rpc_port: Optional[int],
    db_path: str,
    pubkeys: str,
    amount: int,
    recipient_address: str,
    absorb_available_payments: bool,
    maximum_extra_cost: Optional[int],
    amount_threshold: int,
    filename: Optional[str],
):
    from chia.cmds.custody_funcs import payments_cmd

    run(payments_cmd(custody_rpc_port, db_path, pubkeys, amount, recipient_address, absorb_available_payments, maximum_extra_cost, amount_threshold, filename))

@custody_cmd.command("start_rekey", short_help="Rekey the singleton to a new set of keys/options")
@click.option(
    "-cp",
    "--custody-rpc-port",
    help="Set the port where Custody is hosting the RPC interface. See the rpc_port under custody in config.yaml",
    type=int,
    default=None,
    show_default=True,
)
@click.option(
    "-db",
    "--db-path",
    help="The file path to the sync DB (default: ./sync (******).sqlite)",
    default="./",
    required=True,
)
@click.option(
    "-f",
    "--filename",
    help="The filepath to dump the spend bundle into",
    default=None,
)
@click.option(
    "-pks",
    "--pubkeys",
    help="A comma separated list of pubkeys that will be signing this spend.",
    required=True,
)
@click.option(
    "-new",
    "--new-configuration",
    help="The configuration you would like to rekey the singleton to",
    required=True,
)
def start_rekey_cmd(
    custody_rpc_port: Optional[int],
    db_path: str,
    pubkeys: str,
    new_configuration: str,
    filename: Optional[str],
):
    from chia.cmds.custody_funcs import start_rekey_cmd

    run(start_rekey_cmd(custody_rpc_port, db_path, pubkeys, new_configuration, filename))


@custody_cmd.command("clawback", short_help="Clawback a withdrawal or rekey attempt (will be prompted which one)")
@click.option(
    "-cp",
    "--custody-rpc-port",
    help="Set the port where Custody is hosting the RPC interface. See the rpc_port under custody in config.yaml",
    type=int,
    default=None,
    show_default=True,
)
@click.option(
    "-db",
    "--db-path",
    help="The file path to the sync DB (default: ./sync (******).sqlite)",
    default="./",
    required=True,
)
@click.option(
    "-f",
    "--filename",
    help="The filepath to dump the spend bundle into",
    default=None,
)
@click.option(
    "-pks",
    "--pubkeys",
    help="A comma separated list of pubkeys that will be signing this spend.",
    required=True,
)
def clawback_cmd(
    custody_rpc_port: Optional[int],
    db_path: str,
    pubkeys: str,
    filename: Optional[str],
):
    from chia.cmds.custody_funcs import clawback_cmd

    run(clawback_cmd(custody_rpc_port, db_path, pubkeys, filename))


@custody_cmd.command("complete", short_help="Complete a withdrawal or rekey attempt (will be prompted which one)")
@click.option(
    "-cp",
    "--custody-rpc-port",
    help="Set the port where Custody is hosting the RPC interface. See the rpc_port under custody in config.yaml",
    type=int,
    default=None,
    show_default=True,
)
@click.option(
    "-db",
    "--db-path",
    help="The file path to the sync DB (default: ./sync (******).sqlite)",
    default="./",
    required=True,
)
@click.option(
    "-f",
    "--filename",
    help="The filepath to dump the spend bundle into",
    default=None,
)
def complete_cmd(
    custody_rpc_port: Optional[int],
    db_path: str,
    filename: Optional[str],
):
    from chia.cmds.custody_funcs import complete_cmd

    run(complete_cmd(custody_rpc_port, db_path, filename))


@custody_cmd.command("increase_security_level", short_help="Initiate an increase of the number of keys required for withdrawal")
@click.option(
    "-cp",
    "--custody-rpc-port",
    help="Set the port where Custody is hosting the RPC interface. See the rpc_port under custody in config.yaml",
    type=int,
    default=None,
    show_default=True,
)
@click.option(
    "-db",
    "--db-path",
    help="The file path to the sync DB (default: ./sync (******).sqlite)",
    default="./",
    required=True,
)
@click.option(
    "-pks",
    "--pubkeys",
    help="A comma separated list of pubkeys that will be signing this spend.",
    required=True,
)
@click.option(
    "-f",
    "--filename",
    help="The filepath to dump the spend bundle into",
    default=None,
)
def increase_cmd(
    custody_rpc_port: Optional[int],
    db_path: str,
    pubkeys: str,
    filename: Optional[str],
):
    from chia.cmds.custody_funcs import increase_cmd

    run(increase_cmd(custody_rpc_port, db_path, pubkeys, filename))


@custody_cmd.command("show", short_help="Show the status of the singleton, payments, and rekeys")
@click.option(
    "-cp",
    "--custody-rpc-port",
    help="Set the port where Custody is hosting the RPC interface. See the rpc_port under custody in config.yaml",
    type=int,
    default=None,
    show_default=True,
)
@click.option(
    "-db",
    "--db-path",
    help="The file path to the sync DB (default: ./sync (******).sqlite)",
    default="./",
    required=True,
)
@click.option(
    "-c",
    "--config",
    help="Display the details of the public config",
    is_flag=True,
)
@click.option(
    "-d",
    "--derivation",
    help="Display the private details of the private config",
    is_flag=True,
)
def show_cmd(
    custody_rpc_port: Optional[int],
    db_path: str,
    config: bool,
    derivation: bool,
):
    from chia.cmds.custody_funcs import show_cmd

    run(show_cmd(custody_rpc_port, db_path, config, derivation))



@custody_cmd.command("audit", short_help="Export a history of the singleton to a CSV")
@click.option(
    "-cp",
    "--custody-rpc-port",
    help="Set the port where Custody is hosting the RPC interface. See the rpc_port under custody in config.yaml",
    type=int,
    default=None,
    show_default=True,
)
@click.option(
    "-db",
    "--db-path",
    help="The file path to the sync DB (default: ./sync (******).sqlite)",
    default="./",
    required=True,
)
@click.option(
    "-f",
    "--filepath",
    help="The file path the dump the audit log",
    required=False,
)
@click.option(
    "-d",
    "--diff",
    help="A previous audit log to diff against this one",
    required=False,
)
def audit_cmd(
    custody_rpc_port: Optional[int],
    db_path: str,
    filepath: Optional[str],
    diff: Optional[str],
):
    from chia.cmds.custody_funcs import audit_cmd

    run(audit_cmd(custody_rpc_port, db_path, filepath, diff))


@custody_cmd.command("examine_spend", short_help="Examine an unsigned spend to see the details before you sign it")
@click.option(
    "-cp",
    "--custody-rpc-port",
    help="Set the port where Custody is hosting the RPC interface. See the rpc_port under custody in config.yaml",
    type=int,
    default=None,
    show_default=True,
)
@click.argument("spend_file", nargs=1, required=True)
@click.option(
    "--qr-density", help="The amount of bytes to pack into a single QR code", default=250, show_default=True, type=int
)
@click.option(
    "-va",
    "--validate-against",
    help="A new configuration file to check against requests for rekeys",
    required=False,
    default=None,
)
def examine_cmd(
    custody_rpc_port: Optional[int],
    spend_file: str,
    qr_density: int,
    validate_against: str,
):
    from chia.cmds.custody_funcs import examine_cmd

    run(examine_cmd(custody_rpc_port, spend_file, qr_density, validate_against))


@custody_cmd.command("which_pubkeys", short_help="Determine which pubkeys make up an aggregate pubkey")
@click.option(
    "-cp",
    "--custody-rpc-port",
    help="Set the port where Custody is hosting the RPC interface. See the rpc_port under custody in config.yaml",
    type=int,
    default=None,
    show_default=True,
)
@click.argument("aggregate_pubkey", nargs=1, required=True)
@click.option(
    "-pks",
    "--pubkeys",
    help="A comma separated list of pubkey files that may be in the aggregate",
    required=True,
)
@click.option(
    "-m",
    "--num-pubkeys",
    help="Check only combinations of a specific number of pubkeys",
    type=int,
    required=False,
)
@click.option(
    "--no-offset",
    help="Do not try the synthetic versions of the pubkeys",
    is_flag=True,
)
def which_pubkeys_cmd(
    custody_rpc_port: Optional[int],
    aggregate_pubkey: str,
    pubkeys: str,
    num_pubkeys: Optional[int],
    no_offset: bool,
):
    from chia.cmds.custody_funcs import which_pubkeys_cmd

    run(which_pubkeys_cmd(custody_rpc_port, aggregate_pubkey, pubkeys, num_pubkeys, no_offset))


@custody_cmd.command("hsmgen", short_help="Generate key")
@click.option(
    "-cp",
    "--custody-rpc-port",
    help="Set the port where Custody is hosting the RPC interface. See the rpc_port under custody in config.yaml",
    type=int,
    default=None,
    show_default=True,
)
def hsmgen_cmd(
    custody_rpc_port: Optional[int],
) -> None:
    from chia.cmds.custody_funcs import hsmgen_cmd

    run(hsmgen_cmd(custody_rpc_port))
    
@custody_cmd.command("hsmpk", short_help="Get public key")
@click.option(
    "-cp",
    "--custody-rpc-port",
    help="Set the port where Custody is hosting the RPC interface. See the rpc_port under custody in config.yaml",
    type=int,
    default=None,
    show_default=True,
)
@click.option(
    "-s",
    "--secretkey",
    help="Secret key to be used to return public key",
    type=str,
    required=True,
)
def hsmpk_cmd(
    custody_rpc_port: Optional[int],
    secretkey: str,
) -> None:
    from chia.cmds.custody_funcs import hsmpk_cmd

    run(hsmpk_cmd(custody_rpc_port, secretkey))
 

@custody_cmd.command("hsms", short_help="Sign message")
@click.option(
    "-cp",
    "--custody-rpc-port",
    help="Set the port where Custody is hosting the RPC interface. See the rpc_port under custody in config.yaml",
    type=int,
    default=None,
    show_default=True,
)
@click.option(
    "-m",
    "--message",
    help="Message to be signed",
    type=str,
    required=True,
)
@click.option(
    "-s",
    "--secretkey",
    help="Secret key to be used for signing",
    type=str,
    required=True,
)
def hsms_cmd(
    custody_rpc_port: Optional[int],
    message:str,
    secretkey: str,
) -> None:
    from chia.cmds.custody_funcs import hsms_cmd

    run(hsms_cmd(custody_rpc_port, message, secretkey))
 


@custody_cmd.command("hsmmerge", short_help="Merge bundle with signatures")
@click.option(
    "-cp",
    "--custody-rpc-port",
    help="Set the port where Custody is hosting the RPC interface. See the rpc_port under custody in config.yaml",
    type=int,
    default=None,
    show_default=True,
)
@click.option(
    "-b",
    "--bundle",
    help="Bundle to be merged",
    type=str,
    required=True,
)
@click.option(
    "-s", "--sigs", help="A comma separated list of sig files to be merged", required=True
)
def hsmmerge_cmd(
    custody_rpc_port: Optional[int],
    bundle: str,
    sigs: str
) -> None:
    from chia.cmds.custody_funcs import hsmmerge_cmd

    run(hsmmerge_cmd(custody_rpc_port, bundle, sigs))
 



