from typing import List, Dict, Optional, Tuple, Set
from pathlib import Path
from blspy import PrivateKey, G1Element
from chiapos import DiskProver
from dataclasses import dataclass
import logging
import traceback
from src.types.proof_of_space import ProofOfSpace
from src.util.config import load_config, save_config
from src.wallet.derive_keys import master_sk_to_local_sk


log = logging.getLogger(__name__)


@dataclass
class PlotInfo:
    prover: DiskProver
    pool_public_key: G1Element
    farmer_public_key: G1Element
    plot_public_key: G1Element
    local_sk: PrivateKey
    file_size: int
    time_modified: float


def _get_filenames(directory: Path) -> List[Path]:
    if not directory.exists():
        log.warning(f"Directory: {directory} does not exist.")
        return []
    all_files: List[Path] = []
    for child in directory.iterdir():
        if not child.is_dir():
            # If it is a file ending in .plot, add it
            if child.suffix == ".plot":
                all_files.append(child)
        else:
            log.info(f"Not checking subdirectory {child}")
    return all_files


def get_plot_filenames(config: Dict) -> Dict[Path, List[Path]]:
    # Returns a map from directory to a list of all plots in the directory
    directory_names: List[str] = config["plot_directories"]
    all_files: Dict[Path, List[Path]] = {}
    for directory_name in directory_names:
        directory = Path(directory_name).resolve()
        all_files[directory] = _get_filenames(directory)
    return all_files


def parse_plot_info(memo: bytes) -> Tuple[G1Element, G1Element, PrivateKey]:
    # Parses the plot info bytes into keys
    assert len(memo) == (48 + 48 + 32)
    return (
        G1Element.from_bytes(memo[:48]),
        G1Element.from_bytes(memo[48:96]),
        PrivateKey.from_bytes(memo[96:]),
    )


def stream_plot_info(
    pool_public_key: G1Element,
    farmer_public_key: G1Element,
    local_master_sk: PrivateKey,
):
    # Streams the plot info keys into bytes
    data = bytes(pool_public_key) + bytes(farmer_public_key) + bytes(local_master_sk)
    assert len(data) == (48 + 48 + 32)
    return data


def add_plot_directory(str_path, root_path):
    config = load_config(root_path, "config.yaml")
    if str(Path(str_path).resolve()) not in config["harvester"]["plot_directories"]:
        config["harvester"]["plot_directories"].append(str(Path(str_path).resolve()))
    save_config(root_path, "config.yaml", config)
    return config


def load_plots(
    provers: Dict[Path, PlotInfo],
    failed_to_open_filenames: Set[Path],
    farmer_public_keys: Optional[List[G1Element]],
    pool_public_keys: Optional[List[G1Element]],
    root_path: Path,
    open_no_key_filenames=False,
) -> Tuple[bool, Dict[Path, PlotInfo], Set[Path], Set[Path]]:
    config_file = load_config(root_path, "config.yaml", "harvester")
    changed = False
    no_key_filenames: Set[Path] = []
    log.info(f'Searching directories {config_file["plot_directories"]}')

    plot_filenames: Dict[Path, List[Path]] = get_plot_filenames(config_file)
    all_filenames: List[Path] = []
    for paths in plot_filenames.values():
        all_filenames += paths
    total_size = 0

    for filename in all_filenames:
        if filename in provers:
            stat_info = filename.stat()
            if stat_info.st_mtime == provers[filename].time_modified:
                total_size += stat_info.st_size
                continue
        if filename in failed_to_open_filenames:
            continue
        if filename.exists():
            try:
                prover = DiskProver(str(filename))
                (
                    pool_public_key,
                    farmer_public_key,
                    local_master_sk,
                ) = parse_plot_info(prover.get_memo())
                # Only use plots that correct keys associated with them
                if (
                    farmer_public_keys is not None
                    and farmer_public_key not in farmer_public_keys
                ):
                    log.warning(
                        f"Plot {filename} has a farmer public key that is not in the farmer's pk list."
                    )
                    no_key_filenames.append(filename)
                    if not open_no_key_filenames:
                        continue

                if (
                    pool_public_keys is not None
                    and pool_public_key not in pool_public_keys
                ):
                    log.warning(
                        f"Plot {filename} has a pool public key that is not in the farmer's pool pk list."
                    )
                    no_key_filenames.append(filename)
                    if not open_no_key_filenames:
                        continue

                stat_info = filename.stat()
                local_sk = master_sk_to_local_sk(local_master_sk)
                plot_public_key: G1Element = ProofOfSpace.generate_plot_public_key(
                    local_sk.get_g1(), farmer_public_key
                )
                provers[filename] = PlotInfo(
                    prover,
                    pool_public_key,
                    farmer_public_key,
                    plot_public_key,
                    local_sk,
                    stat_info.st_size,
                    stat_info.st_mtime,
                )
                total_size += stat_info.st_size
                changed = True
            except Exception as e:
                tb = traceback.format_exc()
                log.error(f"Failed to open file {filename}. {e} {tb}")
                failed_to_open_filenames.add(filename)
                continue
            log.info(
                f"Found plot {filename} of size {provers[filename].prover.get_size()}"
            )

    log.info(
        f"Loaded a total of {len(provers)} plots of size {total_size / (1024 ** 4)} TB"
    )
    return (changed, provers, failed_to_open_filenames, no_key_filenames)
