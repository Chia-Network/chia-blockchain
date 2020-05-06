import asyncio
import logging
import secrets

from aiter import map_aiter, server

from src.proxy.server import api_request, api_server
from src.util.config import load_config
from src.util.logging import initialize_logging

from .start_stop import start_service


log = logging.getLogger(__name__)


def socket_server_path(root_path):
    return root_path / "run" / "start-daemon.socket"


def socket_server_info_path(root_path):
    return root_path / "run" / "start-daemon.socket.info"


async def server_aiter_for_start_daemon(root_path):
    try:
        raise ValueError()
        socket_path = socket_server_path(root_path)
        s, aiter = await server.start_unix_server_aiter(path=socket_path)
        log.info("listening on %s", socket_path)
        return s, aiter
    except Exception as ex:
        pass

    try:
        # TODO: make this configurable
        socket_server_port = 62191
        s, aiter = await server.start_server_aiter(port=socket_server_port)
        log.info("listening on port %s", socket_server_port)
        return s, aiter
    except Exception as ex:
        pass
    return None


async def kill_and_wait(process, max_nice_wait=30):
    process.terminate()
    log.info("sending term signal to %s", process)
    count = 0
    while count < max_nice_wait:
        if process.poll() is not None:
            break
        await asyncio.sleep(1)
        count += 1
    else:
        process.kill()
        log.info("sending kill signal to %s", process)
    r = process.wait()
    log.info("process %s returned %d", process, r)
    return r


class Daemon:
    def __init__(self, root_path):
        self._root_path = root_path
        self._services = dict()

    async def start_service(self, service_name):
        if service_name in self._services:
            return "already_running"
        process, pid_path = start_service(self._root_path, service_name)
        self._services[service_name] = process
        return "did_start"

    async def stop_service(self, service_name):
        process = self._services.get(service_name)
        if process is None:
            return "not_running"
        del self._services[service_name]
        await kill_and_wait(process)
        return "is_stopped"

    async def is_running(self, service_name):
        process = self._services.get(service_name)
        return process is not None and process.poll() is None


async def run_daemon(root_path):
    config = load_config(root_path, "config.yaml")
    initialize_logging("daemon %(name)-25s", config["logging"], root_path)

    listen_socket, aiter = await server_aiter_for_start_daemon(root_path)

    rws_aiter = map_aiter(lambda rw: dict(reader=rw[0], writer=rw[1], server=listen_socket), aiter)

    daemon = Daemon(root_path)

    return await api_server(rws_aiter, daemon)


def main():
    from src.util.default_root import DEFAULT_ROOT_PATH
    return asyncio.get_event_loop().run_until_complete(run_daemon(DEFAULT_ROOT_PATH))


if __name__ == "__main__":
    main()
