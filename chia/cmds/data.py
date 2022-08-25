import json
import logging
from pathlib import Path
from typing import Any, Coroutine, Dict, List, Optional, TypeVar

import click
from typing_extensions import Protocol

_T = TypeVar("_T")


class IdentityFunction(Protocol):
    def __call__(self, __x: _T) -> _T:
        ...


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


@click.group("data", short_help="Manage your data")
def data_cmd() -> None:
    pass


# TODO: maybe use more helpful `type=`s to get click to handle error reporting of
#       malformed inputs.


def create_changelist_option() -> IdentityFunction:
    return click.option(
        "-d",
        "--changelist",
        "changelist_string",
        help="str representing the changelist",
        type=str,
        required=True,
    )


def create_key_option() -> IdentityFunction:
    return click.option(
        "-h",
        "--key",
        "key_string",
        help="str representing the key",
        type=str,
        required=True,
    )


def create_data_store_id_option() -> "IdentityFunction":
    return click.option(
        "-store",
        "--id",
        help="The hexadecimal store id.",
        type=str,
        required=True,
    )


def create_data_store_name_option() -> "IdentityFunction":
    return click.option(
        "-n",
        "--table_name",
        "table_name",
        help="The name of the table.",
        type=str,
        required=True,
    )


def create_rpc_port_option() -> "IdentityFunction":
    return click.option(
        "-dp",
        "--data-rpc-port",
        help="Set the port where the data layer is hosting the RPC interface. See rpc_port under wallet in config.yaml",
        type=int,
        default=None,
        show_default=True,
    )


def create_fee_option() -> "IdentityFunction":
    return click.option(
        "-m",
        "--fee",
        help="Set the fees for the transaction, in XCH",
        type=str,
        default=None,
        show_default=True,
        required=False,
    )


@data_cmd.command("create_data_store", short_help="Create a new data store")
@click.option("-f", "--fingerprint", help="Set the fingerprint to specify which wallet to use", type=int)
@create_rpc_port_option()
@create_fee_option()
def create_data_store(
    fingerprint: int,
    data_rpc_port: int,
    fee: Optional[str],
) -> None:
    from chia.cmds.data_funcs import create_data_store_cmd

    run(create_data_store_cmd(data_rpc_port, fee))


@data_cmd.command("get_value", short_help="Get the value for a given key and store")
@create_data_store_id_option()
@create_key_option()
@click.option("-f", "--fingerprint", help="Set the fingerprint to specify which wallet to use", type=int)
@create_rpc_port_option()
def get_value(
    id: str,
    key_string: str,
    fingerprint: int,
    data_rpc_port: int,
) -> None:
    from chia.cmds.data_funcs import get_value_cmd

    run(get_value_cmd(data_rpc_port, id, key_string))


@data_cmd.command("update_data_store", short_help="Update a store by providing the changelist operations")
@create_data_store_id_option()
@create_changelist_option()
@click.option("-f", "--fingerprint", help="Set the fingerprint to specify which wallet to use", type=int)
@create_rpc_port_option()
@create_fee_option()
def update_data_store(
    id: str,
    changelist_string: str,
    fingerprint: int,
    data_rpc_port: int,
    fee: str,
) -> None:
    from chia.cmds.data_funcs import update_data_store_cmd

    run(update_data_store_cmd(rpc_port=data_rpc_port, store_id=id, changelist=json.loads(changelist_string), fee=fee))


@data_cmd.command("get_keys", short_help="Get all keys for a given store")
@create_data_store_id_option()
@click.option("-f", "--fingerprint", help="Set the fingerprint to specify which wallet to use", type=int)
@create_rpc_port_option()
def get_keys(
    id: str,
    fingerprint: int,
    data_rpc_port: int,
) -> None:
    from chia.cmds.data_funcs import get_keys_cmd

    run(get_keys_cmd(data_rpc_port, id))


@data_cmd.command("get_keys_values", short_help="Get all keys and values for a given store")
@create_data_store_id_option()
@click.option("-f", "--fingerprint", help="Set the fingerprint to specify which wallet to use", type=int)
@create_rpc_port_option()
def get_keys_values(
    id: str,
    fingerprint: int,
    data_rpc_port: int,
) -> None:
    from chia.cmds.data_funcs import get_keys_values_cmd

    run(get_keys_values_cmd(data_rpc_port, id))


@data_cmd.command("get_root", short_help="Get the published root hash value for a given store")
@create_data_store_id_option()
@click.option("-f", "--fingerprint", help="Set the fingerprint to specify which wallet to use", type=int)
@create_rpc_port_option()
def get_root(
    id: str,
    fingerprint: int,
    data_rpc_port: int,
) -> None:
    from chia.cmds.data_funcs import get_root_cmd

    run(get_root_cmd(rpc_port=data_rpc_port, store_id=id))


@data_cmd.command("subscribe", short_help="Subscribe to a store")
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
    id: str,
    urls: List[str],
    data_rpc_port: int,
) -> None:
    from chia.cmds.data_funcs import subscribe_cmd

    run(subscribe_cmd(rpc_port=data_rpc_port, store_id=id, urls=urls))


@data_cmd.command("remove_subscription", short_help="Remove server urls that are added via subscribing to urls")
@create_data_store_id_option()
@click.option("-u", "--url", "urls", help="Server urls to remove", type=str, multiple=True)
@create_rpc_port_option()
def remove_subscription(
    id: str,
    urls: List[str],
    data_rpc_port: int,
) -> None:
    from chia.cmds.data_funcs import remove_subscriptions_cmd

    run(remove_subscriptions_cmd(rpc_port=data_rpc_port, store_id=id, urls=urls))


@data_cmd.command("unsubscribe", short_help="Completely untrack a store")
@create_data_store_id_option()
@create_rpc_port_option()
def unsubscribe(
    id: str,
    data_rpc_port: int,
) -> None:
    from chia.cmds.data_funcs import unsubscribe_cmd

    run(unsubscribe_cmd(rpc_port=data_rpc_port, store_id=id))


@data_cmd.command(
    "get_kv_diff", short_help="Get the inserted and deleted keys and values between an initial and a final hash"
)
@create_data_store_id_option()
@click.option("-hash_1", "--hash_1", help="Initial hash", type=str)
@click.option("-hash_2", "--hash_2", help="Final hash", type=str)
@create_rpc_port_option()
def get_kv_diff(
    id: str,
    hash_1: str,
    hash_2: str,
    data_rpc_port: int,
) -> None:
    from chia.cmds.data_funcs import get_kv_diff_cmd

    run(get_kv_diff_cmd(rpc_port=data_rpc_port, store_id=id, hash_1=hash_1, hash_2=hash_2))


@data_cmd.command("get_root_history", short_help="Get all changes of a singleton")
@create_data_store_id_option()
@create_rpc_port_option()
def get_root_history(
    id: str,
    data_rpc_port: int,
) -> None:
    from chia.cmds.data_funcs import get_root_history_cmd

    run(get_root_history_cmd(rpc_port=data_rpc_port, store_id=id))


@data_cmd.command("add_missing_files", short_help="Manually reconstruct server files from the data layer database")
@click.option(
    "-i",
    "--ids",
    help="List of stores to reconstruct. If not specified, all stores will be reconstructed",
    type=str,
    required=False,
)
@click.option(
    "-o/-n", "--override/--no-override", help="Specify if already existing files need to be overwritten by this command"
)
@click.option(
    "-f", "--foldername", type=str, help="If specified, use a non-default folder to write the files", required=False
)
@create_rpc_port_option()
def add_missing_files(ids: Optional[str], override: bool, foldername: Optional[str], data_rpc_port: int) -> None:
    from chia.cmds.data_funcs import add_missing_files_cmd

    run(
        add_missing_files_cmd(
            rpc_port=data_rpc_port,
            ids=None if ids is None else json.loads(ids),
            override=override,
            foldername=None if foldername is None else Path(foldername),
        )
    )


@data_cmd.command("add_mirror", short_help="Publish mirror urls on chain")
@click.option("-i", "--id", help="Store id", type=str, required=True)
@click.option("-a", "--amount", help="Amount for this mirror", type=int, required=True)
@click.option("-u", "--url", "urls", help="List of urls published for the coin", type=str, multiple=True)
@create_fee_option()
@create_rpc_port_option()
def add_mirror(id: str, amount: int, urls: List[str], fee: Optional[str], data_rpc_port: int) -> None:
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


@data_cmd.command("delete_mirror", short_help="Delete an owned mirror by its coin id")
@click.option("-i", "--id", help="Store id", type=str, required=True)
@create_fee_option()
@create_rpc_port_option()
def delete_mirror(id: str, fee: Optional[str], data_rpc_port: int) -> None:
    from chia.cmds.data_funcs import delete_mirror_cmd

    run(
        delete_mirror_cmd(
            rpc_port=data_rpc_port,
            coin_id=id,
            fee=fee,
        )
    )


@data_cmd.command("get_mirrors", short_help="Get a list of all mirrors for a given store")
@click.option("-i", "--id", help="Store id", type=str, required=True)
@create_rpc_port_option()
def get_mirrors(id: str, data_rpc_port: int) -> None:
    from chia.cmds.data_funcs import get_mirrors_cmd

    run(
        get_mirrors_cmd(
            rpc_port=data_rpc_port,
            store_id=id,
        )
    )
