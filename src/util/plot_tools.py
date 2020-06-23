from typing import List, Dict, Optional, Tuple
from pathlib import Path
from blspy import PrivateKey, PublicKey
from chiapos import DiskProver
from dataclasses import dataclass
import logging

from src.types.sized_bytes import bytes32


log = logging.getLogger(__name__)


def _get_filenames(directory: Path) -> List[Path]:
    if not directory.is_dir():
        # If it is a file ending in .plot, add it
        if directory.suffix == ".plot":
            return [directory]
        else:
            # Ignore other files
            return []
    # If it is a directory, recurse
    all_files: List[Path] = []
    for child in directory.iterdir():
        all_files += _get_filenames(child)
    return all_files


def get_plot_filenames(config: Dict) -> Dict[Path, List[Path]]:
    # Returns a map from directory to a list of all plots recursively in the directory
    directory_names: List[str] = config["harvester"]["plot_directories"]
    all_files: Dict[Path, List[Path]] = {}
    for directory_name in directory_names:
        directory = Path(directory_name).resolve()
        all_files[directory] = _get_filenames(directory)
    return all_files


def parse_plot_info(memo: bytes) -> Tuple[bytes32, bytes32, PublicKey, PrivateKey]:
    # Parses the plot info bytes into keys
    assert len(memo) == (32 + 32 + 48 + 32)
    return (
        memo[:32],
        memo[32:64],
        PublicKey.from_bytes(memo[64 : 64 + 48]),
        PrivateKey.from_bytes(memo[64 + 48 :]),
    )


def stream_plot_info(
    farmer_address: bytes32,
    pool_address: bytes32,
    farmer_public_key: PublicKey,
    harvester_sk: PrivateKey,
):
    # Streams the plot info keys into bytes
    data = (
        farmer_address + pool_address + bytes(farmer_public_key) + bytes(harvester_sk)
    )
    assert len(data) == (32 + 32 + 48 + 32)
    return data


@dataclass
class PlotInfo:
    prover: DiskProver
    farmer_address: bytes32
    pool_address: bytes32
    farmer_public_key: PublicKey
    harvester_sk: PrivateKey


def load_plots(
    config_file: Dict,
    farmer_pubkeys: Optional[List[PublicKey]],
    root_path: Path,
    open_no_key_filenames=False,
) -> Tuple[Dict[Path, PlotInfo], List[Path], List[Path]]:
    provers: Dict[Path, PlotInfo] = {}
    failed_to_open_filenames: List[Path] = []
    no_key_filenames: List[Path] = []
    plot_filenames: Dict[Path, List[Path]] = get_plot_filenames(config_file)
    all_filenames: List[Path] = []
    for paths in plot_filenames.values():
        all_filenames += paths
    log.info(f"Searching paths: {[str(x) for x in plot_filenames.keys()]}")

    for filename in all_filenames:
        if filename in provers:
            continue
        if filename.exists():
            try:
                prover = DiskProver(str(filename))
                (
                    farmer_address,
                    pool_address,
                    farmer_public_key,
                    harvester_sk,
                ) = parse_plot_info(prover.get_memo())
                # Only use plots that correct pools associated with them
                if (
                    farmer_pubkeys is not None
                    and farmer_public_key not in farmer_pubkeys
                ):
                    log.warning(
                        f"Plot {filename} has a farmer public key that is not in the farmer's pk list."
                    )
                    no_key_filenames.append(filename)
                    if not open_no_key_filenames:
                        continue

                provers[filename] = PlotInfo(
                    prover,
                    farmer_address,
                    pool_address,
                    farmer_public_key,
                    harvester_sk,
                )
            except Exception as e:
                log.error(f"Failed to open file {filename}. {e}")
                failed_to_open_filenames.append(filename)
                break
            log.info(
                f"Found plot {filename} of size {provers[filename].prover.get_size()}"
            )
    return (provers, failed_to_open_filenames, no_key_filenames)
