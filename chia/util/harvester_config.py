"""
Harvester plot directory config helpers.
Extracted from chia.plotting.util to break the daemon ↔ plotting cycle.
"""

from __future__ import annotations

import logging
from pathlib import Path

from chia.util.config import load_config, lock_and_load_config, save_config

log = logging.getLogger(__name__)


def get_plot_directories(root_path: Path, config: dict | None = None) -> list[str]:
    if config is None:
        config = load_config(root_path, "config.yaml")
    return config["harvester"]["plot_directories"] or []


def add_plot_directory(root_path: Path, str_path: str) -> dict:
    path: Path = Path(str_path).resolve()
    if not path.exists():
        raise ValueError(f"Path doesn't exist: {path}")
    if not path.is_dir():
        raise ValueError(f"Path is not a directory: {path}")
    log.debug(f"add_plot_directory {str_path}")
    with lock_and_load_config(root_path, "config.yaml") as config:
        if str(Path(str_path).resolve()) in get_plot_directories(root_path, config):
            raise ValueError(f"Path already added: {path}")
        if not config["harvester"]["plot_directories"]:
            config["harvester"]["plot_directories"] = []
        config["harvester"]["plot_directories"].append(str(Path(str_path).resolve()))
        save_config(root_path, "config.yaml", config)
    return config


def remove_plot_directory(root_path: Path, str_path: str) -> None:
    log.debug(f"remove_plot_directory {str_path}")
    with lock_and_load_config(root_path, "config.yaml") as config:
        str_paths: list[str] = get_plot_directories(root_path, config)
        # If path str matches exactly, remove
        if str_path in str_paths:
            str_paths.remove(str_path)

        # If path matches full path, remove
        new_paths = [Path(sp).resolve() for sp in str_paths]
        if Path(str_path).resolve() in new_paths:
            new_paths.remove(Path(str_path).resolve())

        config["harvester"]["plot_directories"] = [str(np) for np in new_paths]
        save_config(root_path, "config.yaml", config)
