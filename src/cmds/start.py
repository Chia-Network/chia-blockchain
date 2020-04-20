import os
import subprocess
from typing import List


SCRIPTS_FOR_SERVICE = {
    "all": "chia_harvester chia_timelord chia_timelord_launcher chia_farmer chia_full_node".split(),
    "node": "chia_full_node".split(),
    "farmer": "chia_harvester chia_farmer chia_full_node".split(),
    "timelord": "chia_timelord chia_timelord_launcher chia_full_node".split(),
    "wallet": ["npm run --prefix ./electron-ui start", "chia-wallet"],
    "introducer": "chia_introducer".split(),
}

SCRIPTS_FOR_SERVICE["wallet-gui"] = SCRIPTS_FOR_SERVICE["wallet"][:1]
SCRIPTS_FOR_SERVICE["wallet-server"] = SCRIPTS_FOR_SERVICE["wallet"][1:]


def make_parser(parser):

    parser.add_argument(
        "service", choices=SCRIPTS_FOR_SERVICE.keys(), type=str, nargs="+",
    )
    parser.set_defaults(function=start)


def start(args, parser):
    if len(args.service) == 0:
        parser.print_help()
        return 1

    processes: List = []
    for service in args.service:
        processes.extend(start_service(args.root_path, service))

    try:
        for process in processes:
            process.wait()
    except KeyboardInterrupt:
        for process in processes:
            process.kill()
    print("Chia start script finished killing servers.")
    for process in processes:
        process.wait()
    return 0


def start_service(root_path, service):
    # set up CHIA_ROOT
    # invoke correct script
    # save away PID
    processes = []

    # we need PATH to find commands in the virtual env
    # and we need to pass on the possibly altered CHIA_ROOT
    os.environ["CHIA_ROOT"] = str(root_path)

    for script in SCRIPTS_FOR_SERVICE[service]:
        process = subprocess.Popen(script.split())
        processes.append(process)
    return processes
