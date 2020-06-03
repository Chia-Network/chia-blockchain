import asyncio
import os
import subprocess

from src.daemon.client import connect_to_daemon_and_validate
from src.util.service_groups import all_groups, services_for_groups


def make_parser(parser):

    parser.add_argument(
        "-r", "--restart", action="store_true", help="Restart of running processes",
    )
    parser.add_argument(
        "group", choices=all_groups(), type=str, nargs="+",
    )
    parser.set_defaults(function=start)


def launch_start_daemon(root_path):
    os.environ["CHIA_ROOT"] = str(root_path)
    # TODO: use startupinfo=subprocess.DETACHED_PROCESS on windows
    process = subprocess.Popen("chia run_daemon".split(), stdout=subprocess.PIPE)
    return process


async def create_start_daemon_connection(root_path):
    connection = await connect_to_daemon_and_validate(root_path)
    if connection is None:
        # launch a daemon
        process = launch_start_daemon(root_path)
        # give the daemon a chance to start up
        process.stdout.readline()
        # it prints "daemon: listening"
        connection = await connect_to_daemon_and_validate(root_path)
    if connection:
        return connection
    return None


async def async_start(args, parser):
    daemon = await create_start_daemon_connection(args.root_path)
    if daemon is None:
        print("failed to create the chia start daemon")
        return 1

    for service in services_for_groups(args.group):
        if await daemon.is_running(service_name=service):
            print(f"{service}: ", end="", flush=True)
            if args.restart:
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


def start(args, parser):
    return asyncio.get_event_loop().run_until_complete(async_start(args, parser))
