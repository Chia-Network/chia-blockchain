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
    db_path: str,
    pubkeys: str,
    new_configuration: str,
    filename: Optional[str],
):
    async def do_command():
        sync_store: SyncStore = await load_db(db_path)

        try:
            derivation = await sync_store.get_configuration(False, block_outdated=True)
            new_derivation: RootDerivation = load_root_derivation(new_configuration)

            # Quick sanity check that everything except the puzzle root is the same
            if not derivation.prefarm_info.is_valid_update(new_derivation.prefarm_info):
                raise ValueError(
                    "This configuration has more changed than the keys."
                    "Please derive a configuration with the same values for everything except key-related info."
                )

            # Collect some relevant information
            current_singleton: Optional[SingletonRecord] = await sync_store.get_latest_singleton()
            if current_singleton is None:
                raise RuntimeError("No singleton is found for this configuration.  Try `cic sync` then try again.")
            pubkey_list: List[G1Element] = list(load_pubkeys(pubkeys))
            fee_conditions: List[Program] = [Program.to([60, b""])]

            # Get the spend bundle
            singleton_bundle, data_to_sign = get_rekey_spend_info(
                current_singleton.coin,
                pubkey_list,
                derivation,
                current_singleton.lineage_proof,
                new_derivation,
                fee_conditions,
            )

            # Cast everything into HSM types
            as_bls_pubkey_list = [BLSPublicKey(pk) for pk in pubkey_list]
            agg_pk = sum(as_bls_pubkey_list, start=BLSPublicKey.zero())
            synth_sk = BLSSecretExponent(
                PrivateKey.from_bytes(
                    calculate_synthetic_offset(agg_pk, DEFAULT_HIDDEN_PUZZLE_HASH).to_bytes(32, "big")
                )
            )
            coin_spends = [
                HSMCoinSpend(cs.coin, cs.puzzle_reveal.to_program(), cs.solution.to_program())
                for cs in singleton_bundle.coin_spends
            ]
            unsigned_spend = UnsignedSpend(
                coin_spends,
                [SumHint(as_bls_pubkey_list, synth_sk)],
                [],
                get_additional_data(),
            )

            # Print the result
            if filename is not None:
                write_unsigned_spend(filename, unsigned_spend)
                print(f"Successfully wrote spend to {filename}")
            else:
                for chunk in unsigned_spend.chunk(255):
                    print(str(b2a_qrint(chunk)))
        finally:
            await sync_store.db_connection.close()

    asyncio.get_event_loop().run_until_complete(do_command())


