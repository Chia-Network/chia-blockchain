from dataclasses import dataclass
import logging
import threading
import time
import traceback
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Iterator
from concurrent.futures.thread import ThreadPoolExecutor

from blspy import G1Element
from chiapos import DiskProver

from chia.consensus.pos_quality import UI_ACTUAL_SPACE_CONSTANT_FACTOR, _expected_plot_size
from chia.plotting.util import (
    PlotInfo,
    PlotRefreshResult,
    PlotsRefreshParameter,
    PlotRefreshEvents,
    get_plot_filenames,
    parse_plot_info,
    stream_plot_info_pk,
    stream_plot_info_ph,
)
from chia.util.ints import uint16
from chia.util.path import mkdir
from chia.util.streamable import Streamable, streamable
from chia.types.blockchain_format.proof_of_space import ProofOfSpace
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.wallet.derive_keys import master_sk_to_local_sk

log = logging.getLogger(__name__)

CURRENT_VERSION: uint16 = uint16(0)


@dataclass(frozen=True)
@streamable
class CacheEntry(Streamable):
    pool_public_key: Optional[G1Element]
    pool_contract_puzzle_hash: Optional[bytes32]
    plot_public_key: G1Element


@dataclass(frozen=True)
@streamable
class DiskCache(Streamable):
    version: uint16
    data: List[Tuple[bytes32, CacheEntry]]


