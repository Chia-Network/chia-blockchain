from __future__ import annotations

import concurrent.futures
import logging
from collections import Counter
from pathlib import Path
from threading import Lock
from time import sleep, time
from typing import List, Optional

from chia_rs import G1Element
from chiapos import Verifier

from chia.plotting.manager import PlotManager
from chia.plotting.util import (
    PlotInfo,
    PlotRefreshEvents,
    PlotRefreshResult,
    PlotsRefreshParameter,
    find_duplicate_plot_IDs,
    get_plot_filenames,
    parse_plot_info,
)
from chia.util.bech32m import encode_puzzle_hash
from chia.util.config import load_config
from chia.util.cpu import available_logical_cores
from chia.util.hash import std_hash
from chia.util.ints import uint32
from chia.util.keychain import Keychain
from chia.wallet.derive_keys import master_sk_to_farmer_sk, master_sk_to_local_sk

log = logging.getLogger(__name__)


def plot_refresh_callback(event: PlotRefreshEvents, refresh_result: PlotRefreshResult) -> None:
    log.info(f"event: {event.name}, loaded {len(refresh_result.loaded)} plots, {refresh_result.remaining} remaining")


def check_plots(
    root_path: Path,
    num: Optional[int],
    challenge_start: Optional[int],
    grep_string: str,
    list_duplicates: bool,
    debug_show_memo: bool,
) -> None:
    config = load_config(root_path, "config.yaml")
    address_prefix = config["network_overrides"]["config"][config["selected_network"]]["address_prefix"]
    plot_refresh_parameter: PlotsRefreshParameter = PlotsRefreshParameter(batch_sleep_milliseconds=uint32(0))
    plot_manager: PlotManager = PlotManager(
        root_path,
        match_str=grep_string,
        open_no_key_filenames=True,
        refresh_parameter=plot_refresh_parameter,
        refresh_callback=plot_refresh_callback,
    )

    context_count = config["harvester"].get("parallel_decompressor_count", 5)
    thread_count = config["harvester"].get("decompressor_thread_count", 0)
    cpu_count = available_logical_cores()
    if thread_count == 0:
        thread_count = cpu_count // 2
    disable_cpu_affinity = config["harvester"].get("disable_cpu_affinity", False)
    max_compression_level_allowed = config["harvester"].get("max_compression_level_allowed", 7)
    use_gpu_harvesting = config["harvester"].get("use_gpu_harvesting", False)
    gpu_index = config["harvester"].get("gpu_index", 0)
    enforce_gpu_index = config["harvester"].get("enforce_gpu_index", False)
    decompressor_timeout = config["harvester"].get("decompressor_timeout", 20)

    plot_manager.configure_decompressor(
        context_count,
        thread_count,
        disable_cpu_affinity,
        max_compression_level_allowed,
        use_gpu_harvesting,
        gpu_index,
        enforce_gpu_index,
        decompressor_timeout,
    )

    if num is not None:
        if num == 0:
            log.warning("Not opening plot files")
        else:
            if num < 5:
                log.warning(f"{num} challenges is too low, setting it to the minimum of 5")
                num = 5
            if num < 30:
                log.warning("Use 30 challenges (our default) for balance of speed and accurate results")
    else:
        num = 30

    if challenge_start is not None:
        num_start = challenge_start
        num_end = num_start + num
    else:
        num_start = 0
        num_end = num
    challenges = num_end - num_start

    if list_duplicates:
        log.warning("Checking for duplicate Plot IDs")
        log.info("Plot filenames expected to end with -[64 char plot ID].plot")

    if list_duplicates:
        all_filenames: List[Path] = []
        for paths in get_plot_filenames(root_path).values():
            all_filenames += paths
        find_duplicate_plot_IDs(all_filenames)

    if num == 0:
        return None

    parallel_read: bool = config["harvester"].get("parallel_read", True)

    v = Verifier()
    log.info(f"Loading plots in config.yaml using plot_manager loading code (parallel read: {parallel_read})\n")
    # Prompts interactively if the keyring is protected by a master passphrase. To use the daemon
    # for keychain access, KeychainProxy/connect_to_keychain should be used instead of Keychain.
    kc: Keychain = Keychain()
    plot_manager.set_public_keys(
        [master_sk_to_farmer_sk(sk).get_g1() for sk, _ in kc.get_all_private_keys()],
        [G1Element.from_bytes(bytes.fromhex(pk)) for pk in config["farmer"]["pool_public_keys"]],
    )
    plot_manager.start_refreshing()

    while plot_manager.needs_refresh():
        sleep(1)

    plot_manager.stop_refreshing()

    if plot_manager.plot_count() > 0:
        log.info("")
        log.info("")
        log.info(f"Starting to test each plot with {num} challenges each\n")
    total_good_plots: Counter[str] = Counter()
    total_size = 0
    bad_plots_list: List[Path] = []

    with plot_manager:

        def process_plot(plot_path: Path, plot_info: PlotInfo, num_start: int, num_end: int, lock: Lock) -> None:
            nonlocal total_good_plots
            nonlocal total_size
            nonlocal bad_plots_list

            pr = plot_info.prover

            # Look up local_sk from plot to save locked memory
            (
                pool_public_key_or_puzzle_hash,
                farmer_public_key,
                local_master_sk,
            ) = parse_plot_info(pr.get_memo())
            local_sk = master_sk_to_local_sk(local_master_sk)

            with lock:
                log.info(f"Testing plot {plot_path} k={pr.get_size()}")
                if plot_info.pool_public_key is not None:
                    log.info(f"\t{'Pool public key:':<23} {plot_info.pool_public_key}")
                if plot_info.pool_contract_puzzle_hash is not None:
                    pca: str = encode_puzzle_hash(plot_info.pool_contract_puzzle_hash, address_prefix)
                    log.info(f"\t{'Pool contract address:':<23} {pca}")
                log.info(f"\t{'Farmer public key:' :<23} {farmer_public_key}")
                log.info(f"\t{'Local sk:' :<23} {local_sk}")

            total_proofs = 0
            caught_exception: bool = False
            for i in range(num_start, num_end):
                challenge = std_hash(i.to_bytes(32, "big"))
                # Some plot errors cause get_qualities_for_challenge to throw a RuntimeError
                try:
                    quality_start_time = int(round(time() * 1000))
                    for index, quality_str in enumerate(pr.get_qualities_for_challenge(challenge)):
                        quality_spent_time = int(round(time() * 1000)) - quality_start_time
                        if quality_spent_time > 8000:
                            log.warning(
                                f"\tLooking up qualities took: {quality_spent_time} ms. This should be below 8 seconds "
                                f"to minimize risk of losing rewards. Filepath: {plot_path}"
                            )
                        else:
                            log.info(f"\tLooking up qualities took: {quality_spent_time} ms. Filepath: {plot_path}")

                        # Other plot errors cause get_full_proof or validate_proof to throw an AssertionError
                        try:
                            proof_start_time = int(round(time() * 1000))
                            proof = pr.get_full_proof(challenge, index, parallel_read)
                            proof_spent_time = int(round(time() * 1000)) - proof_start_time
                            if proof_spent_time > 15000:
                                log.warning(
                                    f"\tFinding proof took: {proof_spent_time} ms. This should be below 15 seconds "
                                    f"to minimize risk of losing rewards. Filepath: {plot_path}"
                                )
                            else:
                                log.info(f"\tFinding proof took: {proof_spent_time} ms. Filepath: {plot_path}")

                            ver_quality_str = v.validate_proof(pr.get_id(), pr.get_size(), challenge, proof)
                            if quality_str == ver_quality_str:
                                total_proofs += 1
                            else:
                                log.warning(
                                    f"\tQuality doesn't match with proof. Filepath: {plot_path} "
                                    "This can occasionally happen with a compressed plot."
                                )
                        except AssertionError as e:
                            log.error(
                                f"{type(e)}: {e} error in proving/verifying for plot {plot_path}. Filepath: {plot_path}"
                            )
                            caught_exception = True
                        quality_start_time = int(round(time() * 1000))
                except KeyboardInterrupt:
                    log.warning("Interrupted, closing")
                    return
                except SystemExit:
                    log.warning("System is shutting down.")
                    return
                except RuntimeError as e:
                    if str(e) == "GRResult_NoProof received":
                        log.info(f"Proof dropped due to line point compression. Filepath: {plot_path}")
                        continue
                    else:
                        log.error(f"{type(e)}: {e} error in getting challenge qualities for plot {plot_path}")
                        caught_exception = True
                except Exception as e:
                    log.error(f"{type(e)}: {e} error in getting challenge qualities for plot {plot_path}")
                    caught_exception = True
                if caught_exception is True:
                    break

            if total_proofs > 0 and caught_exception is False:
                log.info(
                    f"\tProofs {total_proofs} / {challenges}, {round(total_proofs/float(challenges), 4)}. "
                    f"Filepath: {plot_path}"
                )
                total_good_plots[pr.get_size()] += 1
                total_size += plot_path.stat().st_size
            else:
                log.error(
                    f"\tProofs {total_proofs} / {challenges}, {round(total_proofs/float(challenges), 4)} "
                    f"Filepath: {plot_path}"
                )
                bad_plots_list.append(plot_path)

        with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, context_count)) as executor:
            logger_lock = Lock()
            futures = []
            for plot_path, plot_info in plot_manager.plots.items():
                futures.append(executor.submit(process_plot, plot_path, plot_info, num_start, num_end, logger_lock))

            for future in concurrent.futures.as_completed(futures):
                _ = future.result()

    log.info("")
    log.info("")
    log.info("Summary")
    total_plots: int = sum(list(total_good_plots.values()))
    log.info(f"Found {total_plots} valid plots, total size {total_size / (1024 * 1024 * 1024 * 1024):.5f} TiB")
    for k, count in sorted(dict(total_good_plots).items()):
        log.info(f"{count} plots of size {k}")
    grand_total_bad = len(bad_plots_list) + len(plot_manager.failed_to_open_filenames)
    if grand_total_bad > 0:
        log.warning(f"{grand_total_bad} invalid plots found:")
        if len(bad_plots_list) > 0:
            log.warning(f"    {len(bad_plots_list)} bad plots:")
            for bad_plot_path in bad_plots_list:
                log.warning(f"{bad_plot_path}")
        if len(plot_manager.failed_to_open_filenames) > 0:
            log.warning(f"    {len(plot_manager.failed_to_open_filenames)} unopenable plots:")
            for unopenable_plot_path in plot_manager.failed_to_open_filenames.keys():
                log.warning(f"{unopenable_plot_path}")
    if len(plot_manager.no_key_filenames) > 0:
        log.warning(
            f"There are {len(plot_manager.no_key_filenames)} plots with a farmer or pool public key that "
            f"is not on this machine. The farmer private key must be in the keychain in order to "
            f"farm them, use 'chia keys' to transfer keys. The pool public keys must be in the config.yaml"
        )

    if debug_show_memo:
        plot_memo_str: str = "Plot Memos:\n"
        with plot_manager:
            for path, plot in plot_manager.plots.items():
                plot_memo_str += f"{path}: {plot.prover.get_memo().hex()}\n"
        log.info(plot_memo_str)
