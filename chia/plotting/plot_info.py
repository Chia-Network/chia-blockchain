import logging,sys
from collections import Counter
from pathlib import Path
from typing import Dict, List

from chia.plotting.plot_tools import PlotInfo, find_duplicate_plot_IDs, get_plot_filenames, load_plot, parse_plot_info
from chia.util.config import load_config
from chia.util.hash import std_hash
from chia.util.keychain import Keychain
from chia.wallet.derive_keys import master_sk_to_farmer_sk, master_sk_to_local_sk

log = logging.getLogger(__name__)


def plot_info(path: str):
    (plot_info,error) = load_plot(path)
    if error!="":
        print(error)
        sys.exit(1)
    else:
        pr = plot_info.prover
        id = pr.get_id()
        print(f"path: {path}")
        print(f"k: {pr.get_size()}")
        print(f"id: {id.hex()}")
        print(f"farmer public key: {plot_info.plot_public_key}")
        print(f"pool public key: {plot_info.pool_public_key}")
        sys.exit(0)