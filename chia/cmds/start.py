import click

from chia.util.config import load_config
from chia.util.service_groups import all_groups


@click.command("start", short_help="Start service groups")
@click.option("-r", "--restart", is_flag=True, type=bool, help="Restart running services")
@click.argument("group", type=click.Choice(list(all_groups())), nargs=-1, required=True)
@click.pass_context
def start_cmd(ctx: click.Context, restart: bool, group: str) -> None:
    import asyncio
    from .start_funcs import async_start

    root_path = ctx.obj["root_path"]
    config = load_config(root_path, "config.yaml")
    asyncio.run(async_start(root_path, config, group, restart, ctx.obj["force_legacy_keyring_migration"]))
