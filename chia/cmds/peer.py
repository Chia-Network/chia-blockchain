from __future__ import annotations

from typing import Optional

import click

from chia.cmds.cmds_util import NODE_TYPES
from chia.cmds.peer_funcs import peer_async


@click.command("peer", help="Show, or modify peering connections", no_args_is_help=True)
@click.option(
    "-p",
    "--rpc-port",
    help=(
        "Set the port where the farmer, wallet, full node or harvester "
        "is hosting the RPC interface. See the rpc_port in config.yaml"
    ),
    type=int,
    default=None,
)
@click.option(
    "-c", "--connections", help="List connections to the specified service", is_flag=True, type=bool, default=False
)
@click.option("-a", "--add-connection", help="Connect specified Chia service to ip:port", type=str, default="")
@click.option(
    "-r", "--remove-connection", help="Remove a Node by the first 8 characters of NodeID", type=str, default=""
)
@click.argument("node_type", type=click.Choice(list(NODE_TYPES.keys())), nargs=1, required=True)
@click.pass_context
def peer_cmd(
    ctx: click.Context,
    rpc_port: Optional[int],
    connections: bool,
    add_connection: str,
    remove_connection: str,
    node_type: str,
) -> None:
    import asyncio

    asyncio.run(
        peer_async(
            node_type,
            rpc_port,
            ctx.obj["root_path"],
            connections,
            add_connection,
            remove_connection,
        )
    )
