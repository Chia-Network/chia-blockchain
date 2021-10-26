import sys
from pathlib import Path

import click

from chia.util.service_groups import all_groups, services_for_groups


async def async_stop(root_path: Path, group: str, stop_daemon: bool) -> int:
    from chia.daemon.client import connect_to_daemon_and_validate

    daemon = await connect_to_daemon_and_validate(root_path)
    if daemon is None:
        print("Couldn't connect to sit daemon")
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
            print("Not running")
        elif await daemon.stop_service(service_name=service):
            print("Stopped")
        else:
            print("Stop failed")
            return_val = 1

    await daemon.close()
    return return_val


@click.command("stop", short_help="Stop services")
@click.option("-d", "--daemon", is_flag=True, type=bool, help="Stop daemon")
@click.argument("group", type=click.Choice(list(all_groups())), nargs=-1, required=True)
@click.pass_context
def stop_cmd(ctx: click.Context, daemon: bool, group: str) -> None:
    import asyncio

    sys.exit(asyncio.get_event_loop().run_until_complete(async_stop(ctx.obj["root_path"], group, daemon)))
