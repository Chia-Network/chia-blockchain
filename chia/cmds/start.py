from __future__ import annotations

import click

from chia.util.config import load_config
from chia.util.service_groups import all_groups


@click.command("start", help="Start service groups")
@click.option("-r", "--restart", is_flag=True, type=bool, help="Restart running services")
@click.argument("group", type=click.Choice(list(all_groups())), nargs=-1, required=True)
@click.pass_context
def start_cmd(ctx: click.Context, restart: bool, group: tuple[str, ...]) -> None:
    import asyncio

    from chia.cmds.beta_funcs import warn_if_beta_enabled

    from .start_funcs import async_start

    root_path = ctx.obj["root_path"]
    config = load_config(root_path, "config.yaml")
    warn_if_beta_enabled(config)
    asyncio.run(async_start(root_path, config, group, restart))
