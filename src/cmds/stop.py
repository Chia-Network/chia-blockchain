import asyncio
import sys
from pathlib import Path

import click

from src.daemon.client import connect_to_daemon_and_validate
from src.util.service_groups import all_groups, services_for_groups


async def async_stop(root_path: Path, group: str, stop_daemon: bool) -> int:
    daemon = await connect_to_daemon_and_validate(root_path)
    if daemon is None:
        print("couldn't connect to chia daemon")
        return 1

    if stop_daemon:
        r = await daemon.exit()
        await daemon.close()
        print(f"daemon: {r}")
        return 0

    return_val = 0

    for service in services_for_groups(group):
        print(f"{service}: ", end="", flush=True)
        if not await daemon.is_running(service_name=service):
            print("not running")
        elif await daemon.stop_service(service_name=service):
            print("stopped")
        else:
            print("stop failed")
            return_val = 1

    await daemon.close()
    return return_val


@click.command("stop", short_help="stop service groups")
@click.option("-d", "--daemon", is_flag=True, type=bool, help="Stop daemon")
@click.argument("group", type=click.Choice(all_groups()), nargs=-1, required=True)
@click.pass_context
def stop_cmd(ctx: click.Context, daemon: bool, group: str) -> None:
    sys.exit(asyncio.get_event_loop().run_until_complete(async_stop(ctx.obj["root_path"], group, daemon)))
