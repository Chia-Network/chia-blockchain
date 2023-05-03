from __future__ import annotations

from typing import Optional

import click

from chia.cmds.show_funcs import show_async


@click.command("show", help="Show node information", no_args_is_help=True)
@click.option(
    "-p",
    "--rpc-port",
    help=(
        "Set the port where the Full Node is hosting the RPC interface. "
        "See the rpc_port under full_node in config.yaml"
    ),
    type=int,
    default=None,
)
@click.option(
    "-wp",
    "--wallet-rpc-port",
    help="Set the port where the Wallet is hosting the RPC interface. See the rpc_port under wallet in config.yaml",
    type=int,
    default=None,
)
@click.option("-f", "--fee", help="Show the fee information", is_flag=True, type=bool, default=False)
@click.option("-s", "--state", help="Show the current state of the blockchain", is_flag=True, type=bool, default=False)
@click.option(
    "-c", "--connections", help="List nodes connected to this Full Node", is_flag=True, type=bool, default=False
)
@click.option("-a", "--add-connection", help="Connect to another Full Node by ip:port", type=str, default="")
@click.option(
    "-r", "--remove-connection", help="Remove a Node by the first 8 characters of NodeID", type=str, default=""
)
@click.option("-bh", "--block-header-hash-by-height", help="Look up a block header hash by block height", type=int)
@click.option("-b", "--block-by-header-hash", help="Look up a block by block header hash", type=str, default="")
@click.pass_context
def show_cmd(
    ctx: click.Context,
    rpc_port: Optional[int],
    wallet_rpc_port: Optional[int],
    fee: bool,
    state: bool,
    connections: bool,
    add_connection: str,
    remove_connection: str,
    block_header_hash_by_height: Optional[int],
    block_by_header_hash: str,
) -> None:
    import asyncio

    if connections:
        print("'chia show -c' has been renamed to 'chia peer -c' ")
    if add_connection != "":
        print("'chia show -a' has been renamed to 'chia peer -a' ")
    if remove_connection != "":
        print("'chia show -r' has been renamed to 'chia peer -r' ")
    if wallet_rpc_port is not None:
        print("'chia show -wp' is not used, please remove it from your command.")
    asyncio.run(
        show_async(
            rpc_port,
            ctx.obj["root_path"],
            fee,
            state,
            block_header_hash_by_height,
            block_by_header_hash,
        )
    )
