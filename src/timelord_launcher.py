import signal
import asyncio
import logging
from src.util.logging import initialize_logging
from src.util.config import load_config_cli
from asyncio import Lock
from typing import List

config = load_config_cli("config.yaml", "timelord_launcher")

active_processes: List = []
stopped = False
lock = Lock()

initialize_logging("Launcher %(name)-23s", config["logging"])

log = logging.getLogger(__name__)


async def kill_processes():
    global stopped
    global active_processes
    async with lock:
        stopped = True
        for process in active_processes:
            process.kill()


async def spawn_process(host, port, counter):
    global stopped
    global active_processes
    while not stopped:
        try:
            proc = await asyncio.create_subprocess_shell(
                f"./lib/chiavdf/fast_vdf/vdf_client {host} {port} {counter}"
            )
        except Exception as e:
            log.warning(f"Exception while spawning process {counter}: {(e)}")
            continue
        log.info(f"Launched vdf client number {counter}.")
        async with lock:
            active_processes.append(proc)
        await proc.wait()
        log.info(f"Process number {counter} ended.")
        async with lock:
            if proc in active_processes:
                active_processes.remove(proc)
        await asyncio.sleep(1)


async def main():
    host = config["host"]
    port = config["port"]
    process_count = config["process_count"]

    def signal_received():
        asyncio.create_task(kill_processes())

    asyncio.get_running_loop().add_signal_handler(signal.SIGINT, signal_received)
    asyncio.get_running_loop().add_signal_handler(signal.SIGTERM, signal_received)

    awaitables = [
        spawn_process(host, port, i)
        for i in range(process_count)
    ]
    await asyncio.gather(*awaitables)

asyncio.run(main())
