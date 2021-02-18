from typing import List, Dict
from pathlib import Path
import logging
from chiapos import Verifier
from collections import Counter
from blspy import G1Element
from src.util.keychain import Keychain
from src.util.config import load_config
from src.plotting.plot_tools import load_plots, get_plot_filenames, find_duplicate_plot_IDs
from src.util.hash import std_hash
from src.wallet.derive_keys import master_sk_to_farmer_sk

log = logging.getLogger(__name__)


def check_plots(args, root_path):
    config = load_config(root_path, "config.yaml")
    if args.num is not None:
        num = args.num
        if num == 0:
            log.warning("Not opening plot files")
        else:
            if num < 5:
                num = 5
                log.warning(f"{num} challenges is too low, setting it to the minimum of 5")
            if num < 30:
                log.warning("Use 30 challenges (our default) for balance of speed and accurate results")
    else:
        num = 30

    if args.challenge_start is not None:
        num_start = args.challenge_start
        num_end = num_start + num
    else:
        num_start = 0
        num_end = num
    challenges = num_end - num_start

    if args.grep_string is not None:
        match_str = args.grep_string
    else:
        match_str = None
    if args.list_duplicates:
        log.warning("Checking for duplicate Plot IDs")
        log.info("Plot filenames expected to end with -[64 char plot ID].plot")

    show_memo: bool = args.debug_show_memo

    if args.list_duplicates:
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

    for plot_path, plot_info in provers.items():
        pr = plot_info.prover
        log.info(f"Testing plot {plot_path} k={pr.get_size()}")
        log.info(f"\tPool public key: {plot_info.pool_public_key}")
        log.info(f"\tFarmer public key: {plot_info.farmer_public_key}")
        log.info(f"\tLocal sk: {plot_info.local_sk}")
        total_proofs = 0
        try:
            for i in range(num_start, num_end):
                challenge = std_hash(i.to_bytes(32, "big"))
                for index, quality_str in enumerate(pr.get_qualities_for_challenge(challenge)):
                    proof = pr.get_full_proof(challenge, index)
                    total_proofs += 1
                    ver_quality_str = v.validate_proof(pr.get_id(), pr.get_size(), challenge, proof)
                    assert quality_str == ver_quality_str
        except BaseException as e:
            if isinstance(e, KeyboardInterrupt):
                log.warning("Interrupted, closing")
                return
            log.error(f"{type(e)}: {e} error in proving/verifying for plot {plot_path}")
        if total_proofs > 0:
            log.info(f"\tProofs {total_proofs} / {challenges}, {round(total_proofs/float(challenges), 4)}")
            total_good_plots[pr.get_size()] += 1
            total_size += plot_path.stat().st_size
        else:
            total_bad_plots += 1
            log.error(f"\tProofs {total_proofs} / {challenges}, {round(total_proofs/float(challenges), 4)}")
    log.info("")
    log.info("")
    log.info("Summary")
    total_plots: int = sum(list(total_good_plots.values()))
    log.info(f"Found {total_plots} valid plots, total size {total_size / (1024 * 1024 * 1024 * 1024):.5f} TiB")
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
