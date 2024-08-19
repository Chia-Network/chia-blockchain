from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Callable, Coroutine, Dict, List, Optional, Sequence, TypeVar, Union

import click

from chia.cmds import options
from chia.cmds.param_types import Bytes32ParamType
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.ints import uint64

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


@click.group("data", help="Manage your data")
def data_cmd() -> None:
    pass


# TODO: maybe use more helpful `type=`s to get click to handle error reporting of
#       malformed inputs.


def create_changelist_option() -> Callable[[FC], FC]:
    return click.option(
        "-d",
        "--changelist",
        "changelist_string",
        help="str representing the changelist",
        type=str,
        required=True,
    )


def create_store_updates_option() -> Callable[[FC], FC]:
    return click.option(
        "-d",
        "--store_updates",
        "store_updates_string",
        help="str representing the store updates",
        type=str,
        required=True,
    )


def create_key_option(multiple: bool = False) -> Callable[[FC], FC]:
    return click.option(
        "-k",
        "--key",
        "key_strings" if multiple else "key_string",
        help="str representing the key",
        type=str,
        required=True,
        multiple=multiple,
    )


def create_data_store_id_option() -> Callable[[FC], FC]:
    return click.option(
        "-store",
        "--id",
        help="The hexadecimal store id.",
        type=Bytes32ParamType(),
        required=True,
    )


def create_data_store_name_option() -> Callable[[FC], FC]:
    return click.option(
        "-n",
        "--table_name",
        "table_name",
        help="The name of the table.",
        type=str,
        required=True,
    )


def create_rpc_port_option() -> Callable[[FC], FC]:
    return click.option(
        "-dp",
        "--data-rpc-port",
        help="Set the port where the data layer is hosting the RPC interface. See rpc_port under wallet in config.yaml",
        type=int,
        default=None,
        show_default=True,
    )


def create_root_hash_option() -> Callable[[FC], FC]:
    return click.option(
        "-r",
        "--root_hash",
        help="The hexadecimal root hash",
        type=Bytes32ParamType(),
        required=False,
    )


def create_page_option() -> Callable[[FC], FC]:
    return click.option(
        "-p",
        "--page",
        help="Enables pagination of the output and requests a specific page.",
        type=int,
        required=False,
    )


def create_max_page_size_option() -> Callable[[FC], FC]:
    return click.option(
        "--max-page-size",
        help="Set how many bytes to be included in a page, if pagination is enabled.",
        type=int,
        required=False,
    )


# Functions with this mark in this file are not being ported to @tx_out_cmd due to API peculiarities
# They will therefore not work with observer-only functionality
# NOTE: tx_endpoint  (This creates wallet transactions and should be parametrized by relevant options)
@data_cmd.command("create_data_store", help="Create a new data store")
@create_rpc_port_option()
@options.create_fee()
@click.option("--verbose", is_flag=True, help="Enable verbose output.")
@options.create_fingerprint()
def create_data_store(
    data_rpc_port: int,
    fee: Optional[uint64],
    verbose: bool,
    fingerprint: Optional[int],
) -> None:
    from chia.cmds.data_funcs import create_data_store_cmd

    run(create_data_store_cmd(data_rpc_port, fee, verbose, fingerprint=fingerprint))


@data_cmd.command("get_value", help="Get the value for a given key and store")
@create_data_store_id_option()
@create_key_option()
@create_root_hash_option()
@create_rpc_port_option()
@options.create_fingerprint()
def get_value(
    id: bytes32,
    key_string: str,
    root_hash: Optional[bytes32],
    data_rpc_port: int,
    fingerprint: Optional[int],
) -> None:
    from chia.cmds.data_funcs import get_value_cmd

    run(get_value_cmd(data_rpc_port, id, key_string, root_hash, fingerprint=fingerprint))


