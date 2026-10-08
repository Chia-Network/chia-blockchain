"""Stdlib-only cold start for python3 -I (resolve_loader_bundle public entry).

Spine: disk_exec → scrub → path-filtered iso/loader.
"""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

DEFAULT_SCRIPT_CANDIDATES: tuple[Path, ...] = (
    Path(".github/scripts"),
    Path("internal/workflowscripts"),
)

_SCRUB = "scripts_dir_path_scrub"
_DISK_EXEC = "scripts_dir_disk_exec"
_ISO = "isolated_module_exec"

# Contract: must equal formatter_runtime_bundle.LOADER_RESOLVE_MARKER_FILENAMES (equality-tested).
LOADER_RESOLVE_MARKER_FILENAMES: tuple[str, ...] = (
    "isolated_module_exec.py",
    "trusted_formatter_loader.py",
)


def _bootstrap_disk_exec(script_dir: Path) -> types.ModuleType:
    """PAIRED with scripts_dir_path_scrub._paired_chicken_egg_import_disk_exec."""
    script_dir = script_dir.resolve()
    if sys.modules.get(_DISK_EXEC) is None:
        path = script_dir / f"{_DISK_EXEC}.py"
        spec = importlib.util.spec_from_file_location(_DISK_EXEC, path)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"Could not load module spec from {path}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[_DISK_EXEC] = module
        spec.loader.exec_module(module)
    return sys.modules[_DISK_EXEC].chicken_egg_import_disk_exec(script_dir)


def _require_scrub(script_dir: Path) -> types.ModuleType:
    script_dir = script_dir.resolve()
    disk = _bootstrap_disk_exec(script_dir)
    scrub_path = script_dir / f"{_SCRUB}.py"
    cached = disk.cached_trusted_module(_SCRUB, scrub_path)
    if cached is not None:
        return cached
    disk.exec_trusted_module_from_disk(_SCRUB, scrub_path)
    registered = disk.cached_trusted_module(_SCRUB, scrub_path)
    if registered is None:
        raise RuntimeError(f"Failed to register {_SCRUB} from {scrub_path}")
    return registered


def resolve_loader_for_dir(script_dir: Path) -> types.ModuleType:
    script_dir = script_dir.resolve()
    scrub = _require_scrub(script_dir)
    iso = scrub.bootstrap_module_from_scripts_dir(script_dir, f"{_ISO}.py", _ISO)
    iso.register_util_from_scripts_dir(script_dir)
    return iso.resolve_trusted_formatter_loader_for_dir(script_dir)


def resolve_loader_bundle(
    candidate_script_dirs: tuple[Path, ...] = DEFAULT_SCRIPT_CANDIDATES,
) -> tuple[types.ModuleType, Path]:
    for candidate in candidate_script_dirs:
        script_dir = candidate.resolve()
        if not all((script_dir / name).is_file() for name in LOADER_RESOLVE_MARKER_FILENAMES):
            continue
        return resolve_loader_for_dir(script_dir), script_dir
    raise RuntimeError(
        "trusted_formatter_loader.py not found under .github/scripts/. "
        "Run repo-content-updater managed-files for dependency-cursor-review."
    )
