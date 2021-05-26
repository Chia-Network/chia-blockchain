import logging,sys
from pathlib import Path

from chia.plotting.plot_tools import load_plot

log = logging.getLogger(__name__)


def plot_info(file: Path):
    plot_info, error = load_plot(file)
    if error:
        print(error)
        sys.exit(1)
    else:
        print("\n".join([
            f"path: {file}",
            f"k: {plot_info.prover.get_size()}",
            f"id: {plot_info.prover.get_id().hex()}",
            f"farmer public key: {plot_info.plot_public_key}",
            f"pool public key: {plot_info.pool_public_key}",
        ]))
        sys.exit(0)
