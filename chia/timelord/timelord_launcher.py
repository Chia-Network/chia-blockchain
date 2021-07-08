import asyncio
import logging
import pathlib
import signal
import socket
import time
from typing import Dict, List

import pkg_resources

from chia.util.chia_logging import initialize_logging
from chia.util.config import load_config
from chia.util.default_root import DEFAULT_ROOT_PATH
from chia.util.setproctitle import setproctitle

active_processes: List = []
stopped = False
lock = asyncio.Lock()

log = logging.getLogger(__name__)


async def kill_processes():
    global stopped
    global active_processes
    async with lock:
        stopped = True
        for process in active_processes:
            try:
                process.kill()
            except ProcessLookupError:
                pass


def find_vdf_client() -> pathlib.Path:
    p = pathlib.Path(pkg_resources.get_distribution("chiavdf").location) / "vdf_client"
    if p.is_file():
        return p
    raise FileNotFoundError("can't find vdf_client binary")


async def spawn_process(host: str, port: int, counter: int):
    global stopped
    global active_processes
    path_to_vdf_client = find_vdf_client()
    first_10_seconds = True
    start_time = time.time()
    while not stopped:
        try:
            dirname = path_to_vdf_client.parent
            basename = path_to_vdf_client.name
            resolved = socket.gethostbyname(host)
            proc = await asyncio.create_subprocess_shell(
                f"{basename} {resolved} {port} {counter}",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env={"PATH": dirname},
            )
        except Exception as e:
            log.warning(f"Exception while spawning process {counter}: {(e)}")
            continue
        async with lock:
            active_processes.append(proc)
        stdout, stderr = await proc.communicate()
        if stdout:
            log.info(f"VDF client {counter}: {stdout.decode().rstrip()}")
        if stderr:
            if first_10_seconds:
                if time.time() - start_time > 10:
                    first_10_seconds = False
            else:
                log.error(f"VDF client {counter}: {stderr.decode().rstrip()}")
        log.info(f"Process number {counter} ended.")
        async with lock:
            if proc in active_processes:
                active_processes.remove(proc)
        await asyncio.sleep(0.1)


async def spawn_all_processes(config: Dict, net_config: Dict):
    await asyncio.sleep(5)
    port = config["port"]
    process_count = config["process_count"]
    awaitables = [spawn_process(net_config["self_hostname"], port, i) for i in range(process_count)]
    await asyncio.gather(*awaitables)


def main():
    root_path = DEFAULT_ROOT_PATH
    setproctitle("silicoin_timelord_launcher")
    net_config = load_config(root_path, "config.yaml")
    config = net_config["timelord_launcher"]
    initialize_logging("TLauncher", config["logging"], root_path)

    def signal_received():
        asyncio.create_task(kill_processes())

    loop = asyncio.get_event_loop()

    try:
        loop.add_signal_handler(signal.SIGINT, signal_received)
        loop.add_signal_handler(signal.SIGTERM, signal_received)
    except NotImplementedError:
        log.info("signal handlers unsupported")

    try:
        loop.run_until_complete(spawn_all_processes(config, net_config))
    finally:
        log.info("Launcher fully closed.")
        loop.close()


if __name__ == "__main__":
    main()
