from __future__ import annotations

import json
from typing import Optional

import click

from chia.cmds.cmd_classes import ChiaCliContext
from chia.cmds.dev.mempool_funcs import create_block_async, export_mempool_async, import_mempool_async


@click.group("mempool", help="Debug the mempool")
@click.pass_context
def mempool_cmd(ctx: click.Context) -> None:
    pass


@click.command("import", help="Import mempool items from a JSON file", no_args_is_help=True)
@click.option(
    "-p",
    "--rpc-port",
    help=(
        "Set the port where the Full Node is hosting the RPC interface. See the rpc_port under full_node in config.yaml"
    ),
    type=int,
    default=None,
)
@click.argument("path", type=str)
@click.pass_context
def import_mempool_cmd(ctx: click.Context, rpc_port: Optional[int], path: str) -> None:
    import asyncio

    with open(path) as file:
        source = file.read()

    content = json.loads(source)

    asyncio.run(import_mempool_async(rpc_port, ChiaCliContext.set_default(ctx).root_path, content))


@click.command("export", help="Export mempool items to a JSON file", no_args_is_help=True)
@click.option(
    "-p",
    "--rpc-port",
    help=(
        "Set the port where the Full Node is hosting the RPC interface. See the rpc_port under full_node in config.yaml"
    ),
    type=int,
    default=None,
)
@click.argument("path", type=str)
@click.pass_context
def export_mempool_cmd(ctx: click.Context, rpc_port: Optional[int], path: str) -> None:
    import asyncio

    asyncio.run(export_mempool_async(rpc_port, ChiaCliContext.set_default(ctx).root_path, path))


@click.command("create_block", help="Create a block bundle from the mempool, as if you farmed it")
@click.option(
    "-p",
    "--rpc-port",
    help=(
        "Set the port where the Full Node is hosting the RPC interface. See the rpc_port under full_node in config.yaml"
    ),
    type=int,
    default=None,
)
@click.pass_context
def create_block_cmd(ctx: click.Context, rpc_port: Optional[int]) -> None:
    import asyncio

    asyncio.run(create_block_async(rpc_port, ChiaCliContext.set_default(ctx).root_path))


mempool_cmd.add_command(import_mempool_cmd)
mempool_cmd.add_command(export_mempool_cmd)
mempool_cmd.add_command(create_block_cmd)
