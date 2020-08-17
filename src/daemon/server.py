import asyncio
import json
import logging
import os
import signal
import subprocess
import sys
import traceback
from typing import Dict, Any, List
from sys import platform
from aiohttp import web


import websockets
from src.cmds.init import chia_init

from src.util.ws_message import format_response
from src.util.json_util import dict_to_json_str

try:
    import fcntl

    has_fcntl = True
except ImportError:
    has_fcntl = False

from src.util.config import load_config
from src.util.logging import initialize_logging
from src.util.path import mkdir
from src.util.service_groups import validate_service

log = logging.getLogger(__name__)

# determine if application is a script file or frozen exe
if getattr(sys, "frozen", False):
    name_map = {
        "chia": "chia",
        "chia_wallet": "start_wallet",
        "chia_full_node": "start_full_node",
        "chia_harvester": "start_harvester",
        "chia_farmer": "start_farmer",
        "chia_introducer": "start_introducer",
        "chia_timelord": "start_timelord",
        "chia_timelord_launcher": "timelord_launcher",
        "chia_full_node_simulator": "start_simulator",
    }

    def executable_for_service(service_name):
        application_path = os.path.dirname(sys.executable)
        if platform == "win32" or platform == "cygwin":
            executable = name_map[service_name]
            path = f"{application_path}/{executable}.exe"
            return path
        else:
            path = f"{application_path}/{name_map[service_name]}"
            return path


else:
    application_path = os.path.dirname(__file__)

    def executable_for_service(service_name):
        return service_name