@custody_cmd.command("clawback", short_help="Clawback a withdrawal or rekey attempt (will be prompted which one)")
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
    db_path: str,
    pubkeys: str,
    filename: Optional[str],
):
    async def do_command():
        sync_store: SyncStore = await load_db(db_path)

        try:
            derivation = await sync_store.get_configuration(False, block_outdated=True)

            achs: List[ACHRecord] = await sync_store.get_ach_records(include_completed_coins=False)
            rekeys: List[RekeyRecord] = await sync_store.get_rekey_records(include_completed_coins=False)

            # Prompt the user for the action to cancel
            if len(achs) == 0 and len(rekeys) == 0:
                print("No actions outstanding")
                return
            print("Which actions would you like to cancel?:")
            print()
            index: int = 1
            selectable_records: Dict[int, Union[ACHRecord, RekeyRecord]] = {}
            for ach in achs:
                print(f"{index}) PAYMENT to {encode_puzzle_hash(ach.p2_ph, 'xch')} of amount {ach.coin.amount}")
                selectable_records[index] = ach
                index += 1
            for rekey in rekeys:
                print(f"{index}) REKEY from {rekey.from_root} to {rekey.to_root}")
                selectable_records[index] = rekey
                index += 1
            selected_action = int(input("(Enter index of action to cancel): "))
            if selected_action not in range(1, index):
                print("Invalid index specified.")
                return

            # Construct the spend for the selected index
            pubkey_list: List[G1Element] = list(load_pubkeys(pubkeys))
            fee_conditions: List[Program] = [Program.to([60, b""])]
            record = selectable_records[selected_action]
            if isinstance(record, ACHRecord):
                # Validate we have enough keys
                if len(pubkey_list) != derivation.required_pubkeys:
                    print("Incorrect number of keys to claw back selected payment")
                    return

                # Get the spend bundle
                clawback_bundle, data_to_sign = get_ach_clawback_spend_info(
                    record.coin,
                    pubkey_list,
                    derivation,
                    record.p2_ph,
                    fee_conditions,
                )
            else:
                # Validate we have enough keys
                timelock: uint64 = record.timelock
                required_pubkeys: Optional[int] = None
                if timelock == uint8(1):
                    required_pubkeys = derivation.required_pubkeys
                else:
                    for i in range(derivation.minimum_pubkeys, derivation.required_pubkeys):
                        if timelock == uint8(1 + derivation.required_pubkeys - i):
                            required_pubkeys = i
                            break
                if required_pubkeys is None or len(pubkey_list) != required_pubkeys:
                    print("Incorrect number of keys to claw back selected rekey")
                    return

                # Get the spend bundle
                clawback_bundle, data_to_sign = get_rekey_clawback_spend_info(
                    record.coin,
                    pubkey_list,
                    derivation,
                    record.timelock,
                    dataclasses.replace(
                        derivation,
                        prefarm_info=dataclasses.replace(derivation.prefarm_info, puzzle_root=record.to_root),
                    ),
                    fee_conditions,
                )

            as_bls_pubkey_list = [BLSPublicKey(pk) for pk in pubkey_list]
            agg_pk = sum(as_bls_pubkey_list, start=BLSPublicKey.zero())
            synth_sk = BLSSecretExponent(
                PrivateKey.from_bytes(
                    calculate_synthetic_offset(agg_pk, DEFAULT_HIDDEN_PUZZLE_HASH).to_bytes(32, "big")
                )
            )
            coin_spends = [
                HSMCoinSpend(cs.coin, cs.puzzle_reveal.to_program(), cs.solution.to_program())
                for cs in clawback_bundle.coin_spends
            ]
            unsigned_spend = UnsignedSpend(
                coin_spends,
                [SumHint(as_bls_pubkey_list, synth_sk)],
                [],
                get_additional_data(),
            )

            if filename is not None:
                write_unsigned_spend(filename, unsigned_spend)
                print(f"Successfully wrote spend to {filename}")
            else:
                for chunk in unsigned_spend.chunk(255):
                    print(str(b2a_qrint(chunk)))
        finally:
            await sync_store.db_connection.close()

    asyncio.get_event_loop().run_until_complete(do_command())


