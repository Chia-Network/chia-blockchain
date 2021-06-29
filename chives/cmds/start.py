import click

from chia.util.service_groups import all_groups


@click.command("start", short_help="Start service groups")
@click.option("-r", "--restart", is_flag=True, type=bool, help="Restart running services")
@click.argument("group", type=click.Choice(all_groups()), nargs=-1, required=True)
@click.pass_context
def start_cmd(ctx: click.Context, restart: bool, group: str) -> None:
    import asyncio
    from .start_funcs import async_start

    asyncio.get_event_loop().run_until_complete(async_start(ctx.obj["root_path"], group, restart))
