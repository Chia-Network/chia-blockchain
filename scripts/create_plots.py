import argparse
import os
from copy import deepcopy

from blspy import PrivateKey, PublicKey
from yaml import safe_dump, safe_load

from chiapos import DiskPlotter
from definitions import ROOT_DIR
from src.types.proof_of_space import ProofOfSpace
from src.types.sized_bytes import bytes32

plot_root = os.path.join(ROOT_DIR, "plots")
plot_config_filename = os.path.join(ROOT_DIR, "config", "plots.yaml")
key_config_filename = os.path.join(ROOT_DIR, "config", "keys.yaml")


def main():
    """
    Script for creating plots and adding them to the plot config file.
    """

    parser = argparse.ArgumentParser(description="Chia plotting script.")
    parser.add_argument("-k", "--size", help="Plot size", type=int, default=20)
    parser.add_argument(
        "-n", "--num_plots", help="Number of plots", type=int, default=10
    )
    parser.add_argument(
        "-p", "--pool_pub_key", help="Hex public key of pool", type=str, default=""
    )

    # We need the keys file, to access pool keys (if the exist), and the sk_seed.
    args = parser.parse_args()
    if not os.path.isfile(key_config_filename):
        raise RuntimeError("Keys not generated. Run ./scripts/regenerate_keys.py.")

    # The seed is what will be used to generate a private key for each plot
    key_config = safe_load(open(key_config_filename, "r"))
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
        f"Creating {args.num_plots} plots of size {args.size}, sk_seed {sk_seed.hex()} ppk {pool_pk}"
    )

    for i in range(args.num_plots):
        # Generate a sk based on the seed, plot size (k), and index
        sk: PrivateKey = PrivateKey.from_seed(
            sk_seed + args.size.to_bytes(1, "big") + i.to_bytes(4, "big")
        )

        # The plot seed is based on the pool and plot pks
        plot_seed: bytes32 = ProofOfSpace.calculate_plot_seed(
            pool_pk, sk.get_public_key()
        )
        filename: str = f"plot-{i}-{args.size}-{plot_seed}.dat"
        full_path: str = os.path.join(plot_root, filename)
        if os.path.isfile(full_path):
            print(f"Plot {filename} already exists")
        else:
            # Creates the plot. This will take a long time for larger plots.
            plotter: DiskPlotter = DiskPlotter()
            plotter.create_plot_disk(full_path, args.size, bytes([]), plot_seed)

        # Updates the config if necessary.
        if os.path.isfile(plot_config_filename):
            plot_config = safe_load(open(plot_config_filename, "r"))
        else:
            plot_config = {"plots": {}}
        plot_config_plots_new = deepcopy(plot_config["plots"])
        if filename not in plot_config_plots_new:
            plot_config_plots_new[filename] = {
                "sk": bytes(sk).hex(),
                "pool_pk": bytes(pool_pk).hex(),
            }
        plot_config["plots"].update(plot_config_plots_new)

        # Dumps the new config to disk.
        with open(plot_config_filename, "w") as f:
            safe_dump(plot_config, f)


if __name__ == "__main__":
    main()