@custody_cmd.command("complete", short_help="Complete a withdrawal or rekey attempt (will be prompted which one)")
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
    db_path: str,
    filename: Optional[str],
):
    async def do_command():
        sync_store: SyncStore = await load_db(db_path)

        try:
            derivation = await sync_store.get_configuration(False, block_outdated=True)

            achs: List[ACHRecord] = await sync_store.get_ach_records(include_completed_coins=False)
            rekeys: List[RekeyRecord] = await sync_store.get_rekey_records(include_completed_coins=False)

            # Prompt the user for the action to complete
            if len(achs) == 0 and len(rekeys) == 0:
                print("No actions outstanding")
                return
            print("Which actions would you like to complete?:")
            print()
            index: int = 1
            selectable_records: Dict[int, Union[ACHRecord, RekeyRecord]] = {}
            for ach in achs:
                if ach.confirmed_at_time + derivation.prefarm_info.payment_clawback_period < time.time():
                    prefix = f"{index})"
                    selectable_records[index] = ach
                    index += 1
                else:
                    prefix = "-)"
                print(f"{prefix} PAYMENT to {encode_puzzle_hash(ach.p2_ph, 'xch')} of amount {ach.coin.amount}")

            for rekey in rekeys:
                if rekey.confirmed_at_time + derivation.prefarm_info.rekey_clawback_period < time.time():
                    prefix = f"{index})"
                    selectable_records[index] = rekey
                    index += 1
                else:
                    prefix = "-)"
                print(f"{prefix} REKEY from {rekey.from_root} to {rekey.to_root}")
            if index == 1:
                print("No actions can be completed at this time.")
                return
            selected_action = int(input("(Enter index of action to complete): "))
            if selected_action not in range(1, index):
                print("Invalid index specified.")
                return

            # Construct the spend for the selected index
            record = selectable_records[selected_action]
            if isinstance(record, ACHRecord):
                # Get the spend bundle
                completion_bundle = get_ach_clawforward_spend_bundle(
                    record.coin,
                    dataclasses.replace(
                        derivation,
                        prefarm_info=dataclasses.replace(derivation.prefarm_info, puzzle_root=record.from_root),
                    ),
                    record.p2_ph,
                )
            else:
                current_singleton: Optional[SingletonRecord] = await sync_store.get_latest_singleton()
                if current_singleton is None:
                    raise RuntimeError("No singleton is found for this configuration.  Try `cic sync` then try again.")
                parent_singleton: Optional[SingletonRecord] = await sync_store.get_singleton_record(
                    record.coin.parent_coin_info
                )
                if parent_singleton is None:
                    raise RuntimeError("Bad sync information. Please try a resync.")

                num_pubkeys: int = derivation.required_pubkeys - (record.timelock - 1)

                # Get the spend bundle
                completion_bundle = get_rekey_completion_spend(
                    current_singleton.coin,
                    record.coin,
                    derivation.pubkey_list[0:num_pubkeys],
                    derivation,
                    current_singleton.lineage_proof,
                    LineageProof(
                        parent_singleton.coin.parent_coin_info,
                        construct_singleton_inner_puzzle(derivation.prefarm_info).get_tree_hash(),
                        parent_singleton.coin.amount,
                    ),
                    dataclasses.replace(
                        derivation,
                        prefarm_info=dataclasses.replace(derivation.prefarm_info, puzzle_root=record.to_root),
                    ),
                )

            if filename is not None:
                with open(filename, "w") as file:
                    file.write(bytes(completion_bundle).hex())
                print(f"Successfully wrote spend to {filename}")
            else:
                print(bytes(completion_bundle).hex())
        finally:
            await sync_store.db_connection.close()

    asyncio.get_event_loop().run_until_complete(do_command())


