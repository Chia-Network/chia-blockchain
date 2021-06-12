import logging
from collections import Counter
from pathlib import Path
from typing import Dict, List

from blspy import G1Element
from chiapos import Verifier

from chia.plotting.plot_tools import find_duplicate_plot_IDs, get_plot_filenames, load_plots, parse_plot_info
from chia.util.config import load_config
from chia.util.hash import std_hash
from chia.util.keychain import Keychain
from chia.wallet.derive_keys import master_sk_to_farmer_sk, master_sk_to_local_sk

log = logging.getLogger(__name__)


def inventory_plots(root_path, grep_string, plot_public_key):
    config = load_config(root_path, "config.yaml")

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
        grep_string,
        False,
        root_path,
        open_no_key_filenames=True,
    )

    searching_for_plot_public_key = False

    if plot_public_key is not None:
        log.info(f"Only looking for plot with a public key of {plot_public_key}")
        searching_for_plot_public_key = True


    for plot_path, plot_info in provers.items():
        pr = plot_info.prover

        if searching_for_plot_public_key:
            plot_public_key_matches = plot_public_key in str(plot_info.plot_public_key)

        if not searching_for_plot_public_key or plot_public_key_matches:
            plot_id = provers[plot_path].prover.get_id() # https://chiaforum.com/t/does-it-matter-if-you-accidentally-delete-part-of-the-plot-filename/2719/9?u=notpeter
            log.info(f"Inventory: path={plot_path} k={pr.get_size()} pool_public_key={plot_info.pool_public_key} plot_public_key={plot_info.plot_public_key} plot_id={plot_id.hex()}")
