import os
import signal
import subprocess
import sys

from pathlib import Path
from typing import Tuple

from chia.daemon.server import pid_path_for_service
from chia.util.path import mkdir


def launch_service(root_path: Path, service_command) -> Tuple[subprocess.Popen, Path]:
    """
    Launch a child process.
    """
    # set up CHIA_ROOT
    # invoke correct script
    # save away PID

    # we need to pass on the possibly altered CHIA_ROOT
    os.environ["CHIA_ROOT"] = str(root_path)

    print(f"Launching service with CHIA_ROOT: {os.environ['CHIA_ROOT']}")

    # Insert proper e
    service_array = service_command.split()
    service_executable = executable_for_service(service_array[0])
    service_array[0] = service_executable

    startupinfo = None
    if os.name == "nt":
        startupinfo = subprocess.STARTUPINFO()  # type: ignore
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW  # type: ignore

    # CREATE_NEW_PROCESS_GROUP allows graceful shutdown on windows, by CTRL_BREAK_EVENT signal
    if sys.platform == "win32" or sys.platform == "cygwin":
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        creationflags = 0
    environ_copy = os.environ.copy()
    process = subprocess.Popen(
        service_array, shell=False, startupinfo=startupinfo, creationflags=creationflags, env=environ_copy
    )
    pid_path = pid_path_for_service(root_path, service_command)
    try:
        mkdir(pid_path.parent)
        with open(pid_path, "w") as f:
            f.write(f"{process.pid}\n")
    except Exception:
        pass
    return process, pid_path


def kill_service(root_path: Path, service_name: str) -> bool:
    pid_path = pid_path_for_service(root_path, service_name)

    try:
        with open(pid_path) as f:
            pid = int(f.read())

        # @TODO SIGKILL seems necessary right now for the DNS server, but not the crawler (fix that)
        # @TODO Ensure processes stop before renaming the files and returning
        os.kill(pid, signal.SIGKILL)
        print("sent SIGKILL to process")
    except Exception:
        pass

    try:
        pid_path_killed = pid_path.with_suffix(".pid-killed")
        if pid_path_killed.exists():
            pid_path_killed.unlink()
        os.rename(pid_path, pid_path_killed)
    except Exception:
        pass

    return True


# determine if application is a script file or frozen exe
if getattr(sys, "frozen", False):
    name_map = {
        "chia_seeder": "chia_seeder",
        "chia_seeder_crawler": "chia_seeder_crawler",
        "chia_seeder_server": "chia_seeder_server",
    }

    def executable_for_service(service_name: str) -> str:
        application_path = os.path.dirname(sys.executable)
        if sys.platform == "win32" or sys.platform == "cygwin":
            executable = name_map[service_name]
            path = f"{application_path}/{executable}.exe"
            return path
        else:
            path = f"{application_path}/{name_map[service_name]}"
            return path


else:
    application_path = os.path.dirname(__file__)

    def executable_for_service(service_name: str) -> str:
        return service_name
