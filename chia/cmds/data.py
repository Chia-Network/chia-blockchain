import json
import logging
from typing import Any, Coroutine, Dict, Optional, TypeVar

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


@data_cmd.command("create_data_store", short_help="Get a data row by its hash")
@click.option("-f", "--fingerprint", help="Set the fingerprint to specify which wallet to use", type=int)
@create_rpc_port_option()
def create_data_store(
    # table_string: str,
    fingerprint: int,
    data_rpc_port: int,
) -> None:
    from chia.cmds.data_funcs import create_data_store_cmd

    run(create_data_store_cmd(data_rpc_port, ""))


@data_cmd.command("get_value", short_help="Get a data row by its hash")
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


@data_cmd.command("update_data_store", short_help="Update a table.")
@create_data_store_id_option()
@create_changelist_option()
@click.option("-f", "--fingerprint", help="Set the fingerprint to specify which wallet to use", type=int)
@create_rpc_port_option()
def update_data_store(
    id: str,
    changelist_string: str,
    fingerprint: int,
    data_rpc_port: int,
) -> None:
    from chia.cmds.data_funcs import update_data_store_cmd

    run(update_data_store_cmd(data_rpc_port, id, json.loads(changelist_string)))


@data_cmd.command("get_keys_values", short_help="")
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


@data_cmd.command("get_root", short_help="")
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


@data_cmd.command("subscribe", short_help="")
@create_data_store_id_option()
@click.option("-ip", "--ip", help="", type=str)
@click.option("-port", "--port", help="", type=int)
@create_rpc_port_option()
def subscribe(
    id: str,
    ip: str,
    port: int,
    data_rpc_port: int,
) -> None:
    from chia.cmds.data_funcs import subscribe_cmd

    run(subscribe_cmd(rpc_port=data_rpc_port, store_id=id, ip=ip, port=port))


@data_cmd.command("unsubscribe", short_help="")
@create_data_store_id_option()
@create_rpc_port_option()
def unsubscribe(
    id: str,
    data_rpc_port: int,
) -> None:
    from chia.cmds.data_funcs import unsubscribe_cmd

    run(unsubscribe_cmd(rpc_port=data_rpc_port, store_id=id))
