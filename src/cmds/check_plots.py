import argparse
import logging

from chiapos import Verifier
from src.util.config import load_config
from src.util.logging import initialize_logging
from src.util.default_root import DEFAULT_ROOT_PATH
from src.util.hash import std_hash
from src.harvester import load_plots


plot_config_filename = "plots.yaml"
config_filename = "config.yaml"


def main():
    """
    Script for checking all plots in the plots.yaml file. Specify a number of challenge to test for each plot.
    """

    parser = argparse.ArgumentParser(description="Chia plot checking script.")
    parser.add_argument(
        "-n", "--num", help="Number of challenges", type=int, default=100
    )
    args = parser.parse_args()

    root_path = DEFAULT_ROOT_PATH
    plot_config = load_config(root_path, plot_config_filename)
    config = load_config(root_path, config_filename)

    initialize_logging("%(name)-22s", {"log_stdout": True}, root_path)
    log = logging.getLogger(__name__)

    v = Verifier()
    log.info("Loading plots in plots.yaml using harvester loading code\n")
    provers, _, _ = load_plots(config["harvester"], plot_config, None, root_path)
    log.info(f"\n\nStarting to test each plot with {args.num} challenges each\n")
    for plot_path, pr in provers.items():
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
                        pr.get_id(), pr.get_size(), challenge, proof
                    )
                    assert quality_str == ver_quality_str
        except BaseException as e:
            if isinstance(e, KeyboardInterrupt):
                log.warning("Interrupted, closing")
                return
            log.error(f"{type(e)}: {e} error in proving/verifying for plot {plot_path}")
        if total_proofs > 0:
            log.info(
                f"{plot_path}: Proofs {total_proofs} / {args.num}, {round(total_proofs/float(args.num), 4)}"
            )
        else:
            log.error(
                f"{plot_path}: Proofs {total_proofs} / {args.num}, {round(total_proofs/float(args.num), 4)}"
            )


if __name__ == "__main__":
    main()
