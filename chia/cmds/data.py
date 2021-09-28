import click


@click.group("data", short_help="Manage your data")
def data_cmd() -> None:
    pass


# TODO: maybe use more helpful `type=`s to get click to handle error reporting of
#       malformed inputs.


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
def create_table_cmd(
    table_string: str,
    table_name: str,
    data_rpc_port: int,
) -> None:
    import asyncio

    from chia.cmds.data_funcs import create_table

    asyncio.run(create_table(rpc_port=data_rpc_port, table_string=table_string, table_name=table_name))


@data_cmd.command("get_row", short_help="Get a data row by its hash")
@create_row_hash_option()
@create_table_option()
@create_rpc_port_option()
def get_row_cmd(
    row_hash_string: str,
    table_string: str,
    data_rpc_port: int,
) -> None:
    import asyncio

    from chia.cmds.data_funcs import get_row

    asyncio.run(get_row(rpc_port=data_rpc_port, table_string=table_string, row_hash_string=row_hash_string))


@data_cmd.command("insert_row", short_help="Insert a new row.")
@create_row_data_option()
@create_table_option()
@create_rpc_port_option()
def insert_row_cmd(
    row_data_string: str,
    table_string: str,
    data_rpc_port: int,
) -> None:
    import asyncio

    from chia.cmds.data_funcs import insert_row

    asyncio.run(insert_row(rpc_port=data_rpc_port, table_string=table_string, row_data_string=row_data_string))
