from __future__ import annotations

from pathlib import Path

from chia.simulator.block_tools import get_plot_dir


def get_test_plots(sub_dir: str = "") -> list[Path]:
    path = get_plot_dir()
    if sub_dir != "":
        path /= sub_dir
    return list(sorted(path.glob("*.plot")))