class WebSocketServer:
    def __init__(self, root_path):
        self.root_path = root_path
        self.log = log
        self.services: Dict = dict()
        self.connections: Dict[str, Any] = dict()  # service_name : WebSocket
        self.remote_address_map: Dict[str, str] = dict()  # remote_address: service_name
        self.ping_job = None
        net_config = load_config(root_path, "config.yaml")
        self.self_hostname = net_config["self_hostname"]
        self.daemon_port = net_config["daemon_port"]

    async def start(self):
        self.log.info("Starting Daemon Server")

        def master_close_cb():
            asyncio.ensure_future(self.stop())

        try:
            asyncio.get_running_loop().add_signal_handler(
                signal.SIGINT, master_close_cb
            )
            asyncio.get_running_loop().add_signal_handler(
                signal.SIGTERM, master_close_cb
            )
        except NotImplementedError:
            self.log.info("Not implemented")

        self.websocket_server = await websockets.serve(
            self.safe_handle,
            self.self_hostname,
            self.daemon_port,
            max_size=None,
            ping_interval=500,
            ping_timeout=300,
        )

        self.log.info("Waiting Daemon WebSocketServer closure")
        print("Daemon server started", flush=True)
        await self.websocket_server.wait_closed()
        self.log.info("Daemon WebSocketServer closed")

    async def stop(self):
        await self.exit()
        self.websocket_server.close()
        return {"success": True}

    async def safe_handle(self, websocket, path):
        service_name = ""
        try:
            async for message in websocket:
                try:
                    decoded = json.loads(message)
                    response, socket_to_use = await self.handle_message(
                        websocket, decoded
                    )
                except Exception as e:
                    tb = traceback.format_exc()
                    self.log.error(f"Error while handling message: {tb}")
                    error = {"success": False, "error": f"{e}"}
                    response = format_response(message, error)
                if socket_to_use is not None:
                    await socket_to_use.send(response)
        except websockets.exceptions.ConnectionClosedOK as e:
            if websocket.remote_address[1] in self.remote_address_map:
                service_name = self.remote_address_map[websocket.remote_address[1]]
            self.log.info(
                f"ConnectionClosedOk. Closing websocket with {service_name} {e}"
            )
        except websockets.exceptions.WebSocketException as e:
            if websocket.remote_address[1] in self.remote_address_map:
                service_name = self.remote_address_map[websocket.remote_address[1]]
            self.log.info(
                f"Websocket exception. Closing websocket with {service_name} {e}"
            )
        except Exception as e:
            tb = traceback.format_exc()
            self.log.error(f"Unexpected exception in websocket: {e} {tb}")
        finally:
            if websocket.remote_address[1] in self.remote_address_map:
                service_name = self.remote_address_map[websocket.remote_address[1]]
            if service_name in self.connections:
                self.connections.pop(service_name)
            await websocket.close()

    async def ping_task(self):
        await asyncio.sleep(30)
        for remote_address, service_name in self.remote_address_map.items():
            try:
                connection = self.connections[service_name]
                self.log.info(f"About to ping: {service_name}")
                await connection.ping()
            except Exception as e:
                self.log.info(f"Ping error: {e}")
                self.connections.pop(service_name)
                self.remote_address_map.pop(remote_address)
                self.log.warning("Ping failed, connection closed.")
                await connection.close()
        self.ping_job = asyncio.create_task(self.ping_task())

    async def handle_message(self, websocket, message):
        """
        This function gets called when new message is received via websocket.
        """

        command = message["command"]
        destination = message["destination"]
        if destination != "daemon":
            destination = message["destination"]
            if destination in self.connections:
                socket = self.connections[destination]
                return (dict_to_json_str(message), socket)

            return (None, None)

        data = None
        if "data" in message:
            data = message["data"]
        if command == "ping":
            response = await self.ping()
        elif command == "start_service":
            response = await self.start_service(data)
        elif command == "start_plotting":
            response = await self.start_plotting(data)
        elif command == "stop_service":
            response = await self.stop_service(data)
        elif command == "is_running":
            response = await self.is_running(data)
        elif command == "exit":
            response = await self.stop()
        elif command == "register_service":
            response = await self.register_service(websocket, data)
        else:
            self.log.error(f"UK>> {message}")
            response = {"success": False, "error": f"unknown_command {command}"}

        full_response = format_response(message, response)
        return (full_response, websocket)

    async def ping(self):
        response = {"success": True, "value": "pong"}
        return response

    async def start_plotting(self, request):
        service_name = request["service"]
        k = request["k"]
        n = request["n"]
        t = request["t"]
        t2 = request["t2"]
        d = request["d"]
        b = request["b"]

        command_args: List[str] = []
        command_args += service_name.split(" ")
        command_args.append(f"-k={k}")
        command_args.append(f"-n={n}")
        command_args.append(f"-t={t}")
        command_args.append(f"-2={t2}")
        command_args.append(f"-d={d}")
        command_args.append(f"-b={b}")

        error = None
        success = False

        if service_name in self.services:
            service = self.services[service_name]
            r = service is not None and service.poll() is None
            if r is False:
                self.services.pop(service_name)
                error = None
            else:
                error = "already running"
        if error is None:
            try:
                self.log.info(f"Start potting: {command_args}")
                process, pid_path = launch_plotter(
                    self.root_path, service_name, command_args
                )
                self.services[service_name] = process
                success = True
            except (subprocess.SubprocessError, IOError):
                log.exception(f"problem starting {service_name}")
                error = "start failed"

        response = {
            "success": success,
            "service": service_name,
            "out_file": f"{plotter_log_path(self.root_path).absolute()}",
            "error": error,
        }
        return response

    async def start_service(self, request):
        service_command = request["service"]
        error = None
        success = False
        testing = False
        if "testing" in request:
            testing = request["testing"]

        if not validate_service(service_command):
            error = "unknown service"

        if service_command in self.services:
            service = self.services[service_command]
            r = service is not None and service.poll() is None
            if r is False:
                self.services.pop(service_command)
                error = None
            else:
                error = "already running"

        if error is None:
            try:
                exe_command = service_command
                if testing is True:
                    exe_command = f"{service_command} --testing=true"
                process, pid_path = launch_service(self.root_path, exe_command)
                self.services[service_command] = process
                success = True
            except (subprocess.SubprocessError, IOError):
                log.exception(f"problem starting {service_command}")
                error = "start failed"

        response = {"success": success, "service": service_command, "error": error}
        return response

    async def stop_service(self, request):
        service_name = request["service"]
        result = await kill_service(self.root_path, self.services, service_name)
        response = {"success": result, "service_name": service_name}
        return response

    async def is_running(self, request):
        service_name = request["service"]
        process = self.services.get(service_name)
        r = process is not None and process.poll() is None
        if service_name == "chia plots create":
            response = {
                "success": True,
                "service_name": service_name,
                "is_running": r,
                "out_file": f"{plotter_log_path(self.root_path).absolute()}",
            }
        else:
            response = {"success": True, "service_name": service_name, "is_running": r}

        return response

    async def exit(self):

        jobs = []
        for k in self.services.keys():
            jobs.append(kill_service(self.root_path, self.services, k))
        if jobs:
            await asyncio.wait(jobs)
        self.services.clear()

        # TODO: fix this hack
        asyncio.get_event_loop().call_later(5, lambda *args: sys.exit(0))
        log.info("chia daemon exiting in 5 seconds")

        response = {"success": True}
        return response

    async def register_service(self, websocket, request):
        self.log.info(f"Register service {request}")
        service = request["service"]
        if service in self.connections:
            ws = self.connections[service]
            self.connections.pop(service)
            if ws.remote_address[1] in self.remote_address_map:
                self.remote_address_map.pop(ws.remote_address[1])

        self.connections[service] = websocket
        self.remote_address_map[websocket.remote_address[1]] = service
        if self.ping_job is None:
            self.ping_job = asyncio.create_task(self.ping_task())
        response = {"success": True}
        self.log.info(f"registered for service {service}")
        return response


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