@custody_cmd.command("increase_security_level", short_help="Initiate an increase of the number of keys required for withdrawal")
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
    db_path: str,
    pubkeys: str,
    filename: Optional[str],
):
    async def do_command():
        sync_store: SyncStore = await load_db(db_path)
        try:
            derivation = await sync_store.get_configuration(False, block_outdated=True)

            current_singleton: Optional[SingletonRecord] = await sync_store.get_latest_singleton()
            if current_singleton is None:
                raise RuntimeError("No singleton is found for this configuration.  Try `cic sync` then try again.")
            pubkey_list: List[G1Element] = list(load_pubkeys(pubkeys))
            fee_conditions: List[Program] = [Program.to([60, b""])]

            # Validate we have enough pubkeys
            if len(pubkey_list) < derivation.required_pubkeys + 1:
                print("Not enough keys to increase the security level")
                return

            # Create the spend
            lock_bundle, data_to_sign = get_rekey_spend_info(
                current_singleton.coin,
                pubkey_list,
                derivation,
                current_singleton.lineage_proof,
                additional_conditions=fee_conditions,
            )

            as_bls_pubkey_list = [BLSPublicKey(pk) for pk in pubkey_list]
            coin_spends = [
                HSMCoinSpend(cs.coin, cs.puzzle_reveal.to_program(), cs.solution.to_program())
                for cs in lock_bundle.coin_spends
            ]
            unsigned_spend = UnsignedSpend(
                coin_spends,
                [SumHint(as_bls_pubkey_list, BLSSecretExponent.zero())],
                [],
                get_additional_data(),
            )

            if filename is not None:
                write_unsigned_spend(filename, unsigned_spend)
                print(f"Successfully wrote spend to {filename}")
            else:
                for chunk in unsigned_spend.chunk(255):
                    print(str(b2a_qrint(chunk)))
        finally:
            await sync_store.db_connection.close()

    asyncio.get_event_loop().run_until_complete(do_command())


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
    db_path: str,
    filepath: Optional[str],
    diff: Optional[str],
):
    if diff is not None:
        with open(diff, "r") as file:
            old_dict = json.load(file)

    async def do_command():
        sync_store: SyncStore = await load_db(db_path)
        try:
            singletons: List[SingletonRecord] = await sync_store.get_all_singletons()
            achs: List[ACHRecord] = await sync_store.get_ach_records(include_completed_coins=True)
            rekeys: List[RekeyRecord] = await sync_store.get_rekey_records(include_completed_coins=True)

            # Make dictionaries for easy lookup of coins from the singleton that created them
            singleton_parent_dict: Dict[bytes32, SingletonRecord] = {}
            singleton_dict: Dict[bytes32, SingletonRecord] = {}
            for singleton in singletons:
                singleton_parent_dict[singleton.coin.parent_coin_info] = singleton
                singleton_dict[singleton.coin.name()] = singleton
            ach_dict: Dict[bytes32, ACHRecord] = {}
            for ach in achs:
                ach_dict[ach.coin.parent_coin_info] = ach
            rekey_dict: Dict[bytes32, RekeyRecord] = {}
            for rekey in rekeys:
                rekey_dict[rekey.coin.parent_coin_info] = rekey

            audit_dict: List[Dict[str, Union[str, Dict[str, Union[str, int, bool]]]]] = []
            for singleton in singletons:
                coin_id = singleton.coin.name()
                if singleton.spend_type is None:
                    continue
                if singleton.spend_type == SpendType.HANDLE_PAYMENT:
                    params: Dict[str, Union[str, int, bool]] = {}
                    out_amount, in_amount, p2_ph = get_spend_params_for_ach_creation(singleton.solution.to_program())
                    if out_amount > 0:
                        params["out_amount"] = out_amount
                        params["recipient_ph"] = p2_ph.hex()
                    if in_amount > 0:
                        params["in_amount"] = in_amount
                    if coin_id in ach_dict:
                        ach_record: ACHRecord = ach_dict[coin_id]
                        if ach_record.completed is not None:
                            params["completed"] = ach_record.completed
                            params["spent_at_height"] = ach_record.spent_at_height
                            if not ach_record.completed and ach_record.clawback_pubkey is not None:
                                params["clawback_pubkey"] = BLSPublicKey(ach_record.clawback_pubkey).as_bech32m()
                elif singleton.spend_type == SpendType.START_REKEY:
                    params = {}
                    timelock, new_root = get_spend_params_for_rekey_creation(singleton.solution.to_program())
                    rekey_record: RekeyRecord = rekey_dict[coin_id]
                    params["from_root"] = rekey_record.from_root.hex()
                    params["to_root"] = rekey_record.to_root.hex()
                    if rekey_record.completed is not None:
                        params["completed"] = rekey_record.completed
                        params["spent_at_height"] = rekey_record.spent_at_height
                        if not rekey_record.completed and rekey_record.clawback_pubkey is not None:
                            params["clawback_pubkey"] = BLSPublicKey(rekey_record.clawback_pubkey).as_bech32m()
                elif singleton.spend_type == SpendType.FINISH_REKEY:
                    params = {
                        "from_root": singleton_dict[singleton.coin.parent_coin_info].puzzle_root.hex(),
                        "to_root": singleton.puzzle_root.hex(),
                    }

                audit_dict.append(
                    {
                        "time": singleton_parent_dict[coin_id].confirmed_at_time,
                        "action": singleton.spend_type.name,
                        "params": params,
                    }
                )

            sorted_audit_dict = sorted(audit_dict, key=lambda e: e["time"])

            if diff is not None:
                diff_dict = []
                for i in range(0, len(sorted_audit_dict)):
                    if i >= len(old_dict):
                        diff_dict.append({"new": sorted_audit_dict[i]})
                    elif old_dict[i] != sorted_audit_dict[i]:
                        diff_dict.append(
                            {
                                "old": old_dict[i],
                                "new": sorted_audit_dict[i],
                            }
                        )
                final_dict = diff_dict
            else:
                final_dict = sorted_audit_dict

            if filepath is None:
                print(json.dumps(final_dict))
            else:
                with open(filepath, "w") as file:
                    file.write(json.dumps(final_dict))

        finally:
            await sync_store.db_connection.close()

    asyncio.get_event_loop().run_until_complete(do_command())


