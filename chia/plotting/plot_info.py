import logging,sys

from chia.plotting.plot_tools import load_plot

log = logging.getLogger(__name__)


def plot_info(file: str):
    (plot_info,error) = load_plot(file)
    if error!="":
        print(error)
        sys.exit(1)
    else:
        pr = plot_info.prover
        id = pr.get_id()
        print(f"path: {file}")
        print(f"k: {pr.get_size()}")
        print(f"id: {id.hex()}")
        print(f"farmer public key: {plot_info.plot_public_key}")
        print(f"pool public key: {plot_info.pool_public_key}")
        sys.exit(0)
