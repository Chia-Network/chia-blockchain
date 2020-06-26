import argparse
import logging

from blspy import PublicKey
from chiapos import Verifier
from collections import Counter
from src.util.config import load_config
from src.util.logging import initialize_logging
from src.util.default_root import DEFAULT_ROOT_PATH
from src.util.hash import std_hash
from src.util.plot_tools import load_plots
from src.util.keychain import Keychain


config_filename = "config.yaml"

log = logging.getLogger(__name__)


def main():
    """
    Script for checking all plots in the config.yaml. Specify a number of challenge to test for each plot.
    """

    parser = argparse.ArgumentParser(description="Chia plot checking script.")
    parser.add_argument(
        "-n", "--num", help="Number of challenges", type=int, default=100
    )
    args = parser.parse_args()

    root_path = DEFAULT_ROOT_PATH
    config = load_config(root_path, config_filename)

    initialize_logging("", {"log_stdout": True}, root_path)

    v = Verifier()
    log.info("Loading plots in config.yaml using plot_tools loading code\n")
    kc: Keychain = Keychain()
    pks = [epk.public_child(0).get_public_key() for epk in kc.get_all_public_keys()]
    pool_public_keys = [
        PublicKey.from_bytes(bytes.fromhex(pk))
        for pk in config["farmer"]["pool_public_keys"]
    ]
    _, provers, failed_to_open_filenames, no_key_filenames = load_plots(
        config, {}, pks, pool_public_keys, root_path, open_no_key_filenames=True
    )
    if len(provers) > 0:
        log.info("")
        log.info("")
        log.info(f"Starting to test each plot with {args.num} challenges each\n")
    total_good_plots: Counter = Counter()
    total_bad_plots = 0
    total_size = 0

    for plot_path, plot_info in provers.items():
        pr = plot_info.prover
        log.info(f"Testing plot {plot_path} k={pr.get_size()}")
        log.info(f"\tPool public key: {plot_info.pool_public_key}")
        log.info(f"\tFarmer public key: {plot_info.farmer_public_key}")
        log.info(f"\tHarvester sk: {plot_info.harvester_sk}")
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
                f"\tProofs {total_proofs} / {args.num}, {round(total_proofs/float(args.num), 4)}"
            )
            total_good_plots[pr.get_size()] += 1
            total_size += plot_path.stat().st_size
        else:
            total_bad_plots += 1
            log.error(
                f"\tProofs {total_proofs} / {args.num}, {round(total_proofs/float(args.num), 4)}"
            )
    log.info("")
    log.info("")
    log.info("Summary")
    total_plots: int = sum(list(total_good_plots.values()))
    log.info(
        f"Found {total_plots} valid plots, total size {total_size / (1024 * 1024 * 1024 * 1024)} TB"
    )
    for (k, count) in sorted(dict(total_good_plots).items()):
        log.info(f"{count} plots of size {k}")
    grand_total_bad = total_bad_plots + len(failed_to_open_filenames)
    if grand_total_bad > 0:
        log.warning(f"{grand_total_bad} invalid plots")
    if len(no_key_filenames) > 0:
        log.warning(
            f"There are {len(no_key_filenames)} plots with a farmer or pool public key that "
            f"is not on this machine. The farmer private key must be in the keychain in order to "
            f"farm them, use 'chia keys' to transfer keys. The pool public keys must be in the config.yaml"
        )


if __name__ == "__main__":
    main()
