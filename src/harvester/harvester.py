import logging
import asyncio
from concurrent.futures.thread import ThreadPoolExecutor
from pathlib import Path
from typing import Dict, Optional, Tuple, List, Callable, Set
import concurrent

from blspy import G1Element

from src.consensus.constants import ConsensusConstants
from src.plotting.plot_tools import (
    load_plots,
    PlotInfo,
    remove_plot_directory as remove_plot_directory_pt,
    add_plot_directory as add_plot_directory_pt,
    get_plot_directories as get_plot_directories_pt,
)

log = logging.getLogger(__name__)


class Harvester:
    provers: Dict[Path, PlotInfo]
    failed_to_open_filenames: Dict[Path, int]
    no_key_filenames: Set[Path]
    farmer_public_keys: List[G1Element]
    pool_public_keys: List[G1Element]
    root_path: Path
    _is_shutdown: bool
    executor: ThreadPoolExecutor
    state_changed_callback: Optional[Callable]
    cached_challenges: List
    constants: ConsensusConstants
    _refresh_lock: asyncio.Lock

    def __init__(self, root_path: Path, constants: ConsensusConstants):
        self.root_path = root_path

        # From filename to prover
        self.provers = {}
        self.failed_to_open_filenames = {}
        self.no_key_filenames = set()

        self._is_shutdown = False
        self.farmer_public_keys = []
        self.pool_public_keys = []
        self.match_str = None
        self.executor = concurrent.futures.ThreadPoolExecutor(max_workers=10)
        self.state_changed_callback = None
        self.server = None
        self.constants = constants
        self.cached_challenges = []
        self.log = log

    async def _start(self):
        self._refresh_lock = asyncio.Lock()

    def _close(self):
        self._is_shutdown = True
        self.executor.shutdown(wait=True)

    async def _await_closed(self):
        pass

    def _set_state_changed_callback(self, callback: Callable):
        self.state_changed_callback = callback

    def _state_changed(self, change: str):
        if self.state_changed_callback is not None:
            self.state_changed_callback(change)

    def get_plots(self) -> Tuple[List[Dict], List[str], List[str]]:
        response_plots: List[Dict] = []
        for path, plot_info in self.provers.items():
            prover = plot_info.prover
            response_plots.append(
                {
                    "filename": str(path),
                    "size": prover.get_size(),
                    "plot-seed": prover.get_id(),
                    "pool_public_key": plot_info.pool_public_key,
                    "farmer_public_key": plot_info.farmer_public_key,
                    "plot_public_key": plot_info.plot_public_key,
                    "local_sk": plot_info.local_sk,
                    "file_size": plot_info.file_size,
                    "time_modified": plot_info.time_modified,
                }
            )

        return (
            response_plots,
            [str(s) for s, _ in self.failed_to_open_filenames.items()],
            [str(s) for s in self.no_key_filenames],
        )

    async def refresh_plots(self):
        locked: bool = self._refresh_lock.locked()
        changed: bool = False
        async with self._refresh_lock:
            if not locked:
                # Avoid double refreshing of plots
                (changed, self.provers, self.failed_to_open_filenames, self.no_key_filenames,) = load_plots(
                    self.provers,
                    self.failed_to_open_filenames,
                    self.farmer_public_keys,
                    self.pool_public_keys,
                    self.match_str,
                    self.root_path,
                )
        if changed:
            self._state_changed("plots")

    def delete_plot(self, str_path: str):
        path = Path(str_path).resolve()
        if path in self.provers:
            del self.provers[path]

        # Remove absolute and relative paths
        if path.exists():
            path.unlink()

        self._state_changed("plots")
        return True

    async def add_plot_directory(self, str_path: str) -> bool:
        add_plot_directory_pt(str_path, self.root_path)
        await self.refresh_plots()
        return True

    async def get_plot_directories(self) -> List[str]:
        return get_plot_directories_pt(self.root_path)

    async def remove_plot_directory(self, str_path: str) -> bool:
        remove_plot_directory_pt(str_path, self.root_path)
        return True

    def set_server(self, server):
        self.server = server
