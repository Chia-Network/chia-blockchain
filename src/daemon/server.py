import asyncio
import logging
import os
import subprocess
import sys

try:
    import fcntl
    has_fcntl = True
except ImportError:
    has_fcntl = False

from aiohttp import web

from src.util.config import load_config
from src.util.logging import initialize_logging
from src.util.path import mkdir
from src.util.service_groups import validate_service

from .client import (
    connect_to_daemon_and_validate,
    socket_server_path,
    should_use_unix_socket,
)

log = logging.getLogger(__name__)


def daemon_launch_lock_path(root_path):
    """
    A path to a file that is lock when a daemon is launching but not yet started.
    This prevents multiple instances from launching.
    """
    return root_path / "run" / "start-daemon.launching"


def pid_path_for_service(root_path, service):
    """
    Generate a path for a PID file for the given service name.
    """
    pid_name = service.replace(" ", "-").replace("/", "-")
    return root_path / "run" / f"{pid_name}.pid"


def launch_service(root_path, service):
    """
    Launch a child process.
    """
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


async def kill_service(root_path, services, service_name, delay_before_kill=15):
    process = services.get(service_name)
    if process is None:
        return 0
    del services[service_name]
    pid_path = pid_path_for_service(root_path, service_name)

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
        if pid_path_killed.exists():
            pid_path_killed.unlink()
        os.rename(pid_path, pid_path_killed)
    except Exception:
        pass

    return 1


def create_server_for_daemon(root_path):
    routes = web.RouteTableDef()

    services = dict()

    @routes.get('/daemon/ping/')
    async def ping(request):
        return web.Response(text="pong")

    @routes.get('/daemon/service/start/')
    async def start_service(request):
        service_name = request.query.get("service")

        if not validate_service(service_name):
            r = "unknown service"
            return web.Response(text=str(r))

        if service_name in services:
            r = "already running"
            return web.Response(text=str(r))

        try:
            process, pid_path = launch_service(root_path, service_name)
            services[service_name] = process
            r = "started"
        except (subprocess.SubprocessError, IOError):
            log.exception(f"problem starting {service_name}")
            r = "start failed"

        return web.Response(text=str(r))

    @routes.get('/daemon/service/stop/')
    async def stop_service(request):
        service_name = request.query.get("service")
        r = await kill_service(root_path, services, service_name)
        return web.Response(text=str(r))

    @routes.get('/daemon/service/is_running/')
    async def is_running(request):
        service_name = request.query.get("service")
        process = services.get(service_name)
        r = process is not None and process.poll() is None
        return web.Response(text=str(r))

    @routes.get('/daemon/exit/')
    async def exit(request):

        jobs = []
        for k in services.keys():
            jobs.append(kill_service(root_path, services, k))
        if jobs:
            done, pending = await asyncio.wait(jobs)
        services.clear()

        # TODO: fix this hack
        asyncio.get_event_loop().call_later(5, lambda *args: sys.exit(0))
        log.info("chia daemon exiting in 5 seconds")
        r = "exiting"
        return web.Response(text=str(r))

    app = web.Application()
    app.add_routes(routes)
    return app


def singleton(lockfile, text="semaphore"):
    """
    Open a lockfile exclusively.
    """
    try:
        if has_fcntl:
            f = open(lockfile, "w")
            fcntl.lockf(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        else:
            if lockfile.exists():
                lockfile.unlink()
            fd = os.open(lockfile, os.O_CREAT | os.O_EXCL | os.O_RDWR)
            f = open(fd, "w")
        f.write(text)
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

    # TODO: clean this up, ensuring lockfile isn't removed until the listen port is open
    app = create_server_for_daemon(root_path)

    path = socket_server_path(root_path)
    mkdir(path.parent)

    port = 60191
    while True:
        try:
            path = socket_server_path(root_path)
            mkdir(path.parent)
            if path.exists():
                path.unlink()
            if should_use_unix_socket():
                where = path
                kwargs = dict(path=str(path))
            else:
                with open(path, "w") as f:
                    f.write(f"{port}\n")
                where = port
                kwargs = dict(port=port, host="127.0.0.1")
            task = web._run_app(app, print=None, **kwargs)
            lockfile.close()
            print(f"daemon: listening on {where}", flush=True)
            break
        except Exception:
            port += 1

    await task


def run_daemon(root_path):
    return asyncio.get_event_loop().run_until_complete(async_run_daemon(root_path))


def main():
    from src.util.default_root import DEFAULT_ROOT_PATH
    return run_daemon(DEFAULT_ROOT_PATH)


if __name__ == "__main__":
    main()
