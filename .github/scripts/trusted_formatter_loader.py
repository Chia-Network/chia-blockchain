"""Load the malware verdict formatter from an explicit file path (no sys.path prepend)."""

from __future__ import annotations

import sys
import types
from collections.abc import Callable
from pathlib import Path

TRUSTED_FORMATTER_MODULE_NAME = "trusted_malware_verdict_formatter"


def _runtime_bundle():
    bundle = sys.modules.get("formatter_runtime_bundle")
    if bundle is None:
        raise RuntimeError(
            "formatter_runtime_bundle must be loaded before trusted_formatter_loader "
            "(resolve_loader_bundle / resolve_trusted_formatter_loader_for_dir)"
        )
    return bundle


def _require_util(script_dir: Path):
    util = sys.modules.get("isolated_module_exec")
    path = (script_dir.resolve() / "isolated_module_exec.py").resolve()
    if util is not None:
        existing_file = getattr(util, "__file__", None)
        if existing_file and Path(existing_file).resolve() == path:
            return util
    raise RuntimeError("Formatter bundle not resolved; call trusted_formatter_loader_cold_start.resolve_loader_* first")


def _require_loader_module(script_dir: Path) -> types.ModuleType:
    parent = script_dir.resolve()
    loader = sys.modules.get("trusted_formatter_loader")
    if loader is None:
        raise RuntimeError(
            "Formatter bundle not resolved; call trusted_formatter_loader_cold_start.resolve_loader_* first"
        )
    loader_file = getattr(loader, "__file__", None)
    if not loader_file or Path(loader_file).resolve().parent != parent:
        raise RuntimeError(
            "Formatter bundle not resolved; call trusted_formatter_loader_cold_start.resolve_loader_* first"
        )
    return loader


def import_module_from_trusted_script(
    script_path: Path,
    module_name: str | None = None,
) -> types.ModuleType:
    script_path = script_path.resolve()
    name = module_name or f"trusted_script_{script_path.stem}"
    util = _require_util(script_path.parent)
    return util.load_module_isolated(script_path, name)


def ensure_formatter_sibling_modules(script_dir: Path) -> None:
    """Load co-located formatter modules with scripts-dir isolation."""
    parent = script_dir.resolve()
    for stem in _runtime_bundle().FORMATTER_SIBLING_MODULE_STEMS:
        mod_name = stem
        existing = sys.modules.get(mod_name)
        if existing is not None:
            existing_path = getattr(existing, "__file__", None)
            if existing_path and Path(existing_path).resolve().parent == parent:
                continue
        path = parent / f"{stem}.py"
        if not path.is_file():
            continue
        import_module_from_trusted_script(path, mod_name)


def load_format_malware_review_verdict(script_path: Path) -> Callable[[str], str]:
    """Return format_malware_review_verdict loaded from an explicit trusted file path."""
    script_path = script_path.resolve()
    _require_loader_module(script_path.parent)
    module = import_module_from_trusted_script(script_path, TRUSTED_FORMATTER_MODULE_NAME)
    formatter = getattr(module, "format_malware_review_verdict", None)
    if not callable(formatter):
        raise RuntimeError(f"{script_path} missing format_malware_review_verdict")
    return formatter


def find_and_load_format_malware_review_verdict(
    *candidate_dirs: Path,
) -> Callable[[str], str]:
    for script_dir in candidate_dirs:
        script_path = script_dir / "malware_verdict_formatter.py"
        if script_path.is_file():
            return load_format_malware_review_verdict(script_path)
    raise RuntimeError(
        "malware_verdict_formatter.py not found under .github/scripts/. "
        "Run repo-content-updater managed-files for dependency-cursor-review "
        "(config companion_files pull in malware-verdict-formatter and "
        "trusted-formatter-loader automatically) "
        "or use managed-files group:dependency-cursor-review."
    )
