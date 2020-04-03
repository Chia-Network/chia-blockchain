import argparse
from pathlib import Path

from blspy import PrivateKey, PublicKey

from chiapos import DiskProver, Verifier
from src.types.proof_of_space import ProofOfSpace
from src.types.sized_bytes import bytes32
from src.util.config import load_config
from src.util.hash import std_hash
from src.util.path import path_from_root

chia_root = path_from_root()
plot_config_filename = "plots.yaml"


def main():
    """
    Script for checking all plots in the plots.yaml file. Specify a number of challenge to test for each plot.
    """

    parser = argparse.ArgumentParser(description="Chia plot checking script.")
    parser.add_argument(
        "-n", "--num", help="Number of challenges", type=int, default=1000
    )
    args = parser.parse_args()

    print("Checking plots in plots.yaml")

    v = Verifier()
    plot_config = load_config(plot_config_filename)
    for plot_filename, plot_info in plot_config["plots"].items():
        plot_seed: bytes32 = ProofOfSpace.calculate_plot_seed(
            PublicKey.from_bytes(bytes.fromhex(plot_info["pool_pk"])),
            PrivateKey.from_bytes(bytes.fromhex(plot_info["sk"])).get_public_key(),
        )
        if not Path(plot_filename).exists():
            # Tries relative path
            full_path: Path = chia_root / plot_filename
            if not full_path.exists():
                # Tries absolute path
                full_path = Path(plot_filename)
                if not full_path.exists():
                    print(f"Plot file {full_path} not found.")
                    continue
            pr = DiskProver(str(full_path))
        else:
            pr = DiskProver(plot_filename)
        total_proofs = 0
        try:
            for i in range(args.num):
                challenge = std_hash(i.to_bytes(32, "big"))
                for index, quality_str in enumerate(
                    pr.get_qualities_for_challenge(challenge)
                ):
                    proof = pr.get_full_proof(challenge, index)
                    total_proofs += 1
                    ver_quality_str = v.validate_proof(
                        plot_seed, pr.get_size(), challenge, proof
                    )
                    assert quality_str == ver_quality_str
        except BaseException as e:
            if isinstance(e, KeyboardInterrupt):
                print("Interrupted, closing")
                return
            print(f"{type(e)}: {e} error in proving/verifying for plot {plot_filename}")
        print(
            f"{plot_filename}: Proofs {total_proofs} / {args.num}, {round(total_proofs/float(args.num), 4)}"
        )


if __name__ == "__main__":
    main()