# NOTE: tx_endpoint
@data_cmd.command("update_data_store", help="Update a store by providing the changelist operations")
@create_data_store_id_option()
@create_changelist_option()
@create_rpc_port_option()
@options.create_fee()
@options.create_fingerprint()
@click.option("--submit/--no-submit", default=True, help="Submit the result on chain")
def update_data_store(
    id: bytes32,
    changelist_string: str,
    data_rpc_port: int,
    fee: Optional[uint64],
    fingerprint: Optional[int],
    submit: bool,
) -> None:
    from chia.cmds.data_funcs import update_data_store_cmd

    run(
        update_data_store_cmd(
            rpc_port=data_rpc_port,
            store_id=id,
            changelist=json.loads(changelist_string),
            fee=fee,
            fingerprint=fingerprint,
            submit_on_chain=submit,
        )
    )


@data_cmd.command("update_multiple_stores", help="Update multiple stores by providing the changelist operations")
@create_store_updates_option()
@create_rpc_port_option()
@options.create_fee()
@options.create_fingerprint()
@click.option("--submit/--no-submit", default=True, help="Submit the result on chain")
def update_multiple_stores(
    store_updates_string: str,
    data_rpc_port: int,
    fee: uint64,
    fingerprint: Optional[int],
    submit: bool,
) -> None:
    from chia.cmds.data_funcs import update_multiple_stores_cmd

    run(
        update_multiple_stores_cmd(
            rpc_port=data_rpc_port,
            store_updates=json.loads(store_updates_string),
            fee=fee,
            fingerprint=fingerprint,
            submit_on_chain=submit,
        )
    )


@data_cmd.command("submit_pending_root", help="Submit on chain a locally stored batch")
@create_data_store_id_option()
@create_rpc_port_option()
@options.create_fee()
@options.create_fingerprint()
def submit_pending_root(
    id: bytes32,
    data_rpc_port: int,
    fee: uint64,
    fingerprint: Optional[int],
) -> None:
    from chia.cmds.data_funcs import submit_pending_root_cmd

    run(
        submit_pending_root_cmd(
            rpc_port=data_rpc_port,
            store_id=id,
            fee=fee,
            fingerprint=fingerprint,
        )
    )


@data_cmd.command("submit_all_pending_roots", help="Submit on chain all locally stored batches")
@create_rpc_port_option()
@options.create_fee()
@options.create_fingerprint()
def submit_all_pending_roots(
    data_rpc_port: int,
    fee: uint64,
    fingerprint: Optional[int],
) -> None:
    from chia.cmds.data_funcs import submit_all_pending_roots_cmd

    run(
        submit_all_pending_roots_cmd(
            rpc_port=data_rpc_port,
            fee=fee,
            fingerprint=fingerprint,
        )
    )


@data_cmd.command("get_keys", help="Get all keys for a given store")
@create_data_store_id_option()
@create_root_hash_option()
@create_rpc_port_option()
@options.create_fingerprint()
@create_page_option()
@create_max_page_size_option()
def get_keys(
    id: bytes32,
    root_hash: Optional[bytes32],
    data_rpc_port: int,
    fingerprint: Optional[int],
    page: Optional[int],
    max_page_size: Optional[int],
) -> None:
    from chia.cmds.data_funcs import get_keys_cmd

    run(get_keys_cmd(data_rpc_port, id, root_hash, fingerprint=fingerprint, page=page, max_page_size=max_page_size))


@data_cmd.command("get_keys_values", help="Get all keys and values for a given store")
@create_data_store_id_option()
@create_root_hash_option()
@create_rpc_port_option()
@options.create_fingerprint()
@create_page_option()
@create_max_page_size_option()
def get_keys_values(
    id: bytes32,
    root_hash: Optional[bytes32],
    data_rpc_port: int,
    fingerprint: Optional[int],
    page: Optional[int],
    max_page_size: Optional[int],
) -> None:
    from chia.cmds.data_funcs import get_keys_values_cmd

    run(
        get_keys_values_cmd(
            data_rpc_port, id, root_hash, fingerprint=fingerprint, page=page, max_page_size=max_page_size
        )
    )


