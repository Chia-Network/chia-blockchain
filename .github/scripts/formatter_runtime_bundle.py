"""Consumer-shipped formatter runtime bundle constants (loader markers + sibling stems)."""

from __future__ import annotations

# Source of truth for cold_start.LOADER_RESOLVE_MARKER_FILENAMES (equality-tested).
LOADER_RESOLVE_MARKER_FILENAMES: tuple[str, ...] = (
    "isolated_module_exec.py",
    "trusted_formatter_loader.py",
)

# The prose regex/policy selector is gone. The formatter is a single module.
FORMATTER_SIBLING_MODULE_STEMS: tuple[str, ...] = ()

FORMATTER_RUNTIME_FILENAMES: tuple[str, ...] = (
    "scripts_dir_disk_exec.py",
    "scripts_dir_path_scrub.py",
    *LOADER_RESOLVE_MARKER_FILENAMES,
    "trusted_formatter_loader_cold_start.py",
    "formatter_runtime_bundle.py",
    "malware_verdict_formatter.py",
    *(f"{stem}.py" for stem in FORMATTER_SIBLING_MODULE_STEMS),
)

# Combine workflow entry copies runtime bundle + this script (not cold-start preload).
DCR_COMBINE_EXTRA_FILENAMES: tuple[str, ...] = ("dependency_cursor_review_combine_outputs.py",)
