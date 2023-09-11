from __future__ import annotations

import asyncio
import logging
import os
import pathlib
import signal
import time
from types import FrameType
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import pkg_resources

from chia.util.chia_logging import initialize_logging
from chia.util.config import load_config
from chia.util.default_root import DEFAULT_ROOT_PATH
from chia.util.misc import SignalHandlers
from chia.util.network import resolve
from chia.util.setproctitle import setproctitle

log = logging.getLogger(__name__)


@dataclass
class VDFClientProcessMgr:
    lock: asyncio.Lock
    stopped: bool
    active_processes: List[asyncio.subprocess.Process] = field(default_factory=list)


async def kill_processes(process_mgr: VDFClientProcessMgr):
    async with process_mgr.lock:
        process_mgr.stopped = True
        for process in process_mgr.active_processes:
            try:
                process.kill()
            except ProcessLookupError:
                pass
        process_mgr.active_processes.clear()


def find_vdf_client() -> pathlib.Path:
    p = pathlib.Path(pkg_resources.get_distribution("chiavdf").location) / "vdf_client"
    if p.is_file():
        return p
    raise FileNotFoundError("can't find vdf_client binary")


async def spawn_process(
    host: str,
    port: int,
    counter: int,
    process_mgr: VDFClientProcessMgr,
    *,
    prefer_ipv6: bool,
):
    path_to_vdf_client = find_vdf_client()
    first_10_seconds = True
    start_time = time.time()
    while not process_mgr.stopped:
        try:
            dirname = path_to_vdf_client.parent
            basename = path_to_vdf_client.name
            resolved = await resolve(host, prefer_ipv6=prefer_ipv6)
            proc = await asyncio.create_subprocess_shell(
                f"{basename} {resolved} {port} {counter}",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env={"PATH": os.fspath(dirname)},
            )
        except Exception as e:
            log.warning(f"Exception while spawning process {counter}: {(e)}")
            continue
        async with process_mgr.lock:
            process_mgr.active_processes.append(proc)

        stdout, stderr = await proc.communicate()
        if stdout:
            log.info(f"VDF client {counter}: {stdout.decode().rstrip()}")
        if stderr:
            if first_10_seconds:
                if time.time() - start_time > 10:
                    first_10_seconds = False
            else:
                log.error(f"VDF client {counter}: {stderr.decode().rstrip()}")

        async with process_mgr.lock:
            if proc in process_mgr.active_processes:
                process_mgr.active_processes.remove(proc)

        await asyncio.sleep(0.1)


async def spawn_all_processes(config: Dict, net_config: Dict, process_mgr: VDFClientProcessMgr):
    await asyncio.sleep(5)
    hostname = net_config["self_hostname"] if "host" not in config else config["host"]
    port = config["port"]
    process_count = config["process_count"]
    if process_count == 0:
        log.info("Process_count set to 0, stopping TLauncher.")
        return
    awaitables = [
        spawn_process(
            hostname,
            port,
            i,
            process_mgr,
            prefer_ipv6=net_config.get("prefer_ipv6", False),
        )
        for i in range(process_count)
    ]
    await asyncio.gather(*awaitables)


async def async_main(config: Dict[str, Any], net_config: Dict[str, Any]) -> None:
    lock = asyncio.Lock()

    async def stop(
        signal_: signal.Signals,
        stack_frame: Optional[FrameType],
        loop: asyncio.AbstractEventLoop,
    ) -> None:
        await kill_processes(lock)

    async with SignalHandlers.manage() as signal_handlers:
        signal_handlers.setup_async_signal_handler(handler=stop)

        try:
            await spawn_all_processes(config, net_config, lock)
        finally:
            log.info("Launcher fully closed.")


def main():
    if os.name == "nt":
        log.info("Timelord launcher not supported on Windows.")
        return
    root_path = DEFAULT_ROOT_PATH
    setproctitle("chia_timelord_launcher")
    net_config = load_config(root_path, "config.yaml")
    config = net_config["timelord_launcher"]
    initialize_logging("TLauncher", config["logging"], root_path)

    asyncio.run(async_main(config=config, net_config=net_config))


if __name__ == "__main__":
    main()
