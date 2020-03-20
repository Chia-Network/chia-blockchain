import signal
import asyncio
import logging
from src.util.logging import initialize_logging
from src.util.config import load_config_cli
from asyncio import Lock
from typing import List
from setproctitle import setproctitle

config = load_config_cli("config.yaml", "timelord_launcher")

active_processes: List = []
stopped = False
lock = Lock()

initialize_logging("Launcher %(name)-23s", config["logging"])
setproctitle("chia_timelord_launcher")

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
                f"./lib/chiavdf/fast_vdf/vdf_client {host} {port} {counter}",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except Exception as e:
            log.warning(f"Exception while spawning process {counter}: {(e)}")
            continue
        log.info(f"Launched vdf client number {counter}.")
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


async def spawn_all_processes():
    await asyncio.sleep(15)
    host = config["host"]
    port = config["port"]
    process_count = config["process_count"]
    awaitables = [
        spawn_process(host, port, i)
        for i in range(process_count)
    ]
    await asyncio.gather(*awaitables)

if __name__ == "__main__":
    def signal_received():
        asyncio.create_task(kill_processes())

    loop = asyncio.get_event_loop()

    loop.add_signal_handler(signal.SIGINT, signal_received)
    loop.add_signal_handler(signal.SIGTERM, signal_received)

    try:
        loop.run_until_complete(spawn_all_processes())
    finally:
        log.info("Launcher fully closed.")
        loop.close()
