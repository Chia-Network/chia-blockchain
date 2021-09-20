"""
NOTE: This contains duplicate code from `chia.cmds.plots`.
After `chia plots create` becomes obsolete, consider removing it from there.
"""
import asyncio
import logging
import pkg_resources
from chia.plotting.create_plots import create_plots, resolve_plot_keys
from pathlib import Path
from typing import Any, Dict, Optional

log = logging.getLogger(__name__)


def get_chiapos_install_info() -> Optional[Dict[str, Any]]:
    chiapos_version: str = pkg_resources.get_distribution("chiapos").version
    return {"display_name": "Chia Proof of Space", "version": chiapos_version, "installed": True}


class Params:
    def __init__(self, args):
        self.size = args.size
        self.num = args.count
        self.buffer = args.buffer
        self.num_threads = args.threads
        self.buckets = args.buckets
        self.stripe_size = args.stripes
        self.tmp_dir = Path(args.tmpdir)
        self.tmp2_dir = Path(args.tmpdir2) if args.tmpdir2 else None
        self.final_dir = Path(args.finaldir)
        self.plotid = args.id
        self.memo = args.memo
        self.nobitfield = args.nobitfield
        self.exclude_final_dir = args.exclude_final_dir


def plot_chia(args, root_path):
    if args.size < 32 and not args.override:
        print("k=32 is the minimum size for farming.")
        print("If you are testing and you want to use smaller size please add the --override flag.")
        return
    elif args.size < 25 and args.override:
        print("Error: The minimum k size allowed from the cli is k=25.")
        return

    plot_keys = asyncio.get_event_loop().run_until_complete(
        resolve_plot_keys(
            None if args.farmerkey == b"" else args.farmerkey.hex(),
            args.alt_fingerprint,
            None if args.pool_key == b"" else args.pool_key.hex(),
            None if args.contract == "" else args.contract,
            root_path,
            log,
            args.connect_to_daemon,
        )
    )
    asyncio.get_event_loop().run_until_complete(create_plots(Params(args), plot_keys, root_path))
