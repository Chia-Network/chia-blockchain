from __future__ import annotations

from typing import Optional

import click

from chia.cmds.cmd_classes import ChiaCliContext


@click.group("solver", help="Manage your solver")
def solver_cmd() -> None:
    pass


@solver_cmd.command("get_state", help="Get current solver state")
@click.option(
    "-sp",
    "--solver-rpc-port",
    help="Set the port where the Solver is hosting the RPC interface. See the rpc_port under solver in config.yaml",
    type=int,
    default=None,
    show_default=True,
)
@click.pass_context
def get_state_cmd(
    ctx: click.Context,
    solver_rpc_port: Optional[int],
) -> None:
    import asyncio

    from chia.cmds.solver_funcs import get_state

    asyncio.run(get_state(ChiaCliContext.set_default(ctx), solver_rpc_port))
