import asyncio
import os
import subprocess
from pathlib import Path
from typing import Optional

import click

from src.daemon.client import DaemonProxy, connect_to_daemon_and_validate
from src.util.service_groups import all_groups, services_for_groups


def launch_start_daemon(root_path: Path) -> subprocess.Popen:
    os.environ["CHIA_ROOT"] = str(root_path)
    # TODO: use startupinfo=subprocess.DETACHED_PROCESS on windows
    process = subprocess.Popen("chia run_daemon".split(), stdout=subprocess.PIPE)
    return process


async def create_start_daemon_connection(root_path: Path) -> Optional[DaemonProxy]:
    connection = await connect_to_daemon_and_validate(root_path)
    if connection is None:
        print("Starting daemon")
        # launch a daemon
        process = launch_start_daemon(root_path)
        # give the daemon a chance to start up
        if process.stdout:
            process.stdout.readline()
        await asyncio.sleep(1)
        # it prints "daemon: listening"
        connection = await connect_to_daemon_and_validate(root_path)
    if connection:
        return connection
    return None


async def async_start(root_path: Path, group: str, restart: bool) -> None:
    daemon = await create_start_daemon_connection(root_path)
    if daemon is None:
        print("failed to create the chia start daemon")
        return

    for service in services_for_groups(group):
        if await daemon.is_running(service_name=service):
            print(f"{service}: ", end="", flush=True)
            if restart:
                if not await daemon.is_running(service_name=service):
                    print("not running")
                elif await daemon.stop_service(service_name=service):
                    print("stopped")
                else:
                    print("stop failed")
            else:
                print("already running, use `-r` to restart")
                continue
        print(f"{service}: ", end="", flush=True)
        msg = await daemon.start_service(service_name=service)
        success = msg["data"]["success"]

        if success is True:
            print("started")
        else:
            error = msg["data"]["error"]
            print(f"{service} failed to start. Error: {error}")
    await daemon.close()


@click.command("start", short_help="start service groups")
@click.option("-r", "--restart", is_flag=True, type=bool, help="Restart of running processes")
@click.argument("group", type=click.Choice(all_groups()), nargs=-1, required=True)
@click.pass_context
def start_cmd(ctx: click.Context, restart: bool, group: str) -> None:
    asyncio.get_event_loop().run_until_complete(async_start(ctx.obj["root_path"], group, restart))