@data_cmd.command("get_root", help="Get the published root hash value for a given store")
@create_data_store_id_option()
@create_rpc_port_option()
@options.create_fingerprint()
def get_root(
    id: bytes32,
    data_rpc_port: int,
    fingerprint: Optional[int],
) -> None:
    from chia.cmds.data_funcs import get_root_cmd

    run(get_root_cmd(rpc_port=data_rpc_port, store_id=id, fingerprint=fingerprint))


@data_cmd.command("subscribe", help="Subscribe to a store")
@create_data_store_id_option()
@click.option(
    "-u",
    "--url",
    "urls",
    help="Manually provide a list of servers urls for downloading the data",
    type=str,
    multiple=True,
)
@create_rpc_port_option()
@options.create_fingerprint()
def subscribe(
    id: bytes32,
    urls: List[str],
    data_rpc_port: int,
    fingerprint: Optional[int],
) -> None:
    from chia.cmds.data_funcs import subscribe_cmd

    run(subscribe_cmd(rpc_port=data_rpc_port, store_id=id, urls=urls, fingerprint=fingerprint))


@data_cmd.command("remove_subscription", help="Remove server urls that are added via subscribing to urls")
@create_data_store_id_option()
@click.option("-u", "--url", "urls", help="Server urls to remove", type=str, multiple=True)
@create_rpc_port_option()
@options.create_fingerprint()
def remove_subscription(
    id: bytes32,
    urls: List[str],
    data_rpc_port: int,
    fingerprint: Optional[int],
) -> None:
    from chia.cmds.data_funcs import remove_subscriptions_cmd

    run(remove_subscriptions_cmd(rpc_port=data_rpc_port, store_id=id, urls=urls, fingerprint=fingerprint))


@data_cmd.command("unsubscribe", help="Completely untrack a store")
@create_data_store_id_option()
@create_rpc_port_option()
@options.create_fingerprint()
@click.option("--retain", is_flag=True, help="Retain .dat files")
def unsubscribe(
    id: bytes32,
    data_rpc_port: int,
    fingerprint: Optional[int],
    retain: bool,
) -> None:
    from chia.cmds.data_funcs import unsubscribe_cmd

    run(unsubscribe_cmd(rpc_port=data_rpc_port, store_id=id, fingerprint=fingerprint, retain=retain))


@data_cmd.command(
    "get_kv_diff", help="Get the inserted and deleted keys and values between an initial and a final hash"
)
@create_data_store_id_option()
@click.option("-hash_1", "--hash_1", help="Initial hash", type=Bytes32ParamType(), required=True)
@click.option("-hash_2", "--hash_2", help="Final hash", type=Bytes32ParamType(), required=True)
@create_rpc_port_option()
@options.create_fingerprint()
@create_page_option()
@create_max_page_size_option()
def get_kv_diff(
    id: bytes32,
    hash_1: bytes32,
    hash_2: bytes32,
    data_rpc_port: int,
    fingerprint: Optional[int],
    page: Optional[int],
    max_page_size: Optional[int],
) -> None:
    from chia.cmds.data_funcs import get_kv_diff_cmd

    run(
        get_kv_diff_cmd(
            rpc_port=data_rpc_port,
            store_id=id,
            hash_1=hash_1,
            hash_2=hash_2,
            fingerprint=fingerprint,
            page=page,
            max_page_size=max_page_size,
        )
    )


@data_cmd.command("get_root_history", help="Get all changes of a singleton")
@create_data_store_id_option()
@create_rpc_port_option()
@options.create_fingerprint()
def get_root_history(
    id: bytes32,
    data_rpc_port: int,
    fingerprint: Optional[int],
) -> None:
    from chia.cmds.data_funcs import get_root_history_cmd

    run(get_root_history_cmd(rpc_port=data_rpc_port, store_id=id, fingerprint=fingerprint))


