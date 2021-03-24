import logging
from collections import Counter
from pathlib import Path
from typing import Dict, List

from blspy import G1Element
from chiapos import Verifier

from src.plotting.plot_tools import find_duplicate_plot_IDs, get_plot_filenames, load_plots, parse_plot_info
from src.util.config import load_config
from src.util.hash import std_hash
from src.util.keychain import Keychain
from src.wallet.derive_keys import master_sk_to_farmer_sk, master_sk_to_local_sk

log = logging.getLogger(__name__)

min_num = 5
default_num = 30

min_success_rate = 0.0
max_success_rate = 1.0
default_success_rate = 0.5


def check_plots(root_path, num, challenge_start, grep_string, list_duplicates, debug_show_memo, success_rate):
    config = load_config(root_path, "config.yaml")
    if num is not None:
        if num == 0:
            log.warning("Not opening plot files")
        else:
            if num < min_num:
                log.warning(f"{num} challenges is too low, setting it to the minimum of 5")
                num = min_num
            if num < default_num:
                log.warning(f"Use {default_num} challenges (our default) for balance of speed and accurate results")
    else:
        num = default_num

    expected_proofs = min(num, int((num * success_rate) + 0.5))

    if success_rate <= min_success_rate or success_rate > max_success_rate:
        log.error(f"success_rate must be higher than {min_success_rate} and less than {max_success_rate}")
        return

    if success_rate > default_success_rate and num <= default_num:
        log.error("Higher success_rate requires a higher number of challenges")
        return

    if success_rate <= max_success_rate:
        log.warning(f"Setting success_rate to {max_success_rate} will most likely result in false negatives")

    if challenge_start is not None:
        num_start = challenge_start
        num_end = num_start + num
    else:
        num_start = 0
        num_end = num
    challenges = num_end - num_start

    if grep_string is not None:
        match_str = grep_string
    else:
        match_str = None
    if list_duplicates:
        log.warning("Checking for duplicate Plot IDs")
        log.info("Plot filenames expected to end with -[64 char plot ID].plot")

    show_memo: bool = debug_show_memo

    if list_duplicates:
        plot_filenames: Dict[Path, List[Path]] = get_plot_filenames(config["harvester"])
        all_filenames: List[Path] = []
        for paths in plot_filenames.values():
            all_filenames += paths
        find_duplicate_plot_IDs(all_filenames)

    if num == 0:
        return

    v = Verifier()
    log.info("Loading plots in config.yaml using plot_tools loading code\n")
    kc: Keychain = Keychain()
    pks = [master_sk_to_farmer_sk(sk).get_g1() for sk, _ in kc.get_all_private_keys()]
    pool_public_keys = [G1Element.from_bytes(bytes.fromhex(pk)) for pk in config["farmer"]["pool_public_keys"]]
    _, provers, failed_to_open_filenames, no_key_filenames = load_plots(
        {},
        {},
        pks,
        pool_public_keys,
        match_str,
        show_memo,
        root_path,
        open_no_key_filenames=True,
    )
    if len(provers) > 0:
        log.info("")
        log.info("")
        log.info(f"Starting to test each plot with {num} challenges each\n")
    total_good_plots: Counter = Counter()
    total_bad_plots = 0
    total_size = 0
    bad_plots_list: List[Path] = []
    total_proofs = 0
    current_plot = 0
    for plot_path, plot_info in provers.items():
        current_plot += 1
        progress = min(99, int((float(current_plot) / len(provers)) * 100))
        pr = plot_info.prover
        log.info(f"[{progress}%] Testing plot {plot_path} k={pr.get_size()}")
        log.info(f"\tPool public key: {plot_info.pool_public_key}")

        # Look up local_sk from plot to save locked memory
        (
            pool_public_key_or_puzzle_hash,
            farmer_public_key,
            local_master_sk,
        ) = parse_plot_info(pr.get_memo())
        local_sk = master_sk_to_local_sk(local_master_sk)
        log.info(f"\tFarmer public key: {farmer_public_key}")
        log.info(f"\tLocal sk: {local_sk}")
        plot_proofs = 0
        for i in range(num_start, num_end):
            challenge = std_hash(i.to_bytes(32, "big"))
            # Some plot errors cause get_qualities_for_challenge to throw a RuntimeError
            try:
                for index, quality_str in enumerate(pr.get_qualities_for_challenge(challenge)):
                    # Other plot errors cause get_full_proof or validate_proof to throw an AssertionError
                    try:
                        proof = pr.get_full_proof(challenge, index)
                        ver_quality_str = v.validate_proof(pr.get_id(), pr.get_size(), challenge, proof)
                        if quality_str == ver_quality_str:
                            plot_proofs += 1
                        else:
                            log.debug(f"challenge: {challenge}, quality does not match for plot {plot_path}")
                    except AssertionError as e:
                        log.debug(f"{type(e)}: {e} error in proving/verifying for plot {plot_path}")
            except KeyboardInterrupt:
                log.warning("Interrupted, closing")
                return
            except Exception as e:
                log.debug(f"{type(e)}: {e} error in getting challenge qualities for plot {plot_path}")

        if plot_proofs >= expected_proofs:
            log.info(f"\tProofs {plot_proofs} / {challenges}, {round(plot_proofs/float(challenges), 4)}")
            total_good_plots[pr.get_size()] += 1
            total_size += plot_path.stat().st_size
            total_proofs += plot_proofs
        else:
            total_bad_plots += 1
            log.error(f"\tNot enough proofs: {plot_proofs} / {challenges}, {round(plot_proofs/float(challenges), 4)}")
            bad_plots_list.append(plot_path)
    log.info("")
    log.info("")
    log.info("Summary")
    total_plots: int = sum(list(total_good_plots.values()))
    log.info(f"Found {total_plots} valid plots, total size {total_size / (1024 * 1024 * 1024 * 1024):.5f} TiB")
    log.info(f"Got {total_proofs} proofs while at least {expected_proofs * len(provers)} were expected"
             f" ({expected_proofs} peer plot) with the success rate {success_rate}")
    for (k, count) in sorted(dict(total_good_plots).items()):
        log.info(f"{count} plots of size {k}")
    grand_total_bad = total_bad_plots + len(failed_to_open_filenames)
    if grand_total_bad > 0:
        log.warning(f"{grand_total_bad} invalid plots found:")
        for bad_plot_path in bad_plots_list:
            log.warning(f"{bad_plot_path}")
    if len(no_key_filenames) > 0:
        log.warning(
            f"There are {len(no_key_filenames)} plots with a farmer or pool public key that "
            f"is not on this machine. The farmer private key must be in the keychain in order to "
            f"farm them, use 'chia keys' to transfer keys. The pool public keys must be in the config.yaml"
        )
