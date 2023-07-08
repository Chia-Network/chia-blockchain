from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Callable, Coroutine, Dict, List, Optional, TypeVar, Union

import click

from chia.cmds.param_types import BYTES32_TYPE, TRANSACTION_FEE
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


def create_key_option() -> Callable[[FC], FC]:
    return click.option(
        "-h",
        "--key",
        "key_string",
        help="str representing the key",
        type=str,
        required=True,
    )


def create_data_store_id_option() -> Callable[[FC], FC]:
    return click.option(
        "-store",
        "--id",
        help="The hexadecimal store id.",
        type=BYTES32_TYPE,
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


def create_fee_option() -> Callable[[FC], FC]:
    return click.option(
        "-m",
        "--fee",
        help="Set the fees for the transaction, in XCH",
        type=TRANSACTION_FEE,
        default=None,
        show_default=True,
        required=False,
    )


def create_root_hash_option() -> Callable[[FC], FC]:
    return click.option(
        "-r",
        "--root_hash",
        help="The hexadecimal root hash",
        type=BYTES32_TYPE,
        required=False,
    )


@data_cmd.command("create_data_store", help="Create a new data store")
@create_rpc_port_option()
@create_fee_option()
def create_data_store(
    data_rpc_port: int,
    fee: Optional[uint64],
) -> None:
    from chia.cmds.data_funcs import create_data_store_cmd

    run(create_data_store_cmd(data_rpc_port, fee))


@data_cmd.command("get_value", help="Get the value for a given key and store")
@create_data_store_id_option()
@create_key_option()
@create_root_hash_option()
@create_rpc_port_option()
def get_value(
    id: bytes32,
    key_string: str,
    root_hash: Optional[bytes32],
    data_rpc_port: int,
) -> None:
    from chia.cmds.data_funcs import get_value_cmd

    run(get_value_cmd(data_rpc_port, id, key_string, root_hash))


@data_cmd.command("update_data_store", help="Update a store by providing the changelist operations")
@create_data_store_id_option()
@create_changelist_option()
@create_rpc_port_option()
@create_fee_option()
def update_data_store(
    id: bytes32,
    changelist_string: str,
    data_rpc_port: int,
    fee: Optional[uint64],
) -> None:
    from chia.cmds.data_funcs import update_data_store_cmd

    run(update_data_store_cmd(rpc_port=data_rpc_port, store_id=id, changelist=json.loads(changelist_string), fee=fee))


@data_cmd.command("get_keys", help="Get all keys for a given store")
@create_data_store_id_option()
@create_root_hash_option()
@create_rpc_port_option()
def get_keys(
    id: bytes32,
    root_hash: Optional[bytes32],
    data_rpc_port: int,
) -> None:
    from chia.cmds.data_funcs import get_keys_cmd

    run(get_keys_cmd(data_rpc_port, id, root_hash))


@data_cmd.command("get_keys_values", help="Get all keys and values for a given store")
@create_data_store_id_option()
@create_root_hash_option()
@create_rpc_port_option()
def get_keys_values(
    id: bytes32,
    root_hash: Optional[bytes32],
    data_rpc_port: int,
) -> None:
    from chia.cmds.data_funcs import get_keys_values_cmd

    run(get_keys_values_cmd(data_rpc_port, id, root_hash))


@data_cmd.command("get_root", help="Get the published root hash value for a given store")
@create_data_store_id_option()
@create_rpc_port_option()
def get_root(
    id: bytes32,
    data_rpc_port: int,
) -> None:
    from chia.cmds.data_funcs import get_root_cmd

    run(get_root_cmd(rpc_port=data_rpc_port, store_id=id))


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
def subscribe(
    id: bytes32,
    urls: List[str],
    data_rpc_port: int,
) -> None:
    from chia.cmds.data_funcs import subscribe_cmd

    run(subscribe_cmd(rpc_port=data_rpc_port, store_id=id, urls=urls))


@data_cmd.command("remove_subscription", help="Remove server urls that are added via subscribing to urls")
@create_data_store_id_option()
@click.option("-u", "--url", "urls", help="Server urls to remove", type=str, multiple=True)
@create_rpc_port_option()
def remove_subscription(
    id: bytes32,
    urls: List[str],
    data_rpc_port: int,
) -> None:
    from chia.cmds.data_funcs import remove_subscriptions_cmd

    run(remove_subscriptions_cmd(rpc_port=data_rpc_port, store_id=id, urls=urls))


@data_cmd.command("unsubscribe", help="Completely untrack a store")
@create_data_store_id_option()
@create_rpc_port_option()
def unsubscribe(
    id: bytes32,
    data_rpc_port: int,
) -> None:
    from chia.cmds.data_funcs import unsubscribe_cmd

    run(unsubscribe_cmd(rpc_port=data_rpc_port, store_id=id))


@data_cmd.command(
    "get_kv_diff", help="Get the inserted and deleted keys and values between an initial and a final hash"
)
@create_data_store_id_option()
@click.option("-hash_1", "--hash_1", help="Initial hash", type=BYTES32_TYPE, required=True)
@click.option("-hash_2", "--hash_2", help="Final hash", type=BYTES32_TYPE, required=True)
@create_rpc_port_option()
def get_kv_diff(
    id: bytes32,
    hash_1: bytes32,
    hash_2: bytes32,
    data_rpc_port: int,
) -> None:
    from chia.cmds.data_funcs import get_kv_diff_cmd

    run(get_kv_diff_cmd(rpc_port=data_rpc_port, store_id=id, hash_1=hash_1, hash_2=hash_2))


@data_cmd.command("get_root_history", help="Get all changes of a singleton")
@create_data_store_id_option()
@create_rpc_port_option()
def get_root_history(
    id: bytes32,
    data_rpc_port: int,
) -> None:
    from chia.cmds.data_funcs import get_root_history_cmd

    run(get_root_history_cmd(rpc_port=data_rpc_port, store_id=id))


@data_cmd.command("add_missing_files", help="Manually reconstruct server files from the data layer database")
@click.option(
    "-i",
    "--ids",
    help="List of stores to reconstruct. If not specified, all stores will be reconstructed",
    type=str,
    required=False,
)
@click.option(
    "-o/-n",
    "--overwrite/--no-overwrite",
    help="Specify if already existing files need to be overwritten by this command",
)
@click.option(
    "-f", "--foldername", type=str, help="If specified, use a non-default folder to write the files", required=False
)
@create_rpc_port_option()
def add_missing_files(ids: Optional[str], overwrite: bool, foldername: Optional[str], data_rpc_port: int) -> None:
    from chia.cmds.data_funcs import add_missing_files_cmd

    run(
        add_missing_files_cmd(
            rpc_port=data_rpc_port,
            ids=None if ids is None else json.loads(ids),
            overwrite=overwrite,
            foldername=None if foldername is None else Path(foldername),
        )
    )


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
@create_fee_option()
@create_rpc_port_option()
def add_mirror(id: bytes32, amount: int, urls: List[str], fee: Optional[uint64], data_rpc_port: int) -> None:
    from chia.cmds.data_funcs import add_mirror_cmd

    run(
        add_mirror_cmd(
            rpc_port=data_rpc_port,
            store_id=id,
            urls=urls,
            amount=amount,
            fee=fee,
        )
    )


@data_cmd.command("delete_mirror", help="Delete an owned mirror by its coin id")
@click.option("-c", "--coin_id", help="Coin id", type=BYTES32_TYPE, required=True)
@create_fee_option()
@create_rpc_port_option()
def delete_mirror(coin_id: bytes32, fee: Optional[uint64], data_rpc_port: int) -> None:
    from chia.cmds.data_funcs import delete_mirror_cmd

    run(
        delete_mirror_cmd(
            rpc_port=data_rpc_port,
            coin_id=coin_id,
            fee=fee,
        )
    )


@data_cmd.command("get_mirrors", help="Get a list of all mirrors for a given store")
@create_data_store_id_option()
@create_rpc_port_option()
def get_mirrors(id: bytes32, data_rpc_port: int) -> None:
    from chia.cmds.data_funcs import get_mirrors_cmd

    run(
        get_mirrors_cmd(
            rpc_port=data_rpc_port,
            store_id=id,
        )
    )


@data_cmd.command("get_subscriptions", help="Get subscribed stores, including the owned stores")
@create_rpc_port_option()
def get_subscriptions(data_rpc_port: int) -> None:
    from chia.cmds.data_funcs import get_subscriptions_cmd

    run(
        get_subscriptions_cmd(
            rpc_port=data_rpc_port,
        )
    )


@data_cmd.command("get_owned_stores", help="Get owned stores")
@create_rpc_port_option()
def get_owned_stores(data_rpc_port: int) -> None:
    from chia.cmds.data_funcs import get_owned_stores_cmd

    run(
        get_owned_stores_cmd(
            rpc_port=data_rpc_port,
        )
    )


@data_cmd.command("get_sync_status", help="Get locally stored root compared to the root of the singleton")
@create_data_store_id_option()
@create_rpc_port_option()
def get_sync_status(
    id: bytes32,
    data_rpc_port: int,
) -> None:
    from chia.cmds.data_funcs import get_sync_status_cmd

    run(get_sync_status_cmd(rpc_port=data_rpc_port, store_id=id))


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
@click.option("-i", "--id", "id_str", help="Store ID", type=str, required=True)
@click.confirmation_option(
    prompt="Associated data may not be recoverable.\nAre you sure you want to remove the pending roots?",
)
@create_rpc_port_option()
def clear_pending_roots(id_str: str, data_rpc_port: int) -> None:
    from chia.cmds.data_funcs import clear_pending_roots

    store_id = bytes32.from_hexstr(id_str)

    run(
        clear_pending_roots(
            rpc_port=data_rpc_port,
            store_id=store_id,
        )
    )
