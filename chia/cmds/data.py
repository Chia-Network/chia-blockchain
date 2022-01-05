import json
import logging
from typing import Any, Coroutine, Dict, Optional, TYPE_CHECKING

import click


if TYPE_CHECKING:
    # Will be located here in the next mypy release
    # from _typeshed import IdentityFunction
    from click.decorators import _IdentityFunction as IdentityFunction


logger = logging.getLogger(__name__)


# # TODO: this is more general and should be part of refactoring the overall CLI code duplication
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
        "-k",
        "--key",
        help="value key string.",
        type=str,
        required=True,
    )


def create_kv_store_id_option() -> "IdentityFunction":
    return click.option(
        "-store",
        "--id",
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
        "-wp",
        "--data_rpc_port",
        help="Set the port where the Wallet is hosting the RPC interface. See the rpc_port under wallet in config.yaml",
        type=int,
        default=None,
        show_default=True,
    )


@data_cmd.command("create_kv_store", short_help="Get a data row by its hash")
@click.option("-f", "--fingerprint", help="Set the fingerprint to specify which wallet to use", type=int)
@create_rpc_port_option()
def create_kv_store(
    # table_string: str,
    fingerprint: int,
    data_rpc_port: int,
) -> None:
    from chia.cmds.data_funcs import create_kv_store_cmd
    run(create_kv_store_cmd(fingerprint, data_rpc_port))


@data_cmd.command("update_kv_store", short_help="Update a table.")
@create_kv_store_id_option()
@create_changelist_option()
@click.option("-f", "--fingerprint", help="Set the fingerprint to specify which wallet to use", type=int)
@create_rpc_port_option()
def update_kv_store(
    id: str,
    changelist_string: str,
    fingerprint: int,
    data_rpc_port: int,
) -> None:
    from chia.cmds.data_funcs import update_kv_store_cmd
    run(update_kv_store_cmd(id, json.loads(changelist_string), fingerprint, data_rpc_port))


@data_cmd.command("get_value", short_help="Get a data row by its hash")
@create_kv_store_id_option()
@create_key_option()
@click.option("-f", "--fingerprint", help="Set the fingerprint to specify which wallet to use", type=int)
@create_rpc_port_option()
def get_value(
    id: str,
    key: str,
    fingerprint: int,
    data_rpc_port: int,
) -> None:
    from chia.cmds.data_funcs import get_value_cmd
    run(get_value_cmd(id, key, fingerprint, data_rpc_port))

