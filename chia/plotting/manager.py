from __future__ import annotations

import logging
import threading
import time
import traceback
from concurrent.futures.thread import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from blspy import G1Element
from chiapos import DiskProver

from chia.consensus.pos_quality import UI_ACTUAL_SPACE_CONSTANT_FACTOR, _expected_plot_size
from chia.plotting.cache import Cache, CacheEntry
from chia.plotting.util import PlotInfo, PlotRefreshEvents, PlotRefreshResult, PlotsRefreshParameter, get_plot_filenames
from chia.util.generator_tools import list_to_batches

log = logging.getLogger(__name__)


class PlotManager:
    plots: Dict[Path, PlotInfo]
    plot_filename_paths: Dict[str, Tuple[str, Set[str]]]
    plot_filename_paths_lock: threading.Lock
    failed_to_open_filenames: Dict[Path, int]
    no_key_filenames: Set[Path]
    farmer_public_keys: List[G1Element]
    pool_public_keys: List[G1Element]
    cache: Cache
    match_str: Optional[str]
    open_no_key_filenames: bool
    last_refresh_time: float
    refresh_parameter: PlotsRefreshParameter
    log: Any
    _lock: threading.Lock
    _refresh_thread: Optional[threading.Thread]
    _refreshing_enabled: bool
    _refresh_callback: Callable
    _initial: bool

    def __init__(
        self,
        root_path: Path,
        refresh_callback: Callable,
        match_str: Optional[str] = None,
        open_no_key_filenames: bool = False,
        refresh_parameter: PlotsRefreshParameter = PlotsRefreshParameter(),
    ):
        self.root_path = root_path
        self.plots = {}
        self.plot_filename_paths = {}
        self.plot_filename_paths_lock = threading.Lock()
        self.failed_to_open_filenames = {}
        self.no_key_filenames = set()
        self.farmer_public_keys = []
        self.pool_public_keys = []
        self.cache = Cache(self.root_path.resolve() / "cache" / "plot_manager.dat")
        self.match_str = match_str
        self.open_no_key_filenames = open_no_key_filenames
        self.last_refresh_time = 0
        self.refresh_parameter = refresh_parameter
        self.log = logging.getLogger(__name__)
        self._lock = threading.Lock()
        self._refresh_thread = None
        self._refreshing_enabled = False
        self._refresh_callback = refresh_callback
        self._initial = True

    def __enter__(self):
        self._lock.acquire()

    def __exit__(self, exc_type, exc_value, exc_traceback):
        self._lock.release()

    def reset(self):
        with self:
            self.last_refresh_time = time.time()
            self.plots.clear()
            self.plot_filename_paths.clear()
            self.failed_to_open_filenames.clear()
            self.no_key_filenames.clear()
            self._initial = True

    def set_refresh_callback(self, callback: Callable):
        self._refresh_callback = callback

    def set_public_keys(self, farmer_public_keys: List[G1Element], pool_public_keys: List[G1Element]):
        self.farmer_public_keys = farmer_public_keys
        self.pool_public_keys = pool_public_keys

    def initial_refresh(self):
        return self._initial

    def public_keys_available(self):
        return len(self.farmer_public_keys) and len(self.pool_public_keys)

    def plot_count(self) -> int:
        with self:
            return len(self.plots)

    def get_duplicates(self) -> List[Path]:
        result = []
        for plot_filename, paths_entry in self.plot_filename_paths.items():
            _, duplicated_paths = paths_entry
            for path in duplicated_paths:
                result.append(Path(path) / plot_filename)
        return result

    def needs_refresh(self) -> bool:
        return time.time() - self.last_refresh_time > float(self.refresh_parameter.interval_seconds)

    def start_refreshing(self, sleep_interval_ms: int = 1000):
        self._refreshing_enabled = True
        if self._refresh_thread is None or not self._refresh_thread.is_alive():
            self.cache.load()
            self._refresh_thread = threading.Thread(target=self._refresh_task, args=(sleep_interval_ms,))
            self._refresh_thread.start()

    def stop_refreshing(self) -> None:
        self._refreshing_enabled = False
        if self._refresh_thread is not None and self._refresh_thread.is_alive():
            self._refresh_thread.join()
            self._refresh_thread = None

    def trigger_refresh(self) -> None:
        log.debug("trigger_refresh")
        self.last_refresh_time = 0

    def _refresh_task(self, sleep_interval_ms: int):
        while self._refreshing_enabled:
            try:
                while not self.needs_refresh() and self._refreshing_enabled:
                    time.sleep(sleep_interval_ms / 1000.0)

                if not self._refreshing_enabled:
                    return

                plot_filenames: Dict[Path, List[Path]] = get_plot_filenames(self.root_path)
                plot_directories: Set[Path] = set(plot_filenames.keys())
                plot_paths: Set[Path] = set()
                for paths in plot_filenames.values():
                    plot_paths.update(paths)

                total_result: PlotRefreshResult = PlotRefreshResult()
                total_size = len(plot_paths)

                self._refresh_callback(PlotRefreshEvents.started, PlotRefreshResult(remaining=total_size))

                # First drop all plots we have in plot_filename_paths but not longer in the filesystem or set in config
                for path in list(self.failed_to_open_filenames.keys()):
                    if path not in plot_paths:
                        del self.failed_to_open_filenames[path]

                for path in self.no_key_filenames.copy():
                    if path not in plot_paths:
                        self.no_key_filenames.remove(path)

                filenames_to_remove: List[str] = []
                for plot_filename, paths_entry in self.plot_filename_paths.items():
                    loaded_path, duplicated_paths = paths_entry
                    loaded_plot = Path(loaded_path) / Path(plot_filename)
                    if loaded_plot not in plot_paths:
                        filenames_to_remove.append(plot_filename)
                        with self:
                            if loaded_plot in self.plots:
                                del self.plots[loaded_plot]
                        total_result.removed.append(loaded_plot)
                        # No need to check the duplicates here since we drop the whole entry
                        continue

                    paths_to_remove: List[str] = []
                    for path_str in duplicated_paths:
                        loaded_plot = Path(path_str) / Path(plot_filename)
                        if loaded_plot not in plot_paths:
                            paths_to_remove.append(path_str)
                    for path_str in paths_to_remove:
                        duplicated_paths.remove(path_str)

                for filename in filenames_to_remove:
                    del self.plot_filename_paths[filename]

                for remaining, batch in list_to_batches(sorted(list(plot_paths)), self.refresh_parameter.batch_size):
                    batch_result: PlotRefreshResult = self.refresh_batch(batch, plot_directories)
                    if not self._refreshing_enabled:
                        self.log.debug("refresh_plots: Aborted")
                        break
                    # Set the remaining files since `refresh_batch()` doesn't know them but we want to report it
                    batch_result.remaining = remaining
                    total_result.loaded += batch_result.loaded
                    total_result.processed += batch_result.processed
                    total_result.duration += batch_result.duration

                    self._refresh_callback(PlotRefreshEvents.batch_processed, batch_result)
                    if remaining == 0:
                        break
                    batch_sleep = self.refresh_parameter.batch_sleep_milliseconds
                    self.log.debug(f"refresh_plots: Sleep {batch_sleep} milliseconds")
                    time.sleep(float(batch_sleep) / 1000.0)

                if self._refreshing_enabled:
                    self._refresh_callback(PlotRefreshEvents.done, total_result)

                # Reset the initial refresh indication
                self._initial = False

                # Cleanup unused cache
                self.log.debug(f"_refresh_task: cached entries before cleanup: {len(self.cache)}")
                remove_paths: List[Path] = []
                for path, cache_entry in self.cache.items():
                    if cache_entry.expired(Cache.expiry_seconds) and path not in self.plots:
                        remove_paths.append(path)
                    elif path in self.plots:
                        cache_entry.bump_last_use()
                self.cache.remove(remove_paths)
                self.log.debug(f"_refresh_task: cached entries removed: {len(remove_paths)}")

                if self.cache.changed():
                    self.cache.save()

                self.last_refresh_time = time.time()

                self.log.debug(
                    f"_refresh_task: total_result.loaded {len(total_result.loaded)}, "
                    f"total_result.removed {len(total_result.removed)}, "
                    f"total_duration {total_result.duration:.2f} seconds"
                )
            except Exception as e:
                log.error(f"_refresh_callback raised: {e} with the traceback: {traceback.format_exc()}")
                self.reset()

    def refresh_batch(self, plot_paths: List[Path], plot_directories: Set[Path]) -> PlotRefreshResult:
        start_time: float = time.time()
        result: PlotRefreshResult = PlotRefreshResult(processed=len(plot_paths))
        counter_lock = threading.Lock()

        log.debug(f"refresh_batch: {len(plot_paths)} files in directories {plot_directories}")

        if self.match_str is not None:
            log.info(f'Only loading plots that contain "{self.match_str}" in the file or directory name')

        def process_file(file_path: Path) -> Optional[PlotInfo]:
            if not self._refreshing_enabled:
                return None
            filename_str = str(file_path)
            if self.match_str is not None and self.match_str not in filename_str:
                return None
            if (
                file_path in self.failed_to_open_filenames
                and (time.time() - self.failed_to_open_filenames[file_path])
                < self.refresh_parameter.retry_invalid_seconds
            ):
                # Try once every `refresh_parameter.retry_invalid_seconds` seconds to open the file
                return None

            if file_path in self.plots:
                return self.plots[file_path]

            entry: Optional[Tuple[str, Set[str]]] = self.plot_filename_paths.get(file_path.name)
            if entry is not None:
                loaded_parent, duplicates = entry
                if str(file_path.parent) in duplicates:
                    log.debug(f"Skip duplicated plot {str(file_path)}")
                    return None
            try:
                if not file_path.exists():
                    return None

                stat_info = file_path.stat()

                cache_entry = self.cache.get(file_path)
                cache_hit = cache_entry is not None
                if not cache_hit:
                    prover = DiskProver(str(file_path))

                    log.debug(f"process_file {str(file_path)}")

                    expected_size = _expected_plot_size(prover.get_size()) * UI_ACTUAL_SPACE_CONSTANT_FACTOR

                    # TODO: consider checking if the file was just written to (which would mean that the file is still
                    # being copied). A segfault might happen in this edge case.

                    if prover.get_size() >= 30 and stat_info.st_size < 0.98 * expected_size:
                        log.warning(
                            f"Not farming plot {file_path}. Size is {stat_info.st_size / (1024 ** 3)} GiB, but expected"
                            f" at least: {expected_size / (1024 ** 3)} GiB. We assume the file is being copied."
                        )
                        return None

                    cache_entry = CacheEntry.from_disk_prover(prover)
                    self.cache.update(file_path, cache_entry)

                assert cache_entry is not None
                # Only use plots that correct keys associated with them
                if cache_entry.farmer_public_key not in self.farmer_public_keys:
                    log.warning(f"Plot {file_path} has a farmer public key that is not in the farmer's pk list.")
                    self.no_key_filenames.add(file_path)
                    if not self.open_no_key_filenames:
                        return None

                if cache_entry.pool_public_key is not None and cache_entry.pool_public_key not in self.pool_public_keys:
                    log.warning(f"Plot {file_path} has a pool public key that is not in the farmer's pool pk list.")
                    self.no_key_filenames.add(file_path)
                    if not self.open_no_key_filenames:
                        return None

                # If a plot is in `no_key_filenames` the keys were missing in earlier refresh cycles. We can remove
                # the current plot from that list if its in there since we passed the key checks above.
                if file_path in self.no_key_filenames:
                    self.no_key_filenames.remove(file_path)

                with self.plot_filename_paths_lock:
                    paths: Optional[Tuple[str, Set[str]]] = self.plot_filename_paths.get(file_path.name)
                    if paths is None:
                        paths = (str(Path(cache_entry.prover.get_filename()).parent), set())
                        self.plot_filename_paths[file_path.name] = paths
                    else:
                        paths[1].add(str(Path(cache_entry.prover.get_filename()).parent))
                        log.warning(f"Have multiple copies of the plot {file_path.name} in {[paths[0], *paths[1]]}.")
                        return None

                new_plot_info: PlotInfo = PlotInfo(
                    cache_entry.prover,
                    cache_entry.pool_public_key,
                    cache_entry.pool_contract_puzzle_hash,
                    cache_entry.plot_public_key,
                    stat_info.st_size,
                    stat_info.st_mtime,
                )

                cache_entry.bump_last_use()

                with counter_lock:
                    result.loaded.append(new_plot_info)

                if file_path in self.failed_to_open_filenames:
                    del self.failed_to_open_filenames[file_path]

            except Exception as e:
                tb = traceback.format_exc()
                log.error(f"Failed to open file {file_path}. {e} {tb}")
                self.failed_to_open_filenames[file_path] = int(time.time())
                return None
            log.debug(f"Found plot {file_path} of size {new_plot_info.prover.get_size()}, cache_hit: {cache_hit}")

            return new_plot_info

        with self, ThreadPoolExecutor() as executor:
            plots_refreshed: Dict[Path, PlotInfo] = {}
            for new_plot in executor.map(process_file, plot_paths):
                if new_plot is not None:
                    plots_refreshed[Path(new_plot.prover.get_filename())] = new_plot
            self.plots.update(plots_refreshed)

        result.duration = time.time() - start_time

        self.log.debug(
            f"refresh_batch: loaded {len(result.loaded)}, "
            f"removed {len(result.removed)}, processed {result.processed}, "
            f"remaining {result.remaining}, batch_size {self.refresh_parameter.batch_size}, "
            f"duration: {result.duration:.2f} seconds"
        )
        return result
