import json
import logging
from typing import Any, Coroutine, Dict, Optional, TYPE_CHECKING

import click


if TYPE_CHECKING:
    from _typeshed import IdentityFunction


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


def create_changelist_option() -> "IdentityFunction":
    return click.option(
        "-d",
        "--changelist",
        "changelist_string",
        help="str representing the changelist",
        type=str,
        required=True,
    )


def create_key_option() -> "IdentityFunction":
    return click.option(
        "-h",
        "--key",
        "value key string",
        help="The hexadecimal value id.",
        type=str,
        required=True,
    )


def create_kv_store_id_option() -> "IdentityFunction":
    return click.option(
        "-store",
        "-id",
        help="The hexadecimal store id.",
        type=str,
        required=True,
    )


def create_kv_store_name_option() -> "IdentityFunction":
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
        help="Set the port where the Farmer is hosting the RPC interface. See the rpc_port under farmer in config.yaml",
        type=int,
        default=None,
        show_default=True,
    )


@data_cmd.command("create_kv_store", short_help="Get a data row by its hash")
@create_kv_store_id_option()
@create_rpc_port_option()
def create_kv_store(
    table_string: str,
    data_rpc_port: int,
) -> None:
    from chia.cmds.data_funcs import create_kv_store_cmd

    run(create_kv_store_cmd(rpc_port=data_rpc_port, table_string=table_string))


@data_cmd.command("get_value", short_help="Get a data row by its hash")
@create_key_option()
@create_kv_store_id_option()
@create_rpc_port_option()
def get_value(
    tree_id: str,
    key: str,
    data_rpc_port: int,
) -> None:
    from chia.cmds.data_funcs import get_value_cmd

    run(get_value_cmd(rpc_port=data_rpc_port, tree_id=tree_id, key=key))


@data_cmd.command("update_kv_store", short_help="Update a table.")
@create_kv_store_id_option()
@create_rpc_port_option()
@create_changelist_option()
def update_kv_store(
    tree_id: str,
    changelist_string: str,
    data_rpc_port: int,
) -> None:
    from chia.cmds.data_funcs import update_kv_store_cmd

    changelist = json.loads(changelist_string)

    run(update_kv_store_cmd(rpc_port=data_rpc_port, tree_id=tree_id, changelist=changelist))
