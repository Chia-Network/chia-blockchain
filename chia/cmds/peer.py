from typing import Optional
import click
from chia.cmds.peer_funcs import peer_async
from chia.cmds.show_funcs import execute_with_node


@click.command("peer", short_help="Show, or modify peering connections", no_args_is_help=True)
@click.option(
    "-p",
    "--rpc-port",
    help=(
        "Set the port where the Selected Node is hosting the RPC interface. "
        "See the rpc_port under full_node in config.yaml"
    ),
    type=int,
    default=None,
)
@click.option(
    "-c", "--connections", help="List nodes connected to this Full Node", is_flag=True, type=bool, default=False
)
@click.option("-a", "--add-connection", help="Connect to another Full Node by ip:port", type=str, default="")
@click.option(
    "-r", "--remove-connection", help="Remove a Node by the first 8 characters of NodeID", type=str, default=""
)
@click.pass_context
def peer_cmd(
    ctx: click.Context,
    rpc_port: Optional[int],
    connections: bool,
    add_connection: str,
    remove_connection: str,
) -> None:
    import asyncio

    asyncio.run(
        execute_with_node(
            rpc_port,
            peer_async,
            ctx.obj["root_path"],
            connections,
            add_connection,
            remove_connection,
        )
    )
