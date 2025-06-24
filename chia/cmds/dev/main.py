from __future__ import annotations

import click

from chia.cmds.dev.data import data_group
from chia.cmds.dev.gh import gh_group
from chia.cmds.dev.installers import installers_group
from chia.cmds.dev.mempool import mempool_cmd
from chia.cmds.dev.sim import sim_cmd


@click.group("dev", help="Developer commands and tools")
@click.pass_context
def dev_cmd(ctx: click.Context) -> None:
    pass


dev_cmd.add_command(sim_cmd)
dev_cmd.add_command(installers_group)
dev_cmd.add_command(gh_group)
dev_cmd.add_command(mempool_cmd)
dev_cmd.add_command(data_group)
