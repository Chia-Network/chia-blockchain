import os
import signal
import subprocess

from src.util.path import mkdir

SERVICES_FOR_GROUP = {
    "all": "chia_harvester chia_timelord chia_timelord_launcher chia_farmer chia_full_node".split(),
    "node": "chia_full_node".split(),
    "harvester": "chia_harvester".split(),
    "farmer": "chia_harvester chia_farmer chia_full_node".split(),
    "timelord": "chia_timelord chia_timelord_launcher chia_full_node".split(),
    "wallet": ["npm run --prefix ./electron-ui start"],
    "wallet-server": "chia-wallet".split(),
    "introducer": "chia_introducer".split(),
}


def pid_path_for_service(root_path, service):
    pid_name = service.replace(" ", "-").replace("/", "-")
    return root_path / "run" / f"{pid_name}.pid"


def all_groups():
    return SERVICES_FOR_GROUP.keys()


def services_for_groups(groups):
    for group in groups:
        for service in SERVICES_FOR_GROUP[group]:
            yield service


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


def find_kill_signal():
    for signal_name in "SIGHUP CTRL_C_EVENT".split():
        try:
            return getattr(signal, signal_name)
        except AttributeError:
            pass
    raise RuntimeError("can't find a kill signal")


def stop_service(root_path, service):
    kill_signal = find_kill_signal()
    try:
        pid_path = pid_path_for_service(root_path, service)
        with open(pid_path) as f:
            pid = int(f.readline())
        print(f"sending signal to pid {pid:>5} for {service}")
        try:
            os.kill(pid, kill_signal)
        except Exception:
            print(f"can't kill {pid} for {service}, is it running?")
    except Exception:
        print(f"can't open PID file {pid_path} for {service}, is it running?")
        return 1
    return 0
