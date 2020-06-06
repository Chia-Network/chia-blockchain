import argparse
from copy import deepcopy
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
from src.util.keychain import Keychain
from src.util.path import mkdir, path_from_root


def log(to_log):
    print(to_log)
    sys.stdout.flush()


def main():
    """
    Script for creating plots and adding them to the plot config file.
    """
    root_path = DEFAULT_ROOT_PATH
    plot_config_filename = config_path_for_filename(root_path, "plots.yaml")

    parser = argparse.ArgumentParser(description="Chia plotting script.")
    parser.add_argument("-k", "--size", help="Plot size", type=int, default=26)
    parser.add_argument(
        "-n", "--num_plots", help="Number of plots", type=int, default=1
    )
    parser.add_argument(
        "-i", "--index", help="First plot index", type=int, default=None
    )
    parser.add_argument(
        "-p", "--pool_pub_key", help="Hex public key of pool", type=str, default=""
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
        default=Path("."),
    )
    new_plots_root = path_from_root(
        root_path,
        load_config(root_path, "config.yaml")
        .get("harvester", {})
        .get("new_plot_root", "plots"),
    )
    parser.add_argument(
        "-d",
        "--final_dir",
        help="Final directory for plots (relative or absolute)",
        type=Path,
        default=new_plots_root,
    )

    args = parser.parse_args()

    if args.sk_seed is None and args.index is not None:
        log(
            f"You have specified the -i (index) argument without the -s (sk_seed) argument."
            f" The program has changes, so that the sk_seed is now generated randomly, so -i is no longer necessary."
            f" Please run the program without -i."
        )
        quit()

    if args.index is None:
        args.index = 0

    # The seed is what will be used to generate a private key for each plot
    if args.sk_seed is not None:
        sk_seed: bytes = bytes.fromhex(args.sk_seed)
        log(f"Using the provided sk_seed {sk_seed.hex()}.")
    else:
        sk_seed = token_bytes(32)
        log(
            f"Using sk_seed {sk_seed.hex()}. Note that sk seed is now generated randomly, as opposed "
            f"to from keys.yaml. If you want to use a specific seed, use the -s argument."
        )

    pool_pk: PublicKey
    if len(args.pool_pub_key) > 0:
        # Use the provided pool public key, useful for using an external pool
        pool_pk = PublicKey.from_bytes(bytes.fromhex(args.pool_pub_key))
    else:
        # Use the pool public key from the config, useful for solo farming
        keychain = Keychain()
        all_public_keys = keychain.get_all_public_keys()
        if len(all_public_keys) == 0:
            raise RuntimeError(
                "There are no private keys in the keychain, so we cannot create a plot. "
                "Please generate keys using 'chia keys generate' or pass in a pool pk with -p"
            )
        pool_pk = all_public_keys[0].get_public_key()

    log(
        f"Creating {args.num_plots} plots, from index {args.index} to "
        f"{args.index + args.num_plots - 1}, of size {args.size}, sk_seed {sk_seed.hex()} ppk {pool_pk}"
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

        # The plot seed is based on the pool and plot pks
        plot_seed: bytes32 = ProofOfSpace.calculate_plot_seed(
            pool_pk, sk.get_public_key()
        )
        dt_string = datetime.now().strftime("%Y-%m-%d-%H-%M")

        filename: str = f"plot-k{args.size}-{dt_string}-{plot_seed}.dat"
        full_path: Path = args.final_dir / filename

        plot_config = load_config(root_path, plot_config_filename)
        plot_config_plots_new = deepcopy(plot_config.get("plots", []))
        filenames = [Path(k).name for k in plot_config_plots_new.keys()]
        already_in_config = any(plot_seed.hex() in fname for fname in filenames)
        if already_in_config:
            log(f"Plot {filename} already exists (in config)")
            continue

        if not full_path.exists():
            # Creates the plot. This will take a long time for larger plots.
            plotter: DiskPlotter = DiskPlotter()
            plotter.create_plot_disk(
                str(args.tmp_dir),
                str(args.tmp2_dir),
                str(args.final_dir),
                filename,
                args.size,
                bytes([]),
                plot_seed,
            )
            finished_filenames.append(filename)
        else:
            log(f"Plot {filename} already exists")

        # Updates the config if necessary.
        plot_config = load_config(root_path, plot_config_filename)
        plot_config_plots_new = deepcopy(plot_config.get("plots", []))
        plot_config_plots_new[str(full_path)] = {
            "sk": bytes(sk).hex(),
            "pool_pk": bytes(pool_pk).hex(),
        }
        plot_config["plots"].update(plot_config_plots_new)

        # Dumps the new config to disk.
        save_config(root_path, plot_config_filename, plot_config)
    log("")
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
