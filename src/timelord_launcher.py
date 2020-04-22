import signal
import asyncio
import logging
import pathlib
import pkg_resources
from src.util.logging import initialize_logging
from src.util.config import load_config
from asyncio import Lock
from typing import List
from src.util.default_root import DEFAULT_ROOT_PATH
from src.util.setproctitle import setproctitle

active_processes: List = []
stopped = False
lock = Lock()

log = logging.getLogger(__name__)


async def kill_processes():
    global stopped
    global active_processes
    async with lock:
        stopped = True
        for process in active_processes:
            process.kill()


def find_vdf_client():
    p = pathlib.Path(pkg_resources.get_distribution("chiavdf").location) / "vdf_client"
    if p.is_file():
        return p
    raise FileNotFoundError("can't find vdf_client binary")


async def spawn_process(host, port, counter):
    global stopped
    global active_processes
    path_to_vdf_client = find_vdf_client()
    while not stopped:
        try:
            dirname = path_to_vdf_client.parent
            basename = path_to_vdf_client.name
            proc = await asyncio.create_subprocess_shell(
                f"{basename} {host} {port} {counter}",
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
            log.info(f"Stdout:\n{stdout.decode().rstrip()}")
        if stderr:
            log.info(f"Stderr:\n{stderr.decode().rstrip()}")
        log.info(f"Process number {counter} ended.")
        async with lock:
            if proc in active_processes:
                active_processes.remove(proc)
        await asyncio.sleep(0.1)


async def spawn_all_processes(config):
    await asyncio.sleep(15)
    port = config["port"]
    process_count = config["process_count"]
    awaitables = [spawn_process("127.0.0.1", port, i) for i in range(process_count)]
    await asyncio.gather(*awaitables)


def main():
    root_path = DEFAULT_ROOT_PATH
    setproctitle("chia_timelord_launcher")
    config = load_config(root_path, "config.yaml", "timelord_launcher")
    initialize_logging("Launcher %(name)-23s", config["logging"], root_path)

    def signal_received():
        asyncio.create_task(kill_processes())

    loop = asyncio.get_event_loop()

    try:
        loop.add_signal_handler(signal.SIGINT, signal_received)
        loop.add_signal_handler(signal.SIGTERM, signal_received)
    except NotImplementedError:
        log.info("signal handlers unsupported")

    try:
        loop.run_until_complete(spawn_all_processes(config))
    finally:
        log.info("Launcher fully closed.")
        loop.close()


if __name__ == "__main__":
    main()
