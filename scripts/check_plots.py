import argparse
import os
from hashlib import sha256

from blspy import PrivateKey, PublicKey
from yaml import safe_load

from chiapos import DiskProver, Verifier
from definitions import ROOT_DIR
from src.types.proof_of_space import ProofOfSpace
from src.types.sized_bytes import bytes32

plot_root = os.path.join(ROOT_DIR, "plots")
plot_config_filename = os.path.join(ROOT_DIR, "config", "plots.yaml")


def main():
    """
    Script for checking all plots in the plots.yaml file. Specify a number of challenge to test for each plot.
    """

    parser = argparse.ArgumentParser(description="Chia plot checking script.")
    parser.add_argument(
        "-n", "--num", help="Number of challenges", type=int, default=1000
    )
    args = parser.parse_args()

    v = Verifier()
    if os.path.isfile(plot_config_filename):
        plot_config = safe_load(open(plot_config_filename, "r"))
        for plot_filename, plot_info in plot_config["plots"].items():
            plot_seed: bytes32 = ProofOfSpace.calculate_plot_seed(
                PublicKey.from_bytes(bytes.fromhex(plot_info["pool_pk"])),
                PrivateKey.from_bytes(bytes.fromhex(plot_info["sk"])).get_public_key(),
            )
            if not os.path.isfile(plot_filename):
                # Tries relative path
                full_path: str = os.path.join(plot_root, plot_filename)
                if not os.path.isfile(full_path):
                    # Tries absolute path
                    full_path: str = plot_filename
                    if not os.path.isfile(full_path):
                        print(f"Plot file {full_path} not found.")
                        continue
                pr = DiskProver(full_path)
            else:
                pr = DiskProver(plot_filename)

            total_proofs = 0
            try:
                for i in range(args.num):
                    challenge = sha256(i.to_bytes(32, "big")).digest()
                    for index, quality in enumerate(
                        pr.get_qualities_for_challenge(challenge)
                    ):
                        proof = pr.get_full_proof(challenge, index)
                        total_proofs += 1
                        ver_quality = v.validate_proof(
                            plot_seed, pr.get_size(), challenge, proof
                        )
                        assert quality == ver_quality
            except BaseException as e:
                print(
                    f"{type(e)}: {e} error in proving/verifying for plot {plot_filename}"
                )
            print(
                f"{plot_filename}: Proofs {total_proofs} / {args.num}, {round(total_proofs/float(args.num), 4)}"
            )
    else:
        print(f"Not plot file found at {plot_config_filename}")


if __name__ == "__main__":
    main()