@custody_cmd.command("examine_spend", short_help="Examine an unsigned spend to see the details before you sign it")
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
    spend_file: str,
    qr_density: int,
    validate_against: str,
):
    bundle = read_unsigned_spend(spend_file)

    singleton_spends: List[HSMCoinSpend] = [cs for cs in bundle.coin_spends if cs.coin.amount % 2 == 1]
    drop_coin_spends: List[HSMCoinSpend] = [cs for cs in bundle.coin_spends if cs.coin.amount % 2 == 0]
    if len(singleton_spends) > 1:
        names: List[bytes32] = [cs.coin.name() for cs in singleton_spends]
        spend: HSMCoinSpend = next(cs for cs in singleton_spends if cs.coin.parent_coin_info not in names)
        spend_type: str = "LOCK"
    elif len(singleton_spends) == 1:
        spend = singleton_spends[0]
        spend_type = get_spend_type_for_solution(Program.from_bytes(bytes(spend.solution))).name
    else:
        spend = drop_coin_spends[0]
        if spend.coin.amount == 0:
            spend_type = "REKEY_CANCEL"
        else:
            spend_type = "PAYMENT_CLAWBACK"

    # HSM type conversions
    puzzle = Program.from_bytes(bytes(spend.puzzle_reveal))
    solution = Program.from_bytes(bytes(spend.solution))

    spend_summary: str
    if spend_type == "HANDLE_PAYMENT":
        spending_pubkey: G1Element = get_spending_pubkey_for_solution(solution)
        out_amount, in_amount, p2_ph = get_spend_params_for_ach_creation(solution)
        print("Type: Payment")
        print(f"Incoming: {in_amount}")
        print(f"Outgoing: {out_amount}")
        print(f"To: {encode_puzzle_hash(p2_ph, 'xch')}")
        print(f"Spenders: {BLSPublicKey(spending_pubkey).as_bech32m()}")
        spend_summary = f"""
        <div>
          <ul>
            <li>Type: Payment</li>
            <li>Incoming: {in_amount}</li>
            <li>Outgoing: {out_amount}</li>
            <li>To: {encode_puzzle_hash(p2_ph, 'xch')}</li>
            <li>Spenders: {BLSPublicKey(spending_pubkey).as_bech32m()}</li>
          </ul>
        </div>
        """
    elif spend_type == "LOCK":
        spending_pubkey = get_spending_pubkey_for_solution(solution)
        print("Type: Lock level increase")
        print(f"Spenders: {BLSPublicKey(spending_pubkey).as_bech32m()}")
        spend_summary = f"""
        <div>
          <ul>
            <li>Type: Lock level increase</li>
            <li>Spenders: {BLSPublicKey(spending_pubkey).as_bech32m()}</li>
          </ul>
        </div>
        """
    elif spend_type == "START_REKEY":
        spending_pubkey = get_spending_pubkey_for_solution(solution)
        from_root = get_puzzle_root_from_puzzle(puzzle)
        timelock, new_root = get_spend_params_for_rekey_creation(solution)
        print("Type: Rekey")
        print(f"From: {from_root}")
        print(f"To: {new_root}")
        print(f"Slow factor: {timelock}")
        print(f"Spenders: {BLSPublicKey(spending_pubkey).as_bech32m()}")
        spend_summary = f"""
        <div>
          <ul>
            <li>Type: Rekey</li>
            <li>From: {from_root}</li>
            <li>To: {new_root}</li>
            <li>Slow factor: {timelock}</li>
            <li>Spenders: {BLSPublicKey(spending_pubkey).as_bech32m()}</li>
          </ul>
        </div>
        """
        if validate_against is not None:
            derivation = load_root_derivation(validate_against)
            re_derivation = calculate_puzzle_root(
                derivation.prefarm_info,
                derivation.pubkey_list,
                derivation.required_pubkeys,
                derivation.maximum_pubkeys,
                derivation.minimum_pubkeys,
            )
            if re_derivation.prefarm_info.puzzle_root == new_root and re_derivation == derivation:
                print(f"Configuration successfully validated against root: {new_root}")
            elif re_derivation == derivation:
                expected: bytes32 = new_root
                got: bytes32 = re_derivation.prefarm_info.puzzle_root
                print(f"Configuration does not validate. Expected {expected}, got {got}.")
            else:
                print("Configuration is malformed, could not validate")
    elif spend_type == "REKEY_CANCEL":
        spending_pubkey = get_spending_pubkey_for_drop_coin(solution)
        new_root, old_root, timelock = get_info_for_rekey_drop(puzzle)
        print("Type: Rekey Cancel")
        print(f"From: {old_root}")
        print(f"To: {new_root}")
        print(f"Spenders: {BLSPublicKey(spending_pubkey).as_bech32m()}")
        spend_summary = f"""
        <div>
          <ul>
            <li>Type: Rekey Cancel</li>
            <li>From: {old_root}</li>
            <li>To: {new_root}</li>
            <li>Spenders: {BLSPublicKey(spending_pubkey).as_bech32m()}</li>
          </ul>
        </div>
        """
    elif spend_type == "PAYMENT_CLAWBACK":
        spending_pubkey = get_spending_pubkey_for_drop_coin(solution)
        _, p2_ph = get_info_for_ach_drop(puzzle)
        print("Type: Payment Clawback")
        print(f"Amount: {spend.coin.amount}")
        print(f"To: {encode_puzzle_hash(p2_ph, 'xch')}")
        print(f"Spenders: {BLSPublicKey(spending_pubkey).as_bech32m()}")
        spend_summary = f"""
        <div>
          <ul>
            <li>Type: Payment Clawback</li>
            <li>Amount: {spend.coin.amount}</li>
            <li>To: {encode_puzzle_hash(p2_ph, 'xch')}</li>
            <li>Spenders: {BLSPublicKey(spending_pubkey).as_bech32m()}</li>
          </ul>
        </div>
        """
    else:
        print("Spend is not signable")
        return

    # Transform the bundle in qr codes and then inline them in a div
    all_qr_divs = ""
    normal_qr_width: Optional[float] = None
    for segment in bundle.chunk(qr_density):
        qr_int = b2a_qrint(segment)
        qr = segno.make_qr(qr_int)
        if len(segment) == qr_density or normal_qr_width is None:
            normal_qr_width = qr.symbol_size()[0]
            scale: float = 3
        else:
            scale = 3 * (normal_qr_width / qr.symbol_size()[0])
        all_qr_divs += f"<div>{qr.svg_inline(scale=scale)}</div>"

    total_doc = f"""
    <html width='100%' height='100%'>
        <body width='100%' height='100%'>
            <div width='100%' height='100%'>
              {spend_summary}
              <div style='display:flex; flex-wrap: wrap; width:100%;'>
                {all_qr_divs}
              </div>
            </div>
        </body>
    </html>
    """

    # Write to a temporary file and open in a browser
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".html")
    try:
        tmp_path = Path(tmp.name)
        tmp.write(bytes(total_doc, "utf-8"))
        tmp.close()
        webbrowser.open(f"file://{tmp_path}", new=2)
        input("Press Enter to exit")
    finally:
        os.unlink(tmp.name)


