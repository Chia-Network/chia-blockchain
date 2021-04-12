import concurrent
import logging
import time
import traceback
from concurrent.futures import Future
from dataclasses import dataclass
from enum import IntEnum
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple, Union
from concurrent.futures.thread import ThreadPoolExecutor

from blspy import G1Element, PrivateKey
from chiapos import DiskProver

from chia.consensus.pos_quality import UI_ACTUAL_SPACE_CONSTANT_FACTOR, _expected_plot_size
from chia.types.blockchain_format.proof_of_space import ProofOfSpace
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.config import load_config, save_config
from chia.wallet.derive_keys import master_sk_to_local_sk

log = logging.getLogger(__name__)


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
                log.info(f"Not checking subdirectory {child}, subdirectories not added by default")
    except Exception as e:
        log.warning(f"Error reading directory {directory} {e}")
    return all_files


def get_plot_filenames(config: Dict) -> Dict[Path, List[Path]]:
    # Returns a map from directory to a list of all plots in the directory
    directory_names: List[str] = config["plot_directories"]
    all_files: Dict[Path, List[Path]] = {}
    for directory_name in directory_names:
        directory = Path(directory_name).resolve()
        all_files[directory] = _get_filenames(directory)
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


def add_plot_directory(str_path: str, root_path: Path) -> Dict:
    config = load_config(root_path, "config.yaml")
    if str(Path(str_path).resolve()) not in config["harvester"]["plot_directories"]:
        config["harvester"]["plot_directories"].append(str(Path(str_path).resolve()))
    save_config(root_path, "config.yaml", config)
    return config


def get_plot_directories(root_path: Path) -> List[str]:
    config = load_config(root_path, "config.yaml")
    return [str(Path(str_path).resolve()) for str_path in config["harvester"]["plot_directories"]]


def remove_plot_directory(str_path: str, root_path: Path) -> None:
    config = load_config(root_path, "config.yaml")
    str_paths: List[str] = config["harvester"]["plot_directories"]
    # If path str matches exactly, remove
    if str_path in str_paths:
        str_paths.remove(str_path)

    # If path matcehs full path, remove
    new_paths = [Path(sp).resolve() for sp in str_paths]
    if Path(str_path).resolve() in new_paths:
        new_paths.remove(Path(str_path).resolve())

    config["harvester"]["plot_directories"] = [str(np) for np in new_paths]
    save_config(root_path, "config.yaml", config)


class LoadPlotResult(IntEnum):
    SUCCESS = 0
    SUCCESS_BUT_NO_KEY = 1
    ALREADY_LOADED = 2
    WILL_NOT_LOAD_YET = 3
    DUPLICATE = 4
    INVALID_FILE_SIZE = 5
    ERROR_STATING_FILE = 6
    DOES_NOT_MATCH_STR = 7
    NO_FARMER_PUBLIC_KEY = 8
    NO_POOL_PUBLIC_KEY = 9
    FAILED_TO_OPEN = 10
    FILE_DOES_NOT_EXIST = 11


def load_one_plot(
    filename: Path,
    failed_to_open_filenames: Dict[Path, int],
    provers: Dict[Path, PlotInfo],
    match_str: str,
    show_memo: bool,
    open_no_key_filenames: bool,
    farmer_public_keys: Optional[List[G1Element]],
    pool_public_keys: Optional[List[G1Element]],
) -> Tuple[LoadPlotResult, Optional[PlotInfo]]:
    filename_str = str(filename)
    if match_str is not None and match_str not in filename_str:
        return LoadPlotResult.DOES_NOT_MATCH_STR, None
    if not filename.exists():
        return LoadPlotResult.FILE_DOES_NOT_EXIST, None

    if filename in failed_to_open_filenames and (time.time() - failed_to_open_filenames[filename]) < 1200:
        # Try once every 20 minutes to open the file
        return LoadPlotResult.WILL_NOT_LOAD_YET, None
    if filename in provers:
        try:
            stat_info = filename.stat()
        except Exception as e:
            log.error(f"Failed to open file {filename}. {e}")
            return LoadPlotResult.ERROR_STATING_FILE, None
        if stat_info.st_mtime == provers[filename].time_modified:
            log.info(f"Found (already loaded) plot {filename} of size {provers[filename].prover.get_size()}")
            return LoadPlotResult.ALREADY_LOADED, provers[filename]
    try:
        no_key: bool = False  # This gets set when when we don't have the pool or farmer keys on this machine
        prover: DiskProver = DiskProver(str(filename))

        expected_size: int = int(_expected_plot_size(prover.get_size()) * UI_ACTUAL_SPACE_CONSTANT_FACTOR)
        stat_info = filename.stat()

        # TODO: consider checking if the file was just written to (which would mean that the file is still being copied)

        if prover.get_size() >= 30 and stat_info.st_size < 0.98 * expected_size:
            log.warning(
                f"Not farming plot {filename}. Size is {stat_info.st_size / (1024 ** 3)} GiB, but expected"
                f" at least: {expected_size / (1024 ** 3)} GiB. We assume the file is being copied."
            )
            return LoadPlotResult.INVALID_FILE_SIZE, None

        (
            pool_public_key_or_puzzle_hash,
            farmer_public_key,
            local_master_sk,
        ) = parse_plot_info(prover.get_memo())

        # Only use plots that correct keys associated with them
        if farmer_public_keys is not None and farmer_public_key not in farmer_public_keys:
            log.warning(f"Plot {filename} has a farmer public key that is not in the farmer's pk list.")
            no_key = True
            if not open_no_key_filenames:
                return LoadPlotResult.NO_FARMER_PUBLIC_KEY, None

        if isinstance(pool_public_key_or_puzzle_hash, G1Element):
            pool_public_key = pool_public_key_or_puzzle_hash
            pool_contract_puzzle_hash = None
        else:
            assert isinstance(pool_public_key_or_puzzle_hash, bytes32)
            pool_public_key = None
            pool_contract_puzzle_hash = pool_public_key_or_puzzle_hash

        if pool_public_keys is not None and pool_public_key is not None and pool_public_key not in pool_public_keys:
            log.warning(f"Plot {filename} has a pool public key that is not in the farmer's pool pk list.")
            no_key = True
            if not open_no_key_filenames:
                return LoadPlotResult.NO_POOL_PUBLIC_KEY, None

        stat_info = filename.stat()
        local_sk = master_sk_to_local_sk(local_master_sk)
        plot_public_key: G1Element = ProofOfSpace.generate_plot_public_key(local_sk.get_g1(), farmer_public_key)
        log.info(f"Found new plot {filename} of size {prover.get_size()}")

        if show_memo:
            plot_memo: bytes32
            if pool_contract_puzzle_hash is None:
                plot_memo = stream_plot_info_pk(pool_public_key, farmer_public_key, local_master_sk)
            else:
                plot_memo = stream_plot_info_ph(pool_contract_puzzle_hash, farmer_public_key, local_master_sk)
            plot_memo_str: str = plot_memo.hex()
            log.info(f"Memo: {plot_memo_str}")

        new_plot_info = PlotInfo(
            prover,
            pool_public_key,
            pool_contract_puzzle_hash,
            plot_public_key,
            stat_info.st_size,
            stat_info.st_mtime,
        )
        if no_key:
            return LoadPlotResult.SUCCESS_BUT_NO_KEY, new_plot_info
        else:
            return LoadPlotResult.SUCCESS, new_plot_info

    except Exception as e:
        tb = traceback.format_exc()
        log.error(f"Failed to open file {filename}. {e} {tb}")
        return LoadPlotResult.FAILED_TO_OPEN, None


