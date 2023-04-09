import click

from chia.cmds.sim import sim_cmd


@click.group("dev", short_help="Developer commands and tools")
@click.pass_context
def dev_cmd(ctx: click.Context) -> None:
    pass


dev_cmd.add_command(sim_cmd)