@custody_cmd.command("which_pubkeys", short_help="Determine which pubkeys make up an aggregate pubkey")
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
    aggregate_pubkey: str,
    pubkeys: str,
    num_pubkeys: Optional[int],
    no_offset: bool,
):
    agg_pk: G1Element = list(load_pubkeys(aggregate_pubkey))[0]
    pubkey_list: List[G1Element] = list(load_pubkeys(pubkeys))

    pubkey_file_dict: Dict[str, str] = {}
    for pk, file in zip(pubkey_list, pubkeys.split(",")):
        pubkey_file_dict[str(pk)] = file

    search_range = range(1, len(pubkey_list) + 1) if num_pubkeys is None else range(num_pubkeys, num_pubkeys + 1)
    for m in search_range:
        for subset in itertools.combinations(pubkey_list, m):
            aggregated_pubkey = G1Element()
            for pk in subset:
                aggregated_pubkey += pk
            if aggregated_pubkey == agg_pk or (
                not no_offset
                and PrivateKey.from_bytes(
                    calculate_synthetic_offset(aggregated_pubkey, DEFAULT_HIDDEN_PUZZLE_HASH).to_bytes(32, "big")
                ).get_g1()
                + aggregated_pubkey
                == agg_pk
            ):
                print("The following pubkeys match the specified aggregate:")
                for pk in subset:
                    print(f" - {pubkey_file_dict[str(pk)]}")
                return

    print("No combinations were found that matched the aggregate with the specified parameters.")

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
 



