import logging
import threading
import time
import traceback
from dataclasses import dataclass
from functools import reduce
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union
from concurrent.futures.thread import ThreadPoolExecutor

from blspy import G1Element, PrivateKey
from chiapos import DiskProver

from chia.consensus.pos_quality import UI_ACTUAL_SPACE_CONSTANT_FACTOR, _expected_plot_size
from chia.types.blockchain_format.proof_of_space import ProofOfSpace
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.config import load_config, save_config
from chia.util.ints import uint16
from chia.util.streamable import Streamable, streamable
from chia.wallet.derive_keys import master_sk_to_local_sk

log = logging.getLogger(__name__)


@dataclass(frozen=True)
@streamable
class PlotsRefreshParameter(Streamable):
    interval_seconds: uint16 = uint16(120)
    batch_size: uint16 = uint16(30)
    batch_sleep_milliseconds: uint16 = uint16(10)


@dataclass
class PlotInfo:
    prover: DiskProver
    pool_public_key: Optional[G1Element]
    pool_contract_puzzle_hash: Optional[bytes32]
    plot_public_key: G1Element
    file_size: int
    time_modified: float


def _get_filenames(directory: Path) -> List[Path]:
    try:
        if not directory.exists():
            log.warning(f"Directory: {directory} does not exist.")
            return []
    except OSError as e:
        log.warning(f"Error checking if directory {directory} exists: {e}")
        return []
    all_files: List[Path] = []
    try:
        for child in directory.iterdir():
            if not child.is_dir():
                # If it is a file ending in .plot, add it - work around MacOS ._ files
                if child.suffix == ".plot" and not child.name.startswith("._"):
                    all_files.append(child)
            else:
                log.debug(f"Not checking subdirectory {child}, subdirectories not added by default")
    except Exception as e:
        log.warning(f"Error reading directory {directory} {e}")
    return all_files


def parse_plot_info(memo: bytes) -> Tuple[Union[G1Element, bytes32], G1Element, PrivateKey]:
    # Parses the plot info bytes into keys
    if len(memo) == (48 + 48 + 32):
        # This is a public key memo
        return (
            G1Element.from_bytes(memo[:48]),
            G1Element.from_bytes(memo[48:96]),
            PrivateKey.from_bytes(memo[96:]),
        )
    elif len(memo) == (32 + 48 + 32):
        # This is a pool_contract_puzzle_hash memo
        return (
            bytes32(memo[:32]),
            G1Element.from_bytes(memo[32:80]),
            PrivateKey.from_bytes(memo[80:]),
        )
    else:
        raise ValueError(f"Invalid number of bytes {len(memo)}")


def stream_plot_info_pk(
    pool_public_key: G1Element,
    farmer_public_key: G1Element,
    local_master_sk: PrivateKey,
):
    # There are two ways to stream plot info: with a pool public key, or with a pool contract puzzle hash.
    # This one streams the public key, into bytes
    data = bytes(pool_public_key) + bytes(farmer_public_key) + bytes(local_master_sk)
    assert len(data) == (48 + 48 + 32)
    return data


