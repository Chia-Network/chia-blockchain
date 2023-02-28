"""
NOTE: This contains duplicate code from `chia.cmds.plots`.
After `chia plots create` becomes obsolete, consider removing it from there.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, Optional

import pkg_resources

from chia.plotting.create_plots import create_plots, resolve_plot_keys
from chia.plotting.util import Params, add_plot_directory, validate_plot_size

log = logging.getLogger(__name__)


def get_chiapos_install_info() -> Optional[Dict[str, Any]]:
    chiapos_version: str = pkg_resources.get_distribution("chiapos").version
    return {"display_name": "Chia Proof of Space", "version": chiapos_version, "installed": True}


def plot_chia(args, root_path):
    try:
        validate_plot_size(root_path, args.size, args.override)
    except ValueError as e:
        print(e)
        return

    plot_keys = asyncio.run(
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
    asyncio.run(create_plots(Params.from_args(args=args), plot_keys))
    if not args.exclude_final_dir:
        try:
            add_plot_directory(root_path, args.finaldir)
        except ValueError as e:
            print(e)
