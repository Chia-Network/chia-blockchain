from __future__ import annotations

import asyncio
import logging
import platform
import socket
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

import psutil

from chia.util.config import load_config

log = logging.getLogger("beta")

metrics_log_interval_default = 5
metrics_log_interval_min = 1
metrics_log_interval_max = 30


def log_static_info() -> None:
    log.debug(f"architecture: {platform.architecture()}")
    log.debug(f"processor: {platform.processor()}")
    log.debug(f"cpu count: {psutil.cpu_count()}")
    log.debug(f"machine: {platform.machine()}")
    log.debug(f"platform: {platform.platform()}")


def log_cpu_metrics() -> None:
    log.debug(
        f"CPU - percent: {psutil.cpu_percent(percpu=True)}, "
        f"freq: {psutil.cpu_times(percpu=True)}, "
        f"freq: {psutil.cpu_freq(percpu=True)}, "
        f"load_avg: {psutil.getloadavg()}"
    )


def log_memory_metrics() -> None:
    psutil.disk_io_counters(perdisk=False)
    log.debug(f"MEMORY - virtual memory: {psutil.virtual_memory()}, swap: {psutil.swap_memory()}")


def log_disk_metrics(root_path: Path, plot_dirs: List[str]) -> None:
    # TODO, Could this spam the logs too much for large farms? Maybe don't log usage of plot dirs and
    #       set perdisk=False rather for psutil.disk_io_counters? Lets try it with the default interval of 15s for now.
    log.debug(f"DISK partitions: {psutil.disk_partitions()}")
    for pot_dir in plot_dirs:
        try:
            usage = psutil.disk_usage(pot_dir)
        except FileNotFoundError:
            usage = "Directory not found"
        log.debug(f"DISK - usage {pot_dir}: {usage}")
    log.debug(f"DISK - usage root: {psutil.disk_usage(str(root_path))}")
    log.debug(f"DISK - io counters: {psutil.disk_io_counters(perdisk=True)}")


def log_port_states(config: Dict[str, Any]) -> None:
    selected_network = config["selected_network"]
    full_node_port = config["network_overrides"]["config"][selected_network]["default_full_node_port"]
    test_socket_ipv4 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    port_open_ipv4 = test_socket_ipv4.connect_ex(("127.0.0.1", full_node_port)) == 0
    log.debug(f"full node port IPv4 [{full_node_port}]: {'open' if port_open_ipv4 else 'closed'}")
    test_socket_ipv6 = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
    port_open_ipv6 = test_socket_ipv6.connect_ex(("::1", full_node_port)) == 0
    log.debug(f"full node port IPv6 [{full_node_port}]: {'open' if port_open_ipv6 else 'closed'}")


def log_network_metrics() -> None:
    log.debug(f"NETWORK: io counters: {psutil.net_io_counters(pernic=False)}")


@dataclass
class BetaMetricsLogger:
    root_path: Path
    task: Optional[asyncio.Task[None]] = None
    stop_task: bool = False

    def start_logging(self) -> None:
        log.debug("start_logging")
        log_static_info()
        if self.task is not None:
            raise RuntimeError("Already started")
        self.stop_task = False
        self.task = asyncio.create_task(self.run())

    async def stop_logging(self) -> None:
        log.debug("stop_logging")
        if self.task is None:
            raise RuntimeError("Not yet started")

        self.stop_task = True
        await self.task
        self.task = None

    async def run(self) -> None:
        config = load_config(self.root_path, "config.yaml")
        interval = min(max(config["beta"]["metrics_log_interval"], metrics_log_interval_min), metrics_log_interval_max)
        tick = 0
        while not self.stop_task:
            try:
                tick += 1
                # Log every interval
                if tick % interval == 0:
                    log_cpu_metrics()
                    log_memory_metrics()
                    log_network_metrics()
                # Log after 10 intervals passed
                if tick % (interval * 10) == 0:
                    log_disk_metrics(self.root_path, config["harvester"]["plot_directories"])
                    log_port_states(config)
            except Exception as e:
                log.warning(f"BetaMetricsLogger run failed: {e}")
                await asyncio.sleep(10)
            await asyncio.sleep(1)
        log.debug("done")
