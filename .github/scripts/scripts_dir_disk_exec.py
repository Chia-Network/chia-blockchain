"""Stdlib-only trusted module disk exec (canonical no-filter load + cache lookup)."""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

_DISK_EXEC = "scripts_dir_disk_exec"


def cached_trusted_module(module_name: str, path: Path) -> types.ModuleType | None:
    """Return a sys.modules entry when it already points at the resolved trusted path."""
    path = path.resolve()
    existing = sys.modules.get(module_name)
    if existing is None:
        return None
    existing_file = getattr(existing, "__file__", None)
    if existing_file and Path(existing_file).resolve() == path:
        return existing
    return None


def bootstrap_disk_exec_from_script_dir(script_dir: Path) -> types.ModuleType:
    """Idempotent no-filter load of this module from co-located script_dir (__file__-safe)."""
    script_dir = script_dir.resolve()
    path = script_dir / f"{_DISK_EXEC}.py"
    cached = cached_trusted_module(_DISK_EXEC, path)
    if cached is not None:
        return cached
    spec = importlib.util.spec_from_file_location(_DISK_EXEC, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load module spec from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[_DISK_EXEC] = module
    spec.loader.exec_module(module)
    registered = cached_trusted_module(_DISK_EXEC, path)
    return registered if registered is not None else module


def chicken_egg_import_disk_exec(script_dir: Path) -> types.ModuleType:
    """After optional paired importlib stub, resolve disk_exec from script_dir."""
    return bootstrap_disk_exec_from_script_dir(script_dir)


def exec_trusted_module_from_disk(module_name: str, module_path: Path) -> types.ModuleType:
    """Exec a module from disk without path-filter (stdlib-only sources only)."""
    module_path = module_path.resolve()
    cached = cached_trusted_module(module_name, module_path)
    if cached is not None:
        return cached
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load module spec from {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module
