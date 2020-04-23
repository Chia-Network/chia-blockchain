import os
import subprocess
from typing import List

from src.util.path import mkdir

SERVICES_FOR_GROUP = {
    "all": "chia_harvester chia_timelord chia_timelord_launcher chia_farmer chia_full_node".split(),
    "node": "chia_full_node".split(),
    "farmer": "chia_harvester chia_farmer chia_full_node".split(),
    "timelord": "chia_timelord chia_timelord_launcher chia_full_node".split(),
    "wallet": ["npm run --prefix ./electron-ui start", "chia-wallet"],
    "introducer": "chia_introducer".split(),
}

SERVICES_FOR_GROUP["wallet-gui"] = SERVICES_FOR_GROUP["wallet"][:1]
SERVICES_FOR_GROUP["wallet-server"] = SERVICES_FOR_GROUP["wallet"][1:]


def make_parser(parser):

    parser.add_argument(
        "group", choices=SERVICES_FOR_GROUP.keys(), type=str, nargs="+",
    )
    parser.set_defaults(function=start)


def start(args, parser):
    processes: List = []
    for group in args.group:
        for service in SERVICES_FOR_GROUP[group]:
            processes.append(start_service(args.root_path, service))

    try:
        for process, pid_path in processes:
            process.wait()
    except KeyboardInterrupt:
        for process, pid_path in processes:
            process.kill()
    print("Chia start script finished killing servers.")
    for process, pid_path in processes:
        process.wait()
        try:
            pid_path_killed = pid_path.with_suffix(".pid-killed")
            os.rename(pid_path, pid_path_killed)
        except Exception:
            pass
    return 0


def pid_path_for_service(root_path, service):
    return root_path / "run" / f"{service}.pid"


def start_service(root_path, service):
    # set up CHIA_ROOT
    # invoke correct script
    # save away PID

    # we need to pass on the possibly altered CHIA_ROOT
    os.environ["CHIA_ROOT"] = str(root_path)

    process = subprocess.Popen(service, shell=True)
    pid_path = pid_path_for_service(root_path, service)
    try:
        mkdir(pid_path.parent)
        with open(pid_path, "w") as f:
            f.write(f"{process.pid}\n")
        print(f"wrote pid to {pid_path}")
    except Exception:
        print(f"can't write PID file for {process} at {pid_path}")
    return process, pid_path
