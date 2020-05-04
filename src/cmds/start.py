import os
import time
from typing import List

from .start_stop import (
    all_groups,
    pid_path_for_service,
    services_for_groups,
    start_service,
    stop_service,
)


def make_parser(parser):

    parser.add_argument(
        "group", choices=all_groups(), type=str, nargs="+",
    )
    parser.add_argument(
        "-r", "--restart", action="store_true", help="Restart of running processes",
    )
    parser.add_argument(
        "-f",
        "--force",
        action="store_true",
        help="Restart even if process seems to be running and it can't be stopped",
    )
    parser.set_defaults(function=start)


def start(args, parser):

    processes: List = []
    for service in services_for_groups(args.group):
        if pid_path_for_service(args.root_path, service).is_file():
            if args.restart or args.force:
                args.force=args.restart # Grubby hack to workaround can't restart
                print("restarting")
                stop_service(args.root_path, service)
                while (
                    pid_path_for_service(args.root_path, service).is_file()
                    and not args.force
                ):
                    # try to avoid race condition
                    # this is pretty hacky
                    time.sleep(1)
            else:
                print(
                    f"{service} seems to already be running, use `-r` to force restart"
                )
                continue
        process = start_service(args.root_path, service)
        processes.append(process)

    try:
        for process, pid_path in processes:
            process.wait()
    except KeyboardInterrupt:
        for process, pid_path in processes:
            process.kill()
    for process, pid_path in processes:
        try:
            process.wait()
            pid_path_killed = pid_path.with_suffix(".pid-killed")
            os.rename(pid_path, pid_path_killed)
        except Exception:
            pass
    if len(processes) > 0:
        print("chia start complete")
    return 0
