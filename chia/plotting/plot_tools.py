import logging
import threading
import time
import traceback
from dataclasses import dataclass
from functools import reduce
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple, Union
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

    def __init__(
        self,
        root_path: Path,
        match_str: Optional[str] = None,
        show_memo: bool = False,
        open_no_key_filenames: bool = False,
        refresh_parameter: PlotsRefreshParameter = PlotsRefreshParameter(),
    ):
        self.root_path = root_path
        self.plots = {}
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
        return len(self.plots)

    def add_plot_directory(self, str_path: str) -> Dict:
        log.debug(f"add_plot_directory {str_path}")
        config = load_config(self.root_path, "config.yaml")
        if str(Path(str_path).resolve()) not in self.get_plot_directories(config):
            config["harvester"]["plot_directories"].append(str(Path(str_path).resolve()))
        save_config(self.root_path, "config.yaml", config)
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

    def remove_plot(self, path: Path):
        log.debug(f"remove_plot {str(path)}")
        path = path.resolve()
        if path in self.plots:
            del self.plots[path]

        # Remove absolute and relative paths
        if path.exists():
            path.unlink()

    def needs_refresh(self) -> bool:
        return time.time() - self.last_refresh_time > float(self.refresh_parameter.interval_seconds)

    def refresh(self) -> int:
        self.last_refresh_time = time.time()
        log.info(f"Searching directories {self.get_plot_directories()}")

        plot_filenames: Dict[Path, List[Path]] = self.get_plot_filenames()
        all_filenames: List[Path] = []
        for paths in plot_filenames.values():
            all_filenames += paths
        plot_ids: Set[bytes32] = set()
        plot_ids_lock = threading.Lock()
        loaded_plots: int = 0
        counter_lock = threading.Lock()

        log.debug(f"refresh_batch: {len(all_filenames)} files in directories {self.get_plot_directories()}")

        if self.match_str is not None:
            log.info(f'Only loading plots that contain "{self.match_str}" in the file or directory name')

        def process_file(filename: Path) -> Tuple[int, Dict]:
            new_provers: Dict[Path, PlotInfo] = {}
            nonlocal loaded_plots
            filename_str = str(filename)
            if self.match_str is not None and self.match_str not in filename_str:
                return 0, new_provers
            if filename.exists():
                if (
                    filename in self.failed_to_open_filenames
                    and (time.time() - self.failed_to_open_filenames[filename]) < 1200
                ):
                    # Try once every 20 minutes to open the file
                    return 0, new_provers
                if filename in self.plots:
                    try:
                        stat_info = filename.stat()
                    except Exception as e:
                        log.error(f"Failed to open file {filename}. {e}")
                        return 0, new_provers
                    if stat_info.st_mtime == self.plots[filename].time_modified:
                        with plot_ids_lock:
                            if self.plots[filename].prover.get_id() in plot_ids:
                                log.warning(f"Have multiple copies of the plot {filename}, not adding it.")
                                return 0, new_provers
                            plot_ids.add(self.plots[filename].prover.get_id())
                        new_provers[filename] = self.plots[filename]
                        return stat_info.st_size, new_provers
                try:
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
                        return 0, new_provers

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
                            return 0, new_provers

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
                            return 0, new_provers

                    stat_info = filename.stat()
                    local_sk = master_sk_to_local_sk(local_master_sk)

                    plot_public_key: G1Element = ProofOfSpace.generate_plot_public_key(
                        local_sk.get_g1(), farmer_public_key, pool_contract_puzzle_hash is not None
                    )

                    with plot_ids_lock:
                        if prover.get_id() in plot_ids:
                            log.warning(f"Have multiple copies of the plot {filename}, not adding it.")
                            return 0, new_provers
                        plot_ids.add(prover.get_id())

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

                except Exception as e:
                    tb = traceback.format_exc()
                    log.error(f"Failed to open file {filename}. {e} {tb}")
                    self.failed_to_open_filenames[filename] = int(time.time())
                    return 0, new_provers
                log.info(f"Found plot {filename} of size {new_provers[filename].prover.get_size()}")

                if self.show_memo:
                    plot_memo: bytes32
                    if pool_contract_puzzle_hash is None:
                        plot_memo = stream_plot_info_pk(pool_public_key, farmer_public_key, local_master_sk)
                    else:
                        plot_memo = stream_plot_info_ph(pool_contract_puzzle_hash, farmer_public_key, local_master_sk)
                    plot_memo_str: str = plot_memo.hex()
                    log.info(f"Memo: {plot_memo_str}")

                return stat_info.st_size, new_provers
            return 0, new_provers

        def reduce_function(x: Tuple[int, Dict], y: Tuple[int, Dict]) -> Tuple[int, Dict]:
            (total_size1, new_provers1) = x
            (total_size2, new_provers2) = y
            return total_size1 + total_size2, {**new_provers1, **new_provers2}

        with ThreadPoolExecutor() as executor:
            initial_value: Tuple[int, Dict[Path, PlotInfo]] = (0, {})
            total_size, self.plots = reduce(reduce_function, executor.map(process_file, all_filenames), initial_value)

        log.info(
            f"Loaded a total of {self.plot_count()} plots of size {total_size / (1024 ** 4)} TiB, in"
            f" {time.time() - self.last_refresh_time} seconds"
        )
        return loaded_plots


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
