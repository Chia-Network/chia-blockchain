import asyncio
import logging
import os
import subprocess
import sys

try:
    import fcntl
except ImportError:
    fcntl = None


from aiter import map_aiter, server

from src.proxy.server import api_server
from src.util.config import load_config
from src.util.logging import initialize_logging
from src.util.path import mkdir

from .client import (
    connect_to_daemon_and_validate,
    socket_server_path,
    should_use_unix_socket,
)

log = logging.getLogger(__name__)


def daemon_launch_lock_path(root_path):
    return root_path / "run" / "start-daemon.launching"


async def _listen_on_some_socket(port, max_port=65536):
    """
    Return a socket that we are listening on in the given port range
    """
    while port < max_port:
        try:
            s, aiter = await server.start_server_aiter(port=port)
            log.info("listening on port %s", port)
            return s, aiter, port
        except Exception as ex:
            port += 1
    raise RuntimeError("can't listen on socket")


async def _server_aiter_for_start_daemon(root_path, use_unix_socket):
    path = socket_server_path(root_path)
    mkdir(path.parent)
    try:
        if use_unix_socket:
            if not path.is_socket():
                path.unlink()
            s, aiter = await server.start_unix_server_aiter(path=path)
            log.info("listening on %s", path)
            where = path
        else:
            s, aiter, socket_server_port = await _listen_on_some_socket(60191, 62000)
            try:
                with open(path, "w") as f:
                    f.write(f"{socket_server_port}\n")
                where = socket_server_port
            except Exception as ex:
                raise RuntimeError(f"can't write to {path}")

        return s, aiter, where

    except Exception as ex:
        log.exception("can't create a listen socket for chia daemon")
        raise


def pid_path_for_service(root_path, service):
    pid_name = service.replace(" ", "-").replace("/", "-")
    return root_path / "run" / f"{pid_name}.pid"


def start_service(root_path, service):
    # set up CHIA_ROOT
    # invoke correct script
    # save away PID

    # we need to pass on the possibly altered CHIA_ROOT
    os.environ["CHIA_ROOT"] = str(root_path)

    process = subprocess.Popen(service.split(), shell=False)
    pid_path = pid_path_for_service(root_path, service)
    try:
        mkdir(pid_path.parent)
        with open(pid_path, "w") as f:
            f.write(f"{process.pid}\n")
    except Exception:
        pass
    return process, pid_path


class Daemon:
    def __init__(self, root_path, listen_socket):
        self._root_path = root_path
        self._listen_socket = listen_socket
        self._services = dict()

    async def start_service(self, service_name):
        if service_name in self._services:
            return "already running"
        process, pid_path = start_service(self._root_path, service_name)
        self._services[service_name] = process
        return "started"

    async def stop_service(self, service_name, delay_before_kill=15):
        process = self._services.get(service_name)
        if process is None:
            return "not_running"
        del self._services[service_name]
        pid_path = pid_path_for_service(self._root_path, service_name)

        log.info("sending term signal to %s", service_name)
        process.terminate()
        # on Windows, process.kill and process.terminate are the same,
        # so no point in trying process.kill later
        if process.kill != process.terminate:
            count = 0
            while count < delay_before_kill:
                if process.poll() is not None:
                    break
                await asyncio.sleep(1)
                count += 1
            else:
                process.kill()
                log.info("sending kill signal to %s", service_name)
        r = process.wait()
        log.info("process %s returned %d", process, r)
        try:
            pid_path_killed = pid_path.with_suffix(".pid-killed")
            os.rename(pid_path, pid_path_killed)
        except Exception:
            pass

        return "is_stopped"

    async def is_running(self, service_name):
        process = self._services.get(service_name)
        return process is not None and process.poll() is None

    async def exit(self):
        jobs = []
        for k in self._services.keys():
            jobs.append(self.stop_service(k))
        if jobs:
            done, pending = await asyncio.wait(jobs)
        self._services.clear()
        self._listen_socket.close()
        # TODO: fix this hack
        asyncio.get_event_loop().call_later(5, lambda *args: sys.exit(0))
        log.info("chia daemon exiting in 5 seconds")
        return "exiting"

    async def ping(self):
        return "pong"


def singleton(lockfile, text="semaphore"):
    """
    Open a lockfile exclusively.
    """
    try:
        if fcntl:
            f = open(lockfile, "w")
            fcntl.lockf(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        else:
            fd = os.open(lockfile, os.O_CREAT | os.O_EXCL | os.O_RDWR)
            f = open(fd, "w")
        f.write(text)
        return f
    except IOError:
        return None
    return f


async def async_run_daemon(root_path):
    config = load_config(root_path, "config.yaml")
    initialize_logging("daemon %(name)-25s", config["logging"], root_path)

    connection = await connect_to_daemon_and_validate(root_path)
    if connection is not None:
        print("daemon: already running")
        return 1

    lockfile = singleton(daemon_launch_lock_path(root_path))
    if lockfile is None:
        print("daemon: already launching")
        return 2

    use_unix_socket = should_use_unix_socket()
    listen_socket, aiter, where = await _server_aiter_for_start_daemon(root_path, use_unix_socket)

    rws_aiter = map_aiter(
        lambda rw: dict(reader=rw[0], writer=rw[1], server=listen_socket), aiter
    )

    daemon = Daemon(root_path, listen_socket)

    print(f"daemon: listening on {where}", flush=True)

    return await api_server(rws_aiter, daemon)


def run_daemon(root_path):
    return asyncio.get_event_loop().run_until_complete(async_run_daemon(root_path))


def main():
    from src.util.default_root import DEFAULT_ROOT_PATH
    return run_daemon(DEFAULT_ROOT_PATH)


if __name__ == "__main__":
    main()
