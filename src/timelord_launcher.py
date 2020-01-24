import os
import signal
import asyncio
import logging
from src.util.logging import initialize_logging
from yaml import safe_load
from asyncio import Lock
from definitions import ROOT_DIR

config_filename = os.path.join(ROOT_DIR, "config", "config.yaml")
config = safe_load(open(config_filename, "r"))["timelord_launcher"]

active_processes = []
stopped = False
lock = Lock()

initialize_logging("Launcher %(name)-23s")

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
    global log
    while not stopped:
        try:
            proc = await asyncio.create_subprocess_shell(
                f"./lib/chiavdf/fast_vdf/vdf_client {host} {port} {counter}"
            )
        except Exception as e:
            log.warning(f"Exception while spawning process {counter}.")
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
    stopped = False
    active_processes = []

    host = config["host"]
    port = config["port"]
    process_count = config["process_count"]

    for i in range(process_count):
        asyncio.create_task(spawn_process(host, port, i))
    
    def signal_received():
        asyncio.create_task(kill_processes())

    asyncio.get_running_loop().add_signal_handler(signal.SIGINT, signal_received)
    asyncio.get_running_loop().add_signal_handler(signal.SIGTERM, signal_received)

asyncio.run(main())
