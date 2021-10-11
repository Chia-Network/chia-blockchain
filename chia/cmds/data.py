import json
from typing import Coroutine

import click


# TODO: this is more general and should be part of refactoring the overall CLI code duplication
def run(coro: Coroutine):
    import asyncio

    response = asyncio.run(coro)

    success = response is not None and response.get("success", False)

    if not success:
        raise click.ClickException(message=f"query unsuccessful, response: {response}")


@click.group("data", short_help="Manage your data")
def data_cmd() -> None:
    pass


# TODO: maybe use more helpful `type=`s to get click to handle error reporting of
#       malformed inputs.


def create_changelist_option():
    return click.option(
        "-d",
        "--changelist",
        "changelist_string",
        help="str representing the changelist",
        type=str,
        required=True,
    )


def create_row_data_option():
    return click.option(
        "-d",
        "--row_data",
        "row_data_string",
        help="The hexadecimal row data.",
        type=str,
        required=True,
    )


def create_row_hash_option():
    return click.option(
        "-h",
        "--row_hash",
        "row_hash_string",
        help="The hexadecimal row hash.",
        type=str,
        required=True,
    )


def create_table_option():
    return click.option(
        "-t",
        "--table",
        "table_string",
        help="The hexadecimal table ID.",
        type=str,
        required=True,
    )


def create_table_name_option():
    return click.option(
        "-n",
        "--table_name",
        "table_name",
        help="The name of the table.",
        type=str,
        required=True,
    )


def create_rpc_port_option():
    return click.option(
        "-dp",
        "--data-rpc-port",
        help="Set the port where the Farmer is hosting the RPC interface. See the rpc_port under farmer in config.yaml",
        type=int,
        default=None,
        show_default=True,
    )


@data_cmd.command("create_table", short_help="Get a data row by its hash")
@create_table_option()
@create_table_name_option()
@create_rpc_port_option()
def create_table(
    table_string: str,
    data_rpc_port: int,
) -> None:
    from chia.cmds.data_funcs import create_kv_store_cmd

    run(create_kv_store_cmd(rpc_port=data_rpc_port, table_string=table_string))


@data_cmd.command("get_row", short_help="Get a data row by its hash")
@create_row_hash_option()
@create_table_option()
@create_rpc_port_option()
def get_row(
    tree_id: str,
    key: str,
    data_rpc_port: int,
) -> None:
    from chia.cmds.data_funcs import get_value_cmd

    run(get_value_cmd(rpc_port=data_rpc_port, tree_id=tree_id, key=key))


@data_cmd.command("update_table", short_help="Update a table.")
@create_table_option()
@create_rpc_port_option()
@create_changelist_option()
def update_table(
    tree_id: str,
    changelist_string: str,
    data_rpc_port: int,
) -> None:
    from chia.cmds.data_funcs import update_kv_store

    changelist = json.loads(changelist_string)

    run(update_kv_store(rpc_port=data_rpc_port, tree_id=tree_id, changelist=changelist))
