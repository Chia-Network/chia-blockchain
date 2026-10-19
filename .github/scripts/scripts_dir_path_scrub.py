"""Stdlib-only path-scrub + importlib exec (single bootstrap surface for scripts-dir modules).

``load_scrub_from_disk_under_dash_i`` is the cold-entry for ``scripts_dir_path_scrub`` itself
(no path-filter). It lazy-loads ``scripts_dir_disk_exec`` from the same ``script_dir`` first.
Every other trusted module load uses ``bootstrap_module_from_scripts_dir`` /
``exec_scripts_dir_module`` → ``_exec_with_path_filter``.
"""

from __future__ import annotations

import importlib.util
import sys
import types
from collections.abc import Callable
from importlib.abc import Loader
from pathlib import Path

_SCRUB_MODULE = "scripts_dir_path_scrub"
_DISK_EXEC_MODULE = "scripts_dir_disk_exec"


def _paired_chicken_egg_import_disk_exec(script_dir: Path) -> types.ModuleType:
    """PAIRED with trusted_formatter_loader_cold_start._bootstrap_disk_exec (importlib tail only)."""
    script_dir = script_dir.resolve()
    if sys.modules.get(_DISK_EXEC_MODULE) is None:
        path = script_dir / f"{_DISK_EXEC_MODULE}.py"
        spec = importlib.util.spec_from_file_location(_DISK_EXEC_MODULE, path)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"{_DISK_EXEC_MODULE}.py must be co-located with path_scrub under {script_dir}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[_DISK_EXEC_MODULE] = module
        spec.loader.exec_module(module)
    return sys.modules[_DISK_EXEC_MODULE].chicken_egg_import_disk_exec(script_dir)


def ensure_disk_exec(script_dir: Path) -> types.ModuleType:
    """Return ``scripts_dir_disk_exec`` primed from script_dir (no top-level sibling import)."""
    return _paired_chicken_egg_import_disk_exec(script_dir)


def load_scrub_from_disk_under_dash_i(script_dir: Path) -> types.ModuleType:
    """Cold-start owner: exec stdlib-only path_scrub once (no path-filter)."""
    script_dir = script_dir.resolve()
    path = script_dir / f"{_SCRUB_MODULE}.py"
    disk = ensure_disk_exec(script_dir)
    cached = disk.cached_trusted_module(_SCRUB_MODULE, path)
    if cached is not None:
        return cached
    return disk.exec_trusted_module_from_disk(_SCRUB_MODULE, path)


def _exec_with_path_filter(
    script_dir: Path,
    path: Path,
    module_name: str,
    *,
    register: bool,
    exec_module: Callable[[types.ModuleType, Loader], object],
) -> types.ModuleType:
    """Exec module source while script_dir is removed from sys.path."""
    script_dir = script_dir.resolve()
    path = path.resolve()
    disk = ensure_disk_exec(script_dir)
    if register:
        cached = disk.cached_trusted_module(module_name, path)
        if cached is not None:
            return cached
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load module spec from {path}")
    module = importlib.util.module_from_spec(spec)
    if register:
        sys.modules[module_name] = module
    script_dir_s = str(script_dir)
    saved_path = sys.path.copy()
    try:
        sys.path = [entry for entry in sys.path if entry != script_dir_s]
        exec_module(module, spec.loader)
    finally:
        sys.path[:] = saved_path
    return module


def exec_scripts_dir_module(
    script_dir: Path,
    path: Path,
    module_name: str,
    *,
    register: bool = True,
) -> types.ModuleType:
    """Load a module from script_dir while that directory is removed from sys.path."""
    path = path.resolve()

    def _run(module: types.ModuleType, loader: Loader) -> None:
        loader.exec_module(module)

    return _exec_with_path_filter(script_dir, path, module_name, register=register, exec_module=_run)


def bootstrap_module_from_scripts_dir(
    script_dir: Path,
    filename: str,
    module_name: str,
) -> types.ModuleType:
    """Canonical scripts-dir bootstrap (path-filtered exec)."""
    return exec_scripts_dir_module(script_dir, script_dir / filename, module_name, register=True)