def load_plots(
    provers: Dict[Path, PlotInfo],
    failed_to_open_filenames: Dict[Path, int],
    farmer_public_keys: Optional[List[G1Element]],
    pool_public_keys: Optional[List[G1Element]],
    match_str: Optional[str],
    show_memo: bool,
    root_path: Path,
    open_no_key_filenames=False,
) -> Tuple[bool, Dict[Path, PlotInfo], Dict[Path, int], Set[Path]]:
    start_time = time.time()
    config_file = load_config(root_path, "config.yaml", "harvester")
    changed = False
    no_key_filenames: Set[Path] = set()
    log.info(f'Searching directories {config_file["plot_directories"]}')

    plot_filenames: Dict[Path, List[Path]] = get_plot_filenames(config_file)
    all_filenames: List[Path] = []
    for paths in plot_filenames.values():
        all_filenames += paths
    new_provers: Dict[bytes32, PlotInfo] = {}
    plot_ids: Set[bytes32] = set()
    total_size: int = 0

    if match_str is not None:
        log.info(f'Only loading plots that contain "{match_str}" in the file or directory name')

    with ThreadPoolExecutor() as executor:
        future_to_filename: Dict[Future, Path] = {
            executor.submit(
                load_one_plot,
                filename,
                failed_to_open_filenames,
                provers,
                match_str,
                show_memo,
                open_no_key_filenames,
                farmer_public_keys,
                pool_public_keys,
            ): filename
            for filename in all_filenames
        }
        for future in concurrent.futures.as_completed(future_to_filename):
            filename = future_to_filename[future]
            try:
                result, plot_info = future.result()

                if result == LoadPlotResult.SUCCESS or result == LoadPlotResult.SUCCESS_BUT_NO_KEY:
                    changed = True

                if plot_info is not None:
                    assert (
                        result == LoadPlotResult.SUCCESS
                        or result == LoadPlotResult.SUCCESS_BUT_NO_KEY
                        or result == LoadPlotResult.ALREADY_LOADED
                    )

                    if plot_info.prover.get_id() in plot_ids:
                        log.warning(f"Have multiple copies of the plot {filename}, not adding it.")
                        continue
                    new_provers[filename] = plot_info
                    total_size += new_provers[filename].file_size

                    plot_ids.add(new_provers[filename].prover.get_id())

                if (
                    result == LoadPlotResult.SUCCESS_BUT_NO_KEY
                    or result == LoadPlotResult.NO_POOL_PUBLIC_KEY
                    or result == LoadPlotResult.NO_FARMER_PUBLIC_KEY
                ):
                    no_key_filenames.add(filename)
                if (
                    result == LoadPlotResult.INVALID_FILE_SIZE
                    or result == LoadPlotResult.ERROR_STATING_FILE
                    or result == LoadPlotResult.FAILED_TO_OPEN
                ):
                    failed_to_open_filenames[filename] = int(time.time())

            except Exception as e:
                tb = traceback.format_exc()
                log.error(f"Error loading plot file {filename}, {e} {tb}")

    log.info(
        f"Loaded a total of {len(new_provers)} plots of size {total_size / (1024 ** 4)} TiB, in"
        f" {time.time() - start_time} seconds"
    )
    return changed, new_provers, failed_to_open_filenames, no_key_filenames


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