def stream_plot_info_ph(
    pool_contract_puzzle_hash: bytes32,
    farmer_public_key: G1Element,
    local_master_sk: PrivateKey,
):
    # There are two ways to stream plot info: with a pool public key, or with a pool contract puzzle hash.
    # This one streams the pool contract puzzle hash, into bytes
    data = pool_contract_puzzle_hash + bytes(farmer_public_key) + bytes(local_master_sk)
    assert len(data) == (32 + 48 + 32)
    return data


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
    _refresh_callback: Optional[Callable]

    def __init__(
        self,
        root_path: Path,
        match_str: Optional[str] = None,
        show_memo: bool = False,
        open_no_key_filenames: bool = False,
        refresh_parameter: PlotsRefreshParameter = PlotsRefreshParameter(),
        refresh_callback: Optional[Callable] = None,
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
        self._refresh_callback = refresh_callback

    def __enter__(self):
        self._lock.acquire()

    def __exit__(self, exc_type, exc_value, exc_traceback):
        self._lock.release()

    def set_refresh_callback(self, callback: Callable):
        self._refresh_callback = callback

    def set_public_keys(self, farmer_public_keys: List[G1Element], pool_public_keys: List[G1Element]):
        self.farmer_public_keys = farmer_public_keys
        self.pool_public_keys = pool_public_keys

    def public_keys_available(self):
        return len(self.farmer_public_keys) and len(self.pool_public_keys)

    def get_plot_directories(self, config: Dict = None) -> List[str]:
        if config is None:
            config = load_config(self.root_path, "config.yaml")
        return config["harvester"]["plot_directories"]

    def get_plot_filenames(self) -> Dict[Path, List[Path]]:
        # Returns a map from directory to a list of all plots in the directory
        all_files: Dict[Path, List[Path]] = {}
        for directory_name in self.get_plot_directories():
            directory = Path(directory_name).resolve()
            all_files[directory] = _get_filenames(directory)
        return all_files

    def plot_count(self):
        with self:
            return len(self.plots)

    def add_plot_directory(self, str_path: str) -> Dict:
        log.debug(f"add_plot_directory {str_path}")
        config = load_config(self.root_path, "config.yaml")
        if str(Path(str_path).resolve()) not in self.get_plot_directories(config):
            config["harvester"]["plot_directories"].append(str(Path(str_path).resolve()))
        save_config(self.root_path, "config.yaml", config)
        self.trigger_refresh()
        return config

    def remove_plot_directory(self, str_path: str) -> None:
        log.debug(f"remove_plot_directory {str_path}")
        config = load_config(self.root_path, "config.yaml")
        str_paths: List[str] = self.get_plot_directories(config)
        # If path str matches exactly, remove
        if str_path in str_paths:
            str_paths.remove(str_path)

        # If path matcehs full path, remove
        new_paths = [Path(sp).resolve() for sp in str_paths]
        if Path(str_path).resolve() in new_paths:
            new_paths.remove(Path(str_path).resolve())

        config["harvester"]["plot_directories"] = [str(np) for np in new_paths]
        save_config(self.root_path, "config.yaml", config)
        self.trigger_refresh()

    def remove_plot(self, path: Path):
        log.debug(f"remove_plot {str(path)}")
        # Remove absolute and relative paths
        if path.exists():
            path.unlink()

        self.trigger_refresh()

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

            total_loaded_plots: int = 0
            total_removed_plots: int = 0
            total_loaded_size: int = 0
            total_duration: float = 0
            while self.needs_refresh() and self._refreshing_enabled:
                (
                    loaded_plots,
                    loaded_size,
                    removed_plots,
                    processed_files,
                    remaining_files,
                    duration,
                ) = self.refresh_batch()
                total_loaded_plots += loaded_plots
                total_removed_plots += removed_plots
                total_loaded_size += loaded_size
                total_duration += duration
                if self._refresh_callback is not None:
                    self._refresh_callback(loaded_plots, processed_files, remaining_files)
                if remaining_files == 0:
                    self.last_refresh_time = time.time()
                    break
                batch_sleep = self.refresh_parameter.batch_sleep_milliseconds
                self.log.debug(f"refresh_plots: Sleep {batch_sleep} milliseconds")
                time.sleep(float(batch_sleep) / 1000.0)

            self.log.debug(
                f"_refresh_task: total_loaded_plots {total_loaded_plots}, total_removed_plots {total_removed_plots}, "
                f"total_loaded_size {total_loaded_size / (1024 ** 4)} TiB, total_duration {total_duration} seconds"
            )

    def refresh_batch(self) -> Tuple[int, int, int, int, int, float]:
        start_time: float = time.time()
        plot_filenames: Dict[Path, List[Path]] = self.get_plot_filenames()
        all_filenames: List[Path] = []
        for paths in plot_filenames.values():
            all_filenames += paths
        processed_plots: int = 0
        loaded_plots: int = 0
        loaded_size: int = 0
        remaining_plots: int = 0
        removed_plots: int = 0
        counter_lock = threading.Lock()

        log.debug(f"refresh_batch: {len(all_filenames)} files in directories {self.get_plot_directories()}")

        if self.match_str is not None:
            log.info(f'Only loading plots that contain "{self.match_str}" in the file or directory name')

        def process_file(filename: Path) -> Dict:
            new_provers: Dict[Path, PlotInfo] = {}
            nonlocal processed_plots
            nonlocal loaded_plots
            nonlocal loaded_size
            nonlocal remaining_plots
            filename_str = str(filename)
            if self.match_str is not None and self.match_str not in filename_str:
                return new_provers
            if filename.exists():
                if (
                    filename in self.failed_to_open_filenames
                    and (time.time() - self.failed_to_open_filenames[filename]) > 1200
                ):
                    # Try once every 20 minutes to open the file
                    return new_provers
                if filename in self.plots:
                    try:
                        stat_info = filename.stat()
                    except Exception as e:
                        log.error(f"Failed to open file {filename}. {e}")
                        return new_provers
                    if stat_info.st_mtime == self.plots[filename].time_modified:
                        new_provers[filename] = self.plots[filename]
                        return new_provers
                entry: Optional[Tuple[str, Set[str]]] = self.plot_filename_paths.get(filename.name)
                if entry is not None:
                    loaded_parent, duplicates = entry
                    if str(filename.parent) in duplicates:
                        log.debug(f"Skip duplicated plot {str(filename)}")
                        return new_provers
                try:
                    with counter_lock:
                        if processed_plots >= self.refresh_parameter.batch_size:
                            remaining_plots += 1
                            return new_provers
                        processed_plots += 1

                    prover = DiskProver(str(filename))

                    log.debug(f"process_file {str(filename)}")

                    expected_size = _expected_plot_size(prover.get_size()) * UI_ACTUAL_SPACE_CONSTANT_FACTOR
                    stat_info = filename.stat()

                    # TODO: consider checking if the file was just written to (which would mean that the file is still
                    # being copied). A segfault might happen in this edge case.

                    if prover.get_size() >= 30 and stat_info.st_size < 0.98 * expected_size:
                        log.warning(
                            f"Not farming plot {filename}. Size is {stat_info.st_size / (1024**3)} GiB, but expected"
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
                        log.warning(f"Plot {filename} has a farmer public key that is not in the farmer's pk list.")
                        self.no_key_filenames.add(filename)
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
                        log.warning(f"Plot {filename} has a pool public key that is not in the farmer's pool pk list.")
                        self.no_key_filenames.add(filename)
                        if not self.open_no_key_filenames:
                            return new_provers

                    stat_info = filename.stat()
                    local_sk = master_sk_to_local_sk(local_master_sk)

                    plot_public_key: G1Element = ProofOfSpace.generate_plot_public_key(
                        local_sk.get_g1(), farmer_public_key, pool_contract_puzzle_hash is not None
                    )

                    with self.plot_filename_paths_lock:
                        if filename.name not in self.plot_filename_paths:
                            self.plot_filename_paths[filename.name] = (str(Path(prover.get_filename()).parent), set())
                        else:
                            self.plot_filename_paths[filename.name][1].add(str(Path(prover.get_filename()).parent))
                        if len(self.plot_filename_paths[filename.name][1]) > 0:
                            log.warning(
                                f"Have multiple copies of the plot {filename} in "
                                f"{self.plot_filename_paths[filename.name][1]}."
                            )
                            return new_provers

                    new_provers[filename] = PlotInfo(
                        prover,
                        pool_public_key,
                        pool_contract_puzzle_hash,
                        plot_public_key,
                        stat_info.st_size,
                        stat_info.st_mtime,
                    )

                    with counter_lock:
                        loaded_plots += 1
                        loaded_size += stat_info.st_size

                except Exception as e:
                    tb = traceback.format_exc()
                    log.error(f"Failed to open file {filename}. {e} {tb}")
                    self.failed_to_open_filenames[filename] = int(time.time())
                    return new_provers
                log.info(f"Found plot {filename} of size {new_provers[filename].prover.get_size()}")

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
                        removed_plots += 1
                        # No need to check the duplicates here since we drop the whole entry
                        continue

                    paths_to_remove: List[str] = []
                    for path in duplicated_paths:
                        if plot_removed(Path(path) / Path(plot_filename)):
                            paths_to_remove.append(path)
                            removed_plots += 1
                    for path in paths_to_remove:
                        duplicated_paths.remove(path)

                for filename in filenames_to_remove:
                    del self.plot_filename_paths[filename]

            initial_value: Dict[Path, PlotInfo] = {}
            self.plots = reduce(reduce_function, executor.map(process_file, all_filenames), initial_value)

        duration: float = time.time() - start_time

        self.log.debug(
            f"refresh_batch: loaded_plots {loaded_plots}, loaded_size {loaded_size / (1024 ** 4)} TiB, "
            f"removed_plots {removed_plots}, processed_plots {processed_plots}, remaining_plots {remaining_plots}, "
            f"batch_size {self.refresh_parameter.batch_size}, duration: {duration} seconds"
        )
        return loaded_plots, loaded_size, removed_plots, processed_plots, remaining_plots, duration


def find_duplicate_plot_IDs(all_filenames=None) -> None:
    if all_filenames is None:
        all_filenames = []
    plot_ids_set = set()
    duplicate_plot_ids = set()
    all_filenames_str: List[str] = []

    for filename in all_filenames:
        filename_str: str = str(filename)
        all_filenames_str.append(filename_str)
        filename_parts: List[str] = filename_str.split("-")
        plot_id: str = filename_parts[-1]
        # Skipped parsing and verifying plot ID for faster performance
        # Skipped checking K size for faster performance
        # Only checks end of filenames: 64 char plot ID + .plot = 69 characters
        if len(plot_id) == 69:
            if plot_id in plot_ids_set:
                duplicate_plot_ids.add(plot_id)
            else:
                plot_ids_set.add(plot_id)
        else:
            log.warning(f"{filename} does not end with -[64 char plot ID].plot")

    for plot_id in duplicate_plot_ids:
        log_message: str = plot_id + " found in multiple files:\n"
        duplicate_filenames: List[str] = [filename_str for filename_str in all_filenames_str if plot_id in filename_str]
        for filename_str in duplicate_filenames:
            log_message += "\t" + filename_str + "\n"
        log.warning(f"{log_message}")