class Cache:
    _changed: bool
    _data: Dict[bytes32, CacheEntry]

    def __init__(self, path: Path):
        self._changed = False
        self._data = {}
        self._path = path
        if not path.parent.exists():
            mkdir(path.parent)

    def __len__(self):
        return len(self._data)

    def update(self, plot_id: bytes32, entry: CacheEntry):
        self._data[plot_id] = entry
        self._changed = True

    def remove(self, cache_keys: List[bytes32]):
        for key in cache_keys:
            if key in self._data:
                del self._data[key]
                self._changed = True

    def save(self):
        try:
            disk_cache: DiskCache = DiskCache(
                CURRENT_VERSION, [(plot_id, cache_entry) for plot_id, cache_entry in self.items()]
            )
            serialized: bytes = bytes(disk_cache)
            self._path.write_bytes(serialized)
            self._changed = False
            log.info(f"Saved {len(serialized)} bytes of cached data")
        except Exception as e:
            log.error(f"Failed to save cache: {e}, {traceback.format_exc()}")

    def load(self):
        try:
            serialized = self._path.read_bytes()
            log.info(f"Loaded {len(serialized)} bytes of cached data")
            stored_cache: DiskCache = DiskCache.from_bytes(serialized)
            if stored_cache.version != CURRENT_VERSION:
                # TODO, Migrate or drop current cache if the version changes.
                raise ValueError(f"Invalid cache version {stored_cache.version}. Expected version {CURRENT_VERSION}.")
            self._data = {plot_id: cache_entry for plot_id, cache_entry in stored_cache.data}
        except FileNotFoundError:
            log.debug(f"Cache {self._path} not found")
        except Exception as e:
            log.error(f"Failed to load cache: {e}, {traceback.format_exc()}")

    def keys(self):
        return self._data.keys()

    def items(self):
        return self._data.items()

    def get(self, plot_id):
        return self._data.get(plot_id)

    def changed(self):
        return self._changed

    def path(self):
        return self._path


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
    show_memo: bool
    open_no_key_filenames: bool
    last_refresh_time: float
    refresh_parameter: PlotsRefreshParameter
    log: Any
    _lock: threading.Lock
    _refresh_thread: Optional[threading.Thread]
    _refreshing_enabled: bool
    _refresh_callback: Callable

    def __init__(
        self,
        root_path: Path,
        refresh_callback: Callable,
        match_str: Optional[str] = None,
        show_memo: bool = False,
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
        self.show_memo = show_memo
        self.open_no_key_filenames = open_no_key_filenames
        self.last_refresh_time = 0
        self.refresh_parameter = refresh_parameter
        self.log = logging.getLogger(__name__)
        self._lock = threading.Lock()
        self._refresh_thread = None
        self._refreshing_enabled = False
        self._refresh_callback = refresh_callback  # type: ignore

    def __enter__(self):
        self._lock.acquire()

    def __exit__(self, exc_type, exc_value, exc_traceback):
        self._lock.release()

    def set_refresh_callback(self, callback: Callable):
        self._refresh_callback = callback  # type: ignore

    def set_public_keys(self, farmer_public_keys: List[G1Element], pool_public_keys: List[G1Element]):
        self.farmer_public_keys = farmer_public_keys
        self.pool_public_keys = pool_public_keys

    def public_keys_available(self):
        return len(self.farmer_public_keys) and len(self.pool_public_keys)

    def plot_count(self):
        with self:
            return len(self.plots)

    def get_duplicates(self):
        result = []
        for plot_filename, paths_entry in self.plot_filename_paths.items():
            _, duplicated_paths = paths_entry
            for path in duplicated_paths:
                result.append(Path(path) / plot_filename)
        return result

    def needs_refresh(self) -> bool:
        return time.time() - self.last_refresh_time > float(self.refresh_parameter.interval_seconds)

    def start_refreshing(self):
        self._refreshing_enabled = True
        if self._refresh_thread is None or not self._refresh_thread.is_alive():
            self.cache.load()
            self._refresh_thread = threading.Thread(target=self._refresh_task)
            self._refresh_thread.start()

    def stop_refreshing(self):
        self._refreshing_enabled = False
        if self._refresh_thread is not None and self._refresh_thread.is_alive():
            self._refresh_thread.join()
            self._refresh_thread = None

    def trigger_refresh(self):
        log.debug("trigger_refresh")
        self.last_refresh_time = 0

    def _refresh_task(self):
        while self._refreshing_enabled:

            while not self.needs_refresh() and self._refreshing_enabled:
                time.sleep(1)

            if not self._refreshing_enabled:
                return

            plot_filenames: Dict[Path, List[Path]] = get_plot_filenames(self.root_path)
            plot_directories: Set[Path] = set(plot_filenames.keys())
            plot_paths: List[Path] = []
            for paths in plot_filenames.values():
                plot_paths += paths

            total_result: PlotRefreshResult = PlotRefreshResult()
            total_size = len(plot_paths)

            self._refresh_callback(PlotRefreshEvents.started, PlotRefreshResult(remaining=total_size))

            # First drop all plots we have in plot_filename_paths but not longer in the filesystem or set in config
            def plot_removed(test_path: Path):
                return not test_path.exists() or test_path.parent not in plot_directories

            filenames_to_remove: List[str] = []
            for plot_filename, paths_entry in self.plot_filename_paths.items():
                loaded_path, duplicated_paths = paths_entry
                loaded_plot = Path(loaded_path) / Path(plot_filename)
                if plot_removed(loaded_plot):
                    filenames_to_remove.append(plot_filename)
                    if loaded_plot in self.plots:
                        del self.plots[loaded_plot]
                    total_result.removed += 1
                    # No need to check the duplicates here since we drop the whole entry
                    continue

                paths_to_remove: List[str] = []
                for path in duplicated_paths:
                    if plot_removed(Path(path) / Path(plot_filename)):
                        paths_to_remove.append(path)
                        total_result.removed += 1
                for path in paths_to_remove:
                    duplicated_paths.remove(path)

            for filename in filenames_to_remove:
                del self.plot_filename_paths[filename]

            def batches() -> Iterator[Tuple[int, List[Path]]]:
                if total_size > 0:
                    for batch_start in range(0, total_size, self.refresh_parameter.batch_size):
                        batch_end = min(batch_start + self.refresh_parameter.batch_size, total_size)
                        yield total_size - batch_end, plot_paths[batch_start:batch_end]
                else:
                    yield 0, []

            for remaining, batch in batches():
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

            # Cleanup unused cache
            available_ids = set([plot_info.prover.get_id() for plot_info in self.plots.values()])
            invalid_cache_keys = [plot_id for plot_id in self.cache.keys() if plot_id not in available_ids]
            self.cache.remove(invalid_cache_keys)
            self.log.debug(f"_refresh_task: cached entries removed: {len(invalid_cache_keys)}")

            if self.cache.changed():
                self.cache.save()

            self.last_refresh_time = time.time()

            self.log.debug(
                f"_refresh_task: total_result.loaded {total_result.loaded}, "
                f"total_result.removed {total_result.removed}, "
                f"total_duration {total_result.duration:.2f} seconds"
            )

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

                prover = DiskProver(str(file_path))

                log.debug(f"process_file {str(file_path)}")

                expected_size = _expected_plot_size(prover.get_size()) * UI_ACTUAL_SPACE_CONSTANT_FACTOR
                stat_info = file_path.stat()

                # TODO: consider checking if the file was just written to (which would mean that the file is still
                # being copied). A segfault might happen in this edge case.

                if prover.get_size() >= 30 and stat_info.st_size < 0.98 * expected_size:
                    log.warning(
                        f"Not farming plot {file_path}. Size is {stat_info.st_size / (1024**3)} GiB, but expected"
                        f" at least: {expected_size / (1024 ** 3)} GiB. We assume the file is being copied."
                    )
                    return None

                cache_entry = self.cache.get(prover.get_id())
                if cache_entry is None:
                    (
                        pool_public_key_or_puzzle_hash,
                        farmer_public_key,
                        local_master_sk,
                    ) = parse_plot_info(prover.get_memo())

                    # Only use plots that correct keys associated with them
                    if farmer_public_key not in self.farmer_public_keys:
                        log.warning(f"Plot {file_path} has a farmer public key that is not in the farmer's pk list.")
                        self.no_key_filenames.add(file_path)
                        if not self.open_no_key_filenames:
                            return None

                    pool_public_key: Optional[G1Element] = None
                    pool_contract_puzzle_hash: Optional[bytes32] = None
                    if isinstance(pool_public_key_or_puzzle_hash, G1Element):
                        pool_public_key = pool_public_key_or_puzzle_hash
                    else:
                        assert isinstance(pool_public_key_or_puzzle_hash, bytes32)
                        pool_contract_puzzle_hash = pool_public_key_or_puzzle_hash

                    if pool_public_key is not None and pool_public_key not in self.pool_public_keys:
                        log.warning(f"Plot {file_path} has a pool public key that is not in the farmer's pool pk list.")
                        self.no_key_filenames.add(file_path)
                        if not self.open_no_key_filenames:
                            return None

                    local_sk = master_sk_to_local_sk(local_master_sk)

                    plot_public_key: G1Element = ProofOfSpace.generate_plot_public_key(
                        local_sk.get_g1(), farmer_public_key, pool_contract_puzzle_hash is not None
                    )

                    cache_entry = CacheEntry(pool_public_key, pool_contract_puzzle_hash, plot_public_key)
                    self.cache.update(prover.get_id(), cache_entry)

                with self.plot_filename_paths_lock:
                    paths: Optional[Tuple[str, Set[str]]] = self.plot_filename_paths.get(file_path.name)
                    if paths is None:
                        paths = (str(Path(prover.get_filename()).parent), set())
                        self.plot_filename_paths[file_path.name] = paths
                    else:
                        paths[1].add(str(Path(prover.get_filename()).parent))
                        log.warning(f"Have multiple copies of the plot {file_path.name} in {[paths[0], *paths[1]]}.")
                        return None

                new_plot_info: PlotInfo = PlotInfo(
                    prover,
                    cache_entry.pool_public_key,
                    cache_entry.pool_contract_puzzle_hash,
                    cache_entry.plot_public_key,
                    stat_info.st_size,
                    stat_info.st_mtime,
                )

                with counter_lock:
                    result.loaded += 1

                if file_path in self.failed_to_open_filenames:
                    del self.failed_to_open_filenames[file_path]

            except Exception as e:
                tb = traceback.format_exc()
                log.error(f"Failed to open file {file_path}. {e} {tb}")
                self.failed_to_open_filenames[file_path] = int(time.time())
                return None
            log.info(f"Found plot {file_path} of size {new_plot_info.prover.get_size()}")

            if self.show_memo:
                plot_memo: bytes32
                if pool_contract_puzzle_hash is None:
                    plot_memo = stream_plot_info_pk(pool_public_key, farmer_public_key, local_master_sk)
                else:
                    plot_memo = stream_plot_info_ph(pool_contract_puzzle_hash, farmer_public_key, local_master_sk)
                plot_memo_str: str = plot_memo.hex()
                log.info(f"Memo: {plot_memo_str}")

            return new_plot_info

        with self, ThreadPoolExecutor() as executor:
            plots_refreshed: Dict[Path, PlotInfo] = {}
            for new_plot in executor.map(process_file, plot_paths):
                if new_plot is not None:
                    plots_refreshed[Path(new_plot.prover.get_filename())] = new_plot
            self.plots.update(plots_refreshed)

        result.duration = time.time() - start_time

        self.log.debug(
            f"refresh_batch: loaded {result.loaded}, "
            f"removed {result.removed}, processed {result.processed}, "
            f"remaining {result.remaining}, batch_size {self.refresh_parameter.batch_size}, "
            f"duration: {result.duration:.2f} seconds"
        )
        return result