@data_cmd.command("add_missing_files", help="Manually reconstruct server files from the data layer database")
@click.option(
    "-i",
    "--ids",
    help="List of stores to reconstruct. If not specified, all stores will be reconstructed",
    type=str,
    multiple=True,
    required=False,
)
@click.option(
    "-o/-n",
    "--overwrite/--no-overwrite",
    help="Specify if already existing files need to be overwritten by this command",
)
@click.option(
    "-d", "--directory", type=str, help="If specified, use a non-default directory to write the files", required=False
)
@create_rpc_port_option()
@options.create_fingerprint()
def add_missing_files(
    ids: Sequence[bytes32],
    overwrite: bool,
    directory: Optional[str],
    data_rpc_port: int,
    fingerprint: Optional[int],
) -> None:
    from chia.cmds.data_funcs import add_missing_files_cmd

    run(
        add_missing_files_cmd(
            rpc_port=data_rpc_port,
            ids=list(ids) if ids else None,
            overwrite=overwrite,
            foldername=None if directory is None else Path(directory),
            fingerprint=fingerprint,
        )
    )


# NOTE: tx_endpoint
@data_cmd.command("add_mirror", help="Publish mirror urls on chain")
@create_data_store_id_option()
@click.option(
    "-a", "--amount", help="Amount to spend for this mirror, in mojos", type=int, default=0, show_default=True
)
@click.option(
    "-u",
    "--url",
    "urls",
    help="URL to publish on the new coin, multiple accepted and will be published to a single coin.",
    type=str,
    multiple=True,
)
@options.create_fee()
@create_rpc_port_option()
@options.create_fingerprint()
def add_mirror(
    id: bytes32,
    amount: int,
    urls: List[str],
    fee: Optional[uint64],
    data_rpc_port: int,
    fingerprint: Optional[int],
) -> None:
    from chia.cmds.data_funcs import add_mirror_cmd

    run(
        add_mirror_cmd(
            rpc_port=data_rpc_port,
            store_id=id,
            urls=urls,
            amount=amount,
            fee=fee,
            fingerprint=fingerprint,
        )
    )


# NOTE: tx_endpoint
@data_cmd.command("delete_mirror", help="Delete an owned mirror by its coin id")
@click.option("-c", "--coin_id", help="Coin id", type=Bytes32ParamType(), required=True)
@options.create_fee()
@create_rpc_port_option()
@options.create_fingerprint()
def delete_mirror(
    coin_id: bytes32,
    fee: Optional[uint64],
    data_rpc_port: int,
    fingerprint: Optional[int],
) -> None:
    from chia.cmds.data_funcs import delete_mirror_cmd

    run(
        delete_mirror_cmd(
            rpc_port=data_rpc_port,
            coin_id=coin_id,
            fee=fee,
            fingerprint=fingerprint,
        )
    )


@data_cmd.command("get_mirrors", help="Get a list of all mirrors for a given store")
@create_data_store_id_option()
@create_rpc_port_option()
@options.create_fingerprint()
def get_mirrors(
    id: bytes32,
    data_rpc_port: int,
    fingerprint: Optional[int],
) -> None:
    from chia.cmds.data_funcs import get_mirrors_cmd

    run(
        get_mirrors_cmd(
            rpc_port=data_rpc_port,
            store_id=id,
            fingerprint=fingerprint,
        )
    )


@data_cmd.command("get_subscriptions", help="Get subscribed stores, including the owned stores")
@create_rpc_port_option()
@options.create_fingerprint()
def get_subscriptions(
    data_rpc_port: int,
    fingerprint: Optional[int],
) -> None:
    from chia.cmds.data_funcs import get_subscriptions_cmd

    run(
        get_subscriptions_cmd(
            rpc_port=data_rpc_port,
            fingerprint=fingerprint,
        )
    )


