import logging
import threading
import time
import traceback
from functools import reduce
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple
from concurrent.futures.thread import ThreadPoolExecutor

from blspy import G1Element
from chiapos import DiskProver

from chia.consensus.pos_quality import UI_ACTUAL_SPACE_CONSTANT_FACTOR, _expected_plot_size
from chia.plotting.util import (
    PlotInfo,
    PlotRefreshResult,
    PlotsRefreshParameter,
    get_plot_directories,
    get_plot_filenames,
    parse_plot_info,
    stream_plot_info_pk,
    stream_plot_info_ph,
)
from chia.types.blockchain_format.proof_of_space import ProofOfSpace
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.wallet.derive_keys import master_sk_to_local_sk

log = logging.getLogger(__name__)


class PlotManager:
    plots: Dict[Path, PlotInfo]
    plot_filename_paths: Dict[str, Tuple[str, Set[str]]]
    plot_filename_paths_lock: threading.Lock
    failed_to_open_filenames: Dict[Path, int]
    no_key_filenames: Set[Path]
    farmer_public_keys: List[G1Element]
    pool_public_keys: List[G1Element]
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

    def needs_refresh(self) -> bool:
        return time.time() - self.last_refresh_time > float(self.refresh_parameter.interval_seconds)

    def start_refreshing(self):
        self._refreshing_enabled = True
        if self._refresh_thread is None or not self._refresh_thread.is_alive():
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

            total_result: PlotRefreshResult = PlotRefreshResult()
            while self.needs_refresh() and self._refreshing_enabled:
                batch_result: PlotRefreshResult = self.refresh_batch()
                total_result += batch_result
                self._refresh_callback(batch_result)
                if batch_result.remaining_files == 0:
                    self.last_refresh_time = time.time()
                    break
                batch_sleep = self.refresh_parameter.batch_sleep_milliseconds
                self.log.debug(f"refresh_plots: Sleep {batch_sleep} milliseconds")
                time.sleep(float(batch_sleep) / 1000.0)

            self.log.debug(
                f"_refresh_task: total_result.loaded_plots {total_result.loaded_plots}, "
                f"total_result.removed_plots {total_result.removed_plots}, "
                f"total_result.loaded_size {total_result.loaded_size / (1024 ** 4):.2f} TiB, "
                f"total_duration {total_result.duration:.2f} seconds"
            )

    def refresh_batch(self) -> PlotRefreshResult:
        start_time: float = time.time()
        plot_filenames: Dict[Path, List[Path]] = get_plot_filenames(self.root_path)
        all_filenames: List[Path] = []
        for paths in plot_filenames.values():
            all_filenames += paths

        result: PlotRefreshResult = PlotRefreshResult()
        counter_lock = threading.Lock()

        log.debug(f"refresh_batch: {len(all_filenames)} files in directories {get_plot_directories(self.root_path)}")

        if self.match_str is not None:
            log.info(f'Only loading plots that contain "{self.match_str}" in the file or directory name')

        def process_file(file_path: Path) -> Dict:
            new_provers: Dict[Path, PlotInfo] = {}
            filename_str = str(file_path)
            if self.match_str is not None and self.match_str not in filename_str:
                return new_provers
            if file_path.exists():
                if (
                    file_path in self.failed_to_open_filenames
                    and (time.time() - self.failed_to_open_filenames[file_path])
                    < self.refresh_parameter.retry_invalid_seconds
                ):
                    # Try once every `refresh_parameter.retry_invalid_seconds` seconds to open the file
                    return new_provers
                if file_path in self.plots:
                    try:
                        stat_info = file_path.stat()
                    except Exception as e:
                        log.error(f"Failed to open file {file_path}. {e}")
                        return new_provers
                    if stat_info.st_mtime == self.plots[file_path].time_modified:
                        new_provers[file_path] = self.plots[file_path]
                        return new_provers
                entry: Optional[Tuple[str, Set[str]]] = self.plot_filename_paths.get(file_path.name)
                if entry is not None:
                    loaded_parent, duplicates = entry
                    if str(file_path.parent) in duplicates:
                        log.debug(f"Skip duplicated plot {str(file_path)}")
                        return new_provers
                try:
                    with counter_lock:
                        if result.processed_files >= self.refresh_parameter.batch_size:
                            result.remaining_files += 1
                            return new_provers
                        result.processed_files += 1

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
                        return new_provers

                    (
                        pool_public_key_or_puzzle_hash,
                        farmer_public_key,
                        local_master_sk,
                    ) = parse_plot_info(prover.get_memo())

                    # Only use plots that correct keys associated with them
                    if self.farmer_public_keys is not None and farmer_public_key not in self.farmer_public_keys:
                        log.warning(f"Plot {file_path} has a farmer public key that is not in the farmer's pk list.")
                        self.no_key_filenames.add(file_path)
                        if not self.open_no_key_filenames:
                            return new_provers

                    if isinstance(pool_public_key_or_puzzle_hash, G1Element):
                        pool_public_key = pool_public_key_or_puzzle_hash
                        pool_contract_puzzle_hash = None
                    else:
                        assert isinstance(pool_public_key_or_puzzle_hash, bytes32)
                        pool_public_key = None
                        pool_contract_puzzle_hash = pool_public_key_or_puzzle_hash

                    if (
                        self.pool_public_keys is not None
                        and pool_public_key is not None
                        and pool_public_key not in self.pool_public_keys
                    ):
                        log.warning(f"Plot {file_path} has a pool public key that is not in the farmer's pool pk list.")
                        self.no_key_filenames.add(file_path)
                        if not self.open_no_key_filenames:
                            return new_provers

                    stat_info = file_path.stat()
                    local_sk = master_sk_to_local_sk(local_master_sk)

                    plot_public_key: G1Element = ProofOfSpace.generate_plot_public_key(
                        local_sk.get_g1(), farmer_public_key, pool_contract_puzzle_hash is not None
                    )

                    with self.plot_filename_paths_lock:
                        if file_path.name not in self.plot_filename_paths:
                            self.plot_filename_paths[file_path.name] = (str(Path(prover.get_filename()).parent), set())
                        else:
                            self.plot_filename_paths[file_path.name][1].add(str(Path(prover.get_filename()).parent))
                        if len(self.plot_filename_paths[file_path.name][1]) > 0:
                            log.warning(
                                f"Have multiple copies of the plot {file_path} in "
                                f"{self.plot_filename_paths[file_path.name][1]}."
                            )
                            return new_provers

                    new_provers[file_path] = PlotInfo(
                        prover,
                        pool_public_key,
                        pool_contract_puzzle_hash,
                        plot_public_key,
                        stat_info.st_size,
                        stat_info.st_mtime,
                    )

                    with counter_lock:
                        result.loaded_plots += 1
                        result.loaded_size += stat_info.st_size

                    if file_path in self.failed_to_open_filenames:
                        del self.failed_to_open_filenames[file_path]

                except Exception as e:
                    tb = traceback.format_exc()
                    log.error(f"Failed to open file {file_path}. {e} {tb}")
                    self.failed_to_open_filenames[file_path] = int(time.time())
                    return new_provers
                log.info(f"Found plot {file_path} of size {new_provers[file_path].prover.get_size()}")

                if self.show_memo:
                    plot_memo: bytes32
                    if pool_contract_puzzle_hash is None:
                        plot_memo = stream_plot_info_pk(pool_public_key, farmer_public_key, local_master_sk)
                    else:
                        plot_memo = stream_plot_info_ph(pool_contract_puzzle_hash, farmer_public_key, local_master_sk)
                    plot_memo_str: str = plot_memo.hex()
                    log.info(f"Memo: {plot_memo_str}")

                return new_provers
            return new_provers

        def reduce_function(x: Dict, y: Dict) -> Dict:
            return {**x, **y}

        with self, ThreadPoolExecutor() as executor:

            # First drop all plots we have in plot_filename_paths but not longer in the filesystem or set in config
            def plot_removed(test_path: Path):
                return not test_path.exists() or test_path.parent not in plot_filenames

            with self.plot_filename_paths_lock:
                filenames_to_remove: List[str] = []
                for plot_filename, paths_entry in self.plot_filename_paths.items():
                    loaded_path, duplicated_paths = paths_entry
                    if plot_removed(Path(loaded_path) / Path(plot_filename)):
                        filenames_to_remove.append(plot_filename)
                        result.removed_plots += 1
                        # No need to check the duplicates here since we drop the whole entry
                        continue

                    paths_to_remove: List[str] = []
                    for path in duplicated_paths:
                        if plot_removed(Path(path) / Path(plot_filename)):
                            paths_to_remove.append(path)
                            result.removed_plots += 1
                    for path in paths_to_remove:
                        duplicated_paths.remove(path)

                for filename in filenames_to_remove:
                    del self.plot_filename_paths[filename]

            initial_value: Dict[Path, PlotInfo] = {}
            self.plots = reduce(reduce_function, executor.map(process_file, all_filenames), initial_value)

        result.duration = time.time() - start_time

        self.log.debug(
            f"refresh_batch: loaded_plots {result.loaded_plots}, "
            f"loaded_size {result.loaded_size / (1024 ** 4):.2f} TiB, "
            f"removed_plots {result.removed_plots}, processed_plots {result.processed_files}, "
            f"remaining_plots {result.remaining_files}, batch_size {self.refresh_parameter.batch_size}, "
            f"duration: {result.duration:.2f} seconds"
        )
        return result