def plotter_log_path(root_path):
    return root_path / "plotter" / "plotter_log.txt"


def launch_plotter(root_path, service_name, service_array):
    # we need to pass on the possibly altered CHIA_ROOT
    os.environ["CHIA_ROOT"] = str(root_path)
    service_executable = executable_for_service(service_array[0])

    # Swap service name with name of executable
    service_array[0] = service_executable
    startupinfo = None
    if os.name == "nt":
        startupinfo = subprocess.STARTUPINFO()  # type: ignore
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW  # type: ignore

    plotter_path = plotter_log_path(root_path)

    if plotter_path.parent.exists():
        if plotter_path.exists():
            plotter_path.unlink()
    else:
        mkdir(plotter_path.parent)
    outfile = open(plotter_path.resolve(), "w")
    log.info(f"Service array: {service_array}")
    process = subprocess.Popen(
        service_array, shell=False, stdout=outfile, startupinfo=startupinfo
    )

    pid_path = pid_path_for_service(root_path, service_name)
    try:
        mkdir(pid_path.parent)
        with open(pid_path, "w") as f:
            f.write(f"{process.pid}\n")
    except Exception:
        pass
    return process, pid_path


def launch_service(root_path, service_command):
    """
    Launch a child process.
    """
    # set up CHIA_ROOT
    # invoke correct script
    # save away PID

    # we need to pass on the possibly altered CHIA_ROOT
    os.environ["CHIA_ROOT"] = str(root_path)

    # Innsert proper e
    service_array = service_command.split()
    service_executable = executable_for_service(service_array[0])
    service_array[0] = service_executable
    startupinfo = None
    if os.name == "nt":
        startupinfo = subprocess.STARTUPINFO()  # type: ignore
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW  # type: ignore

    process = subprocess.Popen(service_array, shell=False, startupinfo=startupinfo)
    pid_path = pid_path_for_service(root_path, service_command)
    try:
        mkdir(pid_path.parent)
        with open(pid_path, "w") as f:
            f.write(f"{process.pid}\n")
    except Exception:
        pass
    return process, pid_path


async def kill_service(root_path, services, service_name, delay_before_kill=15) -> bool:
    process = services.get(service_name)
    if process is None:
        return False
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
    log.info("process %s returned %d", service_name, r)
    try:
        pid_path_killed = pid_path.with_suffix(".pid-killed")
        if pid_path_killed.exists():
            pid_path_killed.unlink()
        os.rename(pid_path, pid_path_killed)
    except Exception:
        pass

    return True


def is_running(services, service_name):
    process = services.get(service_name)
    return process is not None and process.poll() is None


def create_server_for_daemon(root_path):
    routes = web.RouteTableDef()

    services: Dict = dict()

    @routes.get("/daemon/ping/")
    async def ping(request):
        return web.Response(text="pong")

    @routes.get("/daemon/service/start/")
    async def start_service(request):
        service_name = request.query.get("service")
        if not validate_service(service_name):
            r = "unknown service"
            return web.Response(text=str(r))

        if is_running(services, service_name):
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

    @routes.get("/daemon/service/stop/")
    async def stop_service(request):
        service_name = request.query.get("service")
        r = await kill_service(root_path, services, service_name)
        return web.Response(text=str(r))

    @routes.get("/daemon/service/is_running/")
    async def is_running_handler(request):
        service_name = request.query.get("service")
        r = is_running(services, service_name)
        return web.Response(text=str(r))

    @routes.get("/daemon/exit/")
    async def exit(request):
        jobs = []
        for k in services.keys():
            jobs.append(kill_service(root_path, services, k))
        if jobs:
            await asyncio.wait(jobs)
        services.clear()

        # we can't await `site.stop()` here because that will cause a deadlock, waiting for this
        # request to exit


def singleton(lockfile, text="semaphore"):
    """
    Open a lockfile exclusively.
    """

    if not lockfile.parent.exists():
        mkdir(lockfile.parent)

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
    chia_init(root_path)
    config = load_config(root_path, "config.yaml")
    initialize_logging("daemon", config["logging"], root_path)
    lockfile = singleton(daemon_launch_lock_path(root_path))
    if lockfile is None:
        print("daemon: already launching")
        return 2

    # TODO: clean this up, ensuring lockfile isn't removed until the listen port is open
    create_server_for_daemon(root_path)
    log.info("before start")
    ws_server = WebSocketServer(root_path)
    await ws_server.start()


def run_daemon(root_path):
    return asyncio.get_event_loop().run_until_complete(async_run_daemon(root_path))


def main():
    from src.util.default_root import DEFAULT_ROOT_PATH

    return run_daemon(DEFAULT_ROOT_PATH)


if __name__ == "__main__":
    main()