@data_cmd.command("get_owned_stores", help="Get owned stores")
@create_rpc_port_option()
@options.create_fingerprint()
def get_owned_stores(
    data_rpc_port: int,
    fingerprint: Optional[int],
) -> None:
    from chia.cmds.data_funcs import get_owned_stores_cmd

    run(
        get_owned_stores_cmd(
            rpc_port=data_rpc_port,
            fingerprint=fingerprint,
        )
    )


@data_cmd.command("get_sync_status", help="Get locally stored root compared to the root of the singleton")
@create_data_store_id_option()
@create_rpc_port_option()
@options.create_fingerprint()
def get_sync_status(
    id: bytes32,
    data_rpc_port: int,
    fingerprint: Optional[int],
) -> None:
    from chia.cmds.data_funcs import get_sync_status_cmd

    run(get_sync_status_cmd(rpc_port=data_rpc_port, store_id=id, fingerprint=fingerprint))


@data_cmd.group("plugins", help="Get information about configured uploader/downloader plugins")
def plugins_cmd() -> None:
    pass


@plugins_cmd.command("check", help="Calls the plugin_info endpoint on all configured plugins")
@create_rpc_port_option()
def check_plugins(
    data_rpc_port: int,
) -> None:
    from chia.cmds.data_funcs import check_plugins_cmd

    run(check_plugins_cmd(rpc_port=data_rpc_port))


@data_cmd.command(
    "clear_pending_roots",
    help="Clear pending roots that will not be published, associated data may not be recoverable",
)
@create_data_store_id_option()
@click.confirmation_option(
    prompt="Associated data may not be recoverable.\nAre you sure you want to remove the pending roots?",
)
@create_rpc_port_option()
@options.create_fingerprint()
def clear_pending_roots(
    id: bytes32,
    data_rpc_port: int,
    fingerprint: Optional[int],
) -> None:
    from chia.cmds.data_funcs import clear_pending_roots

    run(
        clear_pending_roots(
            rpc_port=data_rpc_port,
            store_id=id,
            fingerprint=fingerprint,
        )
    )


@data_cmd.command(
    "wallet_log_in",
    help="Request that the wallet service be logged in to the specified fingerprint",
)
@create_rpc_port_option()
@options.create_fingerprint(required=True)
def wallet_log_in(
    data_rpc_port: int,
    fingerprint: int,
) -> None:
    from chia.cmds.data_funcs import wallet_log_in_cmd

    run(
        wallet_log_in_cmd(
            rpc_port=data_rpc_port,
            fingerprint=fingerprint,
        )
    )


@data_cmd.command(
    "get_proof",
    help="Obtains a merkle proof of inclusion for a given key",
)
@create_data_store_id_option()
@create_rpc_port_option()
@create_key_option(multiple=True)
@options.create_fingerprint()
def get_proof(
    id: bytes32,
    key_strings: List[str],
    data_rpc_port: int,
    fingerprint: Optional[int],
) -> None:
    from chia.cmds.data_funcs import get_proof_cmd

    run(get_proof_cmd(rpc_port=data_rpc_port, store_id=id, fingerprint=fingerprint, key_strings=key_strings))


@data_cmd.command(
    "verify_proof",
    help="Verifies a merkle proof of inclusion",
)
@click.option(
    "-p",
    "--proof",
    "proof_string",
    help="Proof to validate in JSON format.",
    type=str,
)
@create_rpc_port_option()
@options.create_fingerprint()
def verify_proof(
    proof_string: str,
    data_rpc_port: int,
    fingerprint: Optional[int],
) -> None:
    from chia.cmds.data_funcs import verify_proof_cmd

    proof_dict = json.loads(proof_string)
    run(verify_proof_cmd(rpc_port=data_rpc_port, fingerprint=fingerprint, proof=proof_dict))
