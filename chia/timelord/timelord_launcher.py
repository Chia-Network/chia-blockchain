from __future__ import annotations

import asyncio
import logging
import os
import pathlib
import signal
import time
from dataclasses import dataclass, field
from types import FrameType
from typing import Any, Dict, List, Optional

import anyio
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
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    stopped: bool = False
    active_processes: List[asyncio.subprocess.Process] = field(default_factory=list)

    async def remove_process(self, proc: asyncio.subprocess.Process) -> None:
        async with self.lock:
            try:
                self.active_processes.remove(proc)
            except ValueError:
                pass

    async def add_process(self, proc: asyncio.subprocess.Process) -> None:
        async with self.lock:
            self.active_processes.append(proc)

    async def kill_processes(self) -> None:
        async with self.lock:
            self.stopped = True
            for process in self.active_processes:
                try:
                    process.kill()
                except ProcessLookupError:
                    pass
        self.active_processes.clear()


def find_vdf_client() -> pathlib.Path:
    p = pathlib.Path(pkg_resources.get_distribution("chiavdf").location) / "vdf_client"
    if p.is_file():
        return p
    raise FileNotFoundError("Cannot find vdf_client binary. Is Timelord installed?")


async def spawn_process(
    host: str,
    port: int,
    counter: int,
    process_mgr: VDFClientProcessMgr,
    *,
    prefer_ipv6: bool,
    task_status: Optional[anyio.abc.TaskStatus[None]] = None,
):
    path_to_vdf_client = find_vdf_client()
    first_10_seconds = True
    start_time = time.time()
    if task_status is not None:
        task_status.started()
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
        await process_mgr.add_process(proc)

        stdout, stderr = await proc.communicate()
        if stdout:
            log.info(f"VDF client {counter}: {stdout.decode().rstrip()}")
        if stderr:
            if first_10_seconds:
                if time.time() - start_time > 10:
                    first_10_seconds = False
            else:
                log.error(f"VDF client {counter}: {stderr.decode().rstrip()}")

        await process_mgr.remove_process(proc)
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
    process_mgr = VDFClientProcessMgr(asyncio.Lock(), False, [])

    async def stop(
        signal_: signal.Signals,
        stack_frame: Optional[FrameType],
        loop: asyncio.AbstractEventLoop,
    ) -> None:
        await process_mgr.kill_processes()

    async with SignalHandlers.manage() as signal_handlers:
        signal_handlers.setup_async_signal_handler(handler=stop)

        try:
            await spawn_all_processes(config, net_config, process_mgr)
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
