import argparse
from pathlib import Path
from datetime import datetime
from secrets import token_bytes
import sys

from blspy import PrivateKey, PublicKey

from chiapos import DiskPlotter
from src.types.proof_of_space import ProofOfSpace
from src.types.sized_bytes import bytes32
from src.util.config import config_path_for_filename, load_config, save_config
from src.util.default_root import DEFAULT_ROOT_PATH
from src.util.path import mkdir
from src.util.keychain import Keychain
from src.util.plot_tools import get_plot_filenames, stream_plot_info


def log(to_log):
    print(to_log)
    sys.stdout.flush()


def get_default_public_key() -> PublicKey:
    keychain: Keychain = Keychain()
    epk = keychain.get_first_public_key()
    if epk is None:
        raise RuntimeError(
            "No keys, please run 'chia keys generate' or provide a public key with -f"
        )
    return PublicKey.from_bytes(bytes(epk.public_child(0).get_public_key()))


def main():
    """
    Script for creating plots and adding them to the plot config file.
    """
    root_path = DEFAULT_ROOT_PATH
    config_filename = config_path_for_filename(root_path, "config.yaml")

    parser = argparse.ArgumentParser(description="Chia plotting script.")
    parser.add_argument("-k", "--size", help="Plot size", type=int, default=26)
    parser.add_argument(
        "-n", "--num_plots", help="Number of plots", type=int, default=1
    )
    parser.add_argument(
        "-i", "--index", help="First plot index", type=int, default=None
    )
    parser.add_argument(
        "-b", "--buffer", help="Megabytes for sort/plot buffer", type=int, default=2048
    )
    parser.add_argument(
        "-f",
        "--farmer_public_key",
        help="Hex farmer public key",
        type=str,
        default=None,
    )
    parser.add_argument(
        "-p", "--pool_public_key", help="Hex public key of pool", type=str, default=None
    )
    parser.add_argument(
        "-s", "--sk_seed", help="Secret key seed in hex", type=str, default=None
    )
    parser.add_argument(
        "-t",
        "--tmp_dir",
        help="Temporary directory for plotting files",
        type=Path,
        default=Path("."),
    )
    parser.add_argument(
        "-2",
        "--tmp2_dir",
        help="Second temporary directory for plotting files",
        type=Path,
        default=None,
    )
    parser.add_argument(
        "-d",
        "--final_dir",
        help="Final directory for plots (relative or absolute)",
        type=Path,
        default=Path("."),
    )

    args = parser.parse_args()

    if args.sk_seed is None and args.index is not None:
        log(
            "You have specified the -i (index) argument without the -s (sk_seed) argument."
            " The program has changes, so that the sk_seed is now generated randomly, so -i is no longer necessary."
            " Please run the program without -i."
        )
        quit()
    if args.tmp2_dir is None:
        args.tmp2_dir = args.final_dir

    if args.index is None:
        args.index = 0

    # The seed is what will be used to generate a private key for each plot
    if args.sk_seed is not None:
        sk_seed: bytes = bytes.fromhex(args.sk_seed)
        log(f"Using the provided sk_seed {sk_seed.hex()}.")
    else:
        sk_seed = token_bytes(32)
        log(
            f"Using sk_seed {sk_seed.hex()}. Note that sk seed is now generated randomly. "
            f"If you want to use a specific seed, use the -s argument."
        )

    farmer_public_key: PublicKey
    if args.farmer_public_key is not None:
        farmer_public_key = PublicKey.from_bytes(bytes.fromhex(args.farmer_public_key))
    else:
        farmer_public_key = get_default_public_key()

    pool_public_key: PublicKey
    if args.pool_public_key is not None:
        pool_public_key = bytes.fromhex(args.pool_public_key)
    else:
        pool_public_key = get_default_public_key()

    log(
        f"Creating {args.num_plots} plots, from index {args.index} to "
        f"{args.index + args.num_plots - 1}, of size {args.size}, sk_seed "
        f"{sk_seed.hex()} pool public key "
        f"{bytes(pool_public_key).hex()} farmer public key {bytes(farmer_public_key).hex()}"
    )

    mkdir(args.tmp_dir)
    mkdir(args.tmp2_dir)
    mkdir(args.final_dir)
    finished_filenames = []
    for i in range(args.index, args.index + args.num_plots):
        # Generate a sk based on the seed, plot size (k), and index
        sk: PrivateKey = PrivateKey.from_seed(
            sk_seed + args.size.to_bytes(1, "big") + i.to_bytes(4, "big")
        )

        # The plot public key is the combination of the harvester and farmer keys
        plot_public_key = ProofOfSpace.generate_plot_public_key(
            sk.get_public_key(), farmer_public_key
        )

        # The plot seed is based on the harvester, farmer, and pool keys
        plot_seed: bytes32 = ProofOfSpace.calculate_plot_seed(
            pool_public_key, plot_public_key
        )
        dt_string = datetime.now().strftime("%Y-%m-%d-%H-%M")

        filename: str = f"plot-k{args.size}-{dt_string}-{plot_seed}.plot"
        full_path: Path = args.final_dir / filename

        config = load_config(root_path, config_filename)
        plot_filenames = get_plot_filenames(config)

        if args.final_dir.resolve() not in plot_filenames:
            # Adds the directory to the plot directories if it is not present
            config["harvester"]["plot_directories"].append(
                str(args.final_dir.resolve())
            )
            save_config(root_path, config_filename, config)

        if not full_path.exists():
            # Creates the plot. This will take a long time for larger plots.
            plotter: DiskPlotter = DiskPlotter()
            plotter.create_plot_disk(
                str(args.tmp_dir),
                str(args.tmp2_dir),
                str(args.final_dir),
                filename,
                args.size,
                stream_plot_info(pool_public_key, farmer_public_key, sk),
                plot_seed,
                args.buffer,
            )
            finished_filenames.append(filename)
        else:
            log(f"Plot {filename} already exists")

    log("Summary:")
    try:
        args.tmp_dir.rmdir()
    except Exception:
        log(
            f"warning: did not remove primary temporary folder {args.tmp_dir}, it may not be empty."
        )
    try:
        args.tmp2_dir.rmdir()
    except Exception:
        log(
            f"warning: did not remove secondary temporary folder {args.tmp2_dir}, it may not be empty."
        )
    log(f"Created a total of {len(finished_filenames)} new plots")
    for filename in finished_filenames:
        log(filename)


if __name__ == "__main__":
    main()
