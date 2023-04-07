from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

from blspy import G1Element, PrivateKey
from chiapos import DiskProver
from typing_extensions import final

from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.config import load_config, lock_and_load_config, save_config
from chia.util.ints import uint32
from chia.util.streamable import Streamable, streamable

log = logging.getLogger(__name__)


@streamable
@dataclass(frozen=True)
class PlotsRefreshParameter(Streamable):
    interval_seconds: uint32 = uint32(120)
    retry_invalid_seconds: uint32 = uint32(1200)
    batch_size: uint32 = uint32(300)
    batch_sleep_milliseconds: uint32 = uint32(1)


@dataclass
class PlotInfo:
    prover: DiskProver
    pool_public_key: Optional[G1Element]
    pool_contract_puzzle_hash: Optional[bytes32]
    plot_public_key: G1Element
    file_size: int
    time_modified: float


class PlotRefreshEvents(Enum):
    """
    This are the events the `PlotManager` will trigger with the callback during a full refresh cycle:

      - started: This event indicates the start of a refresh cycle and contains the total number of files to
                 process in `PlotRefreshResult.remaining`.

      - batch_processed: This event gets triggered if one batch has been processed. The values of
                         `PlotRefreshResult.{loaded|removed|processed}` are the results of this specific batch.

      - done: This event gets triggered after all batches has been processed. The values of
              `PlotRefreshResult.{loaded|removed|processed}` are the totals of all batches.

      Note: The values of `PlotRefreshResult.{remaining|duration}` have the same meaning for all events.
    """

    started = 0
    batch_processed = 1
    done = 2


@dataclass
class PlotRefreshResult:
    loaded: List[PlotInfo] = field(default_factory=list)
    removed: List[Path] = field(default_factory=list)
    processed: int = 0
    remaining: int = 0
    duration: float = 0


@final
@dataclass
class Params:
    size: int
    num: int
    buffer: int
    num_threads: int
    buckets: int
    tmp_dir: Path
    tmp2_dir: Optional[Path]
    final_dir: Path
    plotid: Optional[str]
    memo: Optional[str]
    nobitfield: bool
    stripe_size: int = 65536


def get_plot_directories(root_path: Path, config: Dict = None) -> List[str]:
    if config is None:
        config = load_config(root_path, "config.yaml")
    return config["harvester"]["plot_directories"] or []


def get_plot_filenames(root_path: Path) -> Dict[Path, List[Path]]:
    # Returns a map from directory to a list of all plots in the directory
    all_files: Dict[Path, List[Path]] = {}
    config = load_config(root_path, "config.yaml")
    recursive_scan: bool = config["harvester"].get("recursive_plot_scan", False)
    for directory_name in get_plot_directories(root_path, config):
        try:
            directory = Path(directory_name).resolve()
        except (OSError, RuntimeError):
            log.exception(f"Failed to resolve {directory_name}")
            continue
        all_files[directory] = get_filenames(directory, recursive_scan)
    return all_files


def add_plot_directory(root_path: Path, str_path: str) -> Dict:
    path: Path = Path(str_path).resolve()
    if not path.exists():
        raise ValueError(f"Path doesn't exist: {path}")
    if not path.is_dir():
        raise ValueError(f"Path is not a directory: {path}")
    log.debug(f"add_plot_directory {str_path}")
    with lock_and_load_config(root_path, "config.yaml") as config:
        if str(Path(str_path).resolve()) in get_plot_directories(root_path, config):
            raise ValueError(f"Path already added: {path}")
        if not config["harvester"]["plot_directories"]:
            config["harvester"]["plot_directories"] = []
        config["harvester"]["plot_directories"].append(str(Path(str_path).resolve()))
        save_config(root_path, "config.yaml", config)
    return config


def remove_plot_directory(root_path: Path, str_path: str) -> None:
    log.debug(f"remove_plot_directory {str_path}")
    with lock_and_load_config(root_path, "config.yaml") as config:
        str_paths: List[str] = get_plot_directories(root_path, config)
        # If path str matches exactly, remove
        if str_path in str_paths:
            str_paths.remove(str_path)

        # If path matches full path, remove
        new_paths = [Path(sp).resolve() for sp in str_paths]
        if Path(str_path).resolve() in new_paths:
            new_paths.remove(Path(str_path).resolve())

        config["harvester"]["plot_directories"] = [str(np) for np in new_paths]
        save_config(root_path, "config.yaml", config)


def remove_plot(path: Path):
    log.debug(f"remove_plot {str(path)}")
    # Remove absolute and relative paths
    if path.exists():
        path.unlink()


def get_filenames(directory: Path, recursive: bool) -> List[Path]:
    try:
        if not directory.exists():
            log.warning(f"Directory: {directory} does not exist.")
            return []
    except OSError as e:
        log.warning(f"Error checking if directory {directory} exists: {e}")
        return []
    all_files: List[Path] = []
    try:
        glob_function = directory.rglob if recursive else directory.glob
        all_files = [child for child in glob_function("*.plot") if child.is_file() and not child.name.startswith("._")]
        log.debug(f"get_filenames: {len(all_files)} files found in {directory}, recursive: {recursive}")
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


def validate_plot_size(root_path: Path, k: int, override_k: bool) -> None:
    config = load_config(root_path, "config.yaml")
    min_k = config["min_mainnet_k_size"]
    if k < min_k and not override_k:
        raise ValueError(
            f"k={min_k} is the minimum size for farming.\n"
            "If you are testing and you want to use smaller size please add the --override-k flag."
        )
    elif k < 25 and override_k:
        raise ValueError("Error: The minimum k size allowed from the cli is k=25.")
