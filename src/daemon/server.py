import asyncio
import logging
import os
import subprocess
import sys


from aiter import map_aiter, server

from src.proxy.server import api_server
from src.util.config import load_config
from src.util.logging import initialize_logging
from src.util.path import mkdir


log = logging.getLogger(__name__)


def socket_server_path(root_path):
    return root_path / "run" / "start-daemon.socket"


def socket_server_info_path(root_path):
    return root_path / "run" / "start-daemon.socket.info"


async def server_aiter_for_start_daemon(root_path):
    try:
        # for now, don't use unix sockets
        raise ValueError()
        socket_path = socket_server_path(root_path)
        s, aiter = await server.start_unix_server_aiter(path=socket_path)
        log.info("listening on %s", socket_path)
        return s, aiter, socket_path
    except Exception as ex:
        pass

    # TODO: make this configurable
    socket_server_port = 60191
    while socket_server_port < 65535:
        try:
            s, aiter = await server.start_server_aiter(port=socket_server_port)
            log.info("listening on port %s", socket_server_port)
            break
        except Exception as ex:
            pass
    else:
        raise RuntimeError("can't listen on socket")

    try:
        path = socket_server_info_path(root_path)
        mkdir(path.parent)
        with open(path, "w") as f:
            f.write(f"{socket_server_port}\n")
    except Exception as ex:
        raise RuntimeError(f"can't write to {path}")

    return s, aiter, path


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
        print(f"wrote pid to {pid_path}")
    except Exception:
        print(f"can't write PID file for {process} at {pid_path}")
    return process, pid_path
    return 0


class Daemon:
    def __init__(self, root_path, listen_socket):
        self._root_path = root_path
        self._listen_socket = listen_socket
        self._services = dict()

    async def start_service(self, service_name):
        if service_name in self._services:
            return "already_running"
        process, pid_path = start_service(self._root_path, service_name)
        self._services[service_name] = process
        return "did_start"

    async def stop_service(self, service_name, delay_before_kill=30):
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


async def async_run_daemon(root_path):
    config = load_config(root_path, "config.yaml")
    initialize_logging("daemon %(name)-25s", config["logging"], root_path)

    listen_socket, aiter, path = await server_aiter_for_start_daemon(root_path)

    rws_aiter = map_aiter(lambda rw: dict(reader=rw[0], writer=rw[1], server=listen_socket), aiter)

    daemon = Daemon(root_path, listen_socket)

    return await api_server(rws_aiter, daemon)


def run_daemon(root_path):
    return asyncio.get_event_loop().run_until_complete(async_run_daemon(root_path))


def main():
    from src.util.default_root import DEFAULT_ROOT_PATH
    return run_daemon(DEFAULT_ROOT_PATH)


if __name__ == "__main__":
    main()
