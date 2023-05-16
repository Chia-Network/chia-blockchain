from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any, Dict

import click

from chia.util.config import load_config
from chia.util.service_groups import all_groups, services_for_groups


async def async_stop(root_path: Path, config: Dict[str, Any], group: tuple[str, ...], stop_daemon: bool) -> int:
    from chia.daemon.client import connect_to_daemon_and_validate

    daemon = await connect_to_daemon_and_validate(root_path, config)
    if daemon is None:
        print("Couldn't connect to chia daemon")
        return 1

    if stop_daemon:
        r = await daemon.exit()
        await daemon.close()
        if r.get("data", {}).get("success", False):
            if r["data"].get("services_stopped") is not None:
                [print(f"{service}: Stopped") for service in r["data"]["services_stopped"]]
            await asyncio.sleep(1)  # just cosmetic
            print("Daemon stopped")
        else:
            print(f"Stop daemon failed {r}")
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


@click.command("stop", help="Stop services")
@click.option("-d", "--daemon", is_flag=True, type=bool, help="Stop daemon")
@click.argument("group", type=click.Choice(list(all_groups())), nargs=-1, required=True)
@click.pass_context
def stop_cmd(ctx: click.Context, daemon: bool, group: tuple[str, ...]) -> None:
    from chia.cmds.beta_funcs import warn_if_beta_enabled

    root_path = ctx.obj["root_path"]
    config = load_config(root_path, "config.yaml")
    warn_if_beta_enabled(config)

    sys.exit(asyncio.run(async_stop(root_path, config, group, daemon)))
