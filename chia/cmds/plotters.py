from __future__ import annotations

import click

from chia.cmds.cmd_classes import ChiaCliContext
from chia.plotters.plotters import call_plotters


@click.command(
    "plotters",
    help="Advanced plotting options",
    context_settings={"ignore_unknown_options": True},
    add_help_option=False,
)
@click.pass_context
@click.argument("args", nargs=-1)
def plotters_cmd(ctx: click.Context, args: tuple[click.Argument]) -> None:
    call_plotters(ChiaCliContext.set_default(ctx).root_path, args)
