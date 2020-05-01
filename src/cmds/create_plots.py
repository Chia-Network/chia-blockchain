import argparse
from copy import deepcopy
from pathlib import Path

from blspy import PrivateKey, PublicKey

from chiapos import DiskPlotter
from src.types.proof_of_space import ProofOfSpace
from src.types.sized_bytes import bytes32
from src.util.config import config_path_for_filename, load_config, save_config
from src.util.default_root import DEFAULT_ROOT_PATH
from src.util.path import make_path_relative, mkdir, path_from_root


def main():
    """
    Script for creating plots and adding them to the plot config file.
    """
    root_path = DEFAULT_ROOT_PATH
    plot_config_filename = config_path_for_filename(root_path, "plots.yaml")
    key_config_filename = config_path_for_filename(root_path, "keys.yaml")

    parser = argparse.ArgumentParser(description="Chia plotting script.")
    parser.add_argument("-k", "--size", help="Plot size", type=int, default=26)
    parser.add_argument(
        "-n", "--num_plots", help="Number of plots", type=int, default=1
    )
    parser.add_argument("-i", "--index", help="First plot index", type=int, default=0)
    parser.add_argument(
        "-p", "--pool_pub_key", help="Hex public key of pool", type=str, default=""
    )
    parser.add_argument(
        "-t",
        "--tmp_dir",
        help="Temporary directory for plotting files (relative to final directory)",
        type=Path,
        default=Path("./plots.tmp"),
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

    # We need the keys file, to access pool keys (if the exist), and the sk_seed.
    args = parser.parse_args()
    if not key_config_filename.exists():
        raise RuntimeError("Keys not generated. Run `chia generate keys`")

    # The seed is what will be used to generate a private key for each plot
    key_config = load_config(root_path, key_config_filename)
    sk_seed: bytes = bytes.fromhex(key_config["sk_seed"])

    pool_pk: PublicKey
    if len(args.pool_pub_key) > 0:
        # Use the provided pool public key, useful for using an external pool
        pool_pk = PublicKey.from_bytes(bytes.fromhex(args.pool_pub_key))
    else:
        # Use the pool public key from the config, useful for solo farming
        pool_sk = PrivateKey.from_bytes(bytes.fromhex(key_config["pool_sks"][0]))
        pool_pk = pool_sk.get_public_key()

    print(
        f"Creating {args.num_plots} plots, from index {args.index} to "
        f"{args.index + args.num_plots - 1}, of size {args.size}, sk_seed {sk_seed.hex()} ppk {pool_pk}"
    )

    tmp_dir = args.tmp_dir
    mkdir(tmp_dir)
    mkdir(args.final_dir)
    for i in range(args.index, args.index + args.num_plots):
        # Generate a sk based on the seed, plot size (k), and index
        sk: PrivateKey = PrivateKey.from_seed(
            sk_seed + args.size.to_bytes(1, "big") + i.to_bytes(4, "big")
        )

        # The plot seed is based on the pool and plot pks
        plot_seed: bytes32 = ProofOfSpace.calculate_plot_seed(
            pool_pk, sk.get_public_key()
        )
        filename: str = f"plot-{i}-{args.size}-{plot_seed}.dat"
        full_path: Path = args.final_dir / filename

        plot_config = load_config(root_path, plot_config_filename)
        plot_config_plots_new = deepcopy(plot_config.get("plots", []))
        filenames = [Path(k).name for k in plot_config_plots_new.keys()]
        relative_path = make_path_relative(full_path, root_path)
        already_in_config = (
            relative_path in plot_config_plots_new
            or full_path in plot_config_plots_new
            or full_path.name in filenames
        )
        if already_in_config:
            print(f"Plot {filename} already exists (in config)")
            continue

        if not full_path.exists():
            # Creates the plot. This will take a long time for larger plots.
            plotter: DiskPlotter = DiskPlotter()
            plotter.create_plot_disk(
                str(tmp_dir),
                str(args.final_dir),
                filename,
                args.size,
                bytes([]),
                plot_seed,
            )
        else:
            print(f"Plot {filename} already exists")

        # Updates the config if necessary.
        plot_config_plots_new[str(full_path)] = {
            "sk": bytes(sk).hex(),
            "pool_pk": bytes(pool_pk).hex(),
        }
        plot_config["plots"].update(plot_config_plots_new)

        # Dumps the new config to disk.
        save_config(root_path, plot_config_filename, plot_config)
    try:
        tmp_dir.rmdir()
    except Exception:
        print(f"warning: did not remove temporary folder {tmp_dir}, it may not be empty.")


if __name__ == "__main__":
    main()
