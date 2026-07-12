# Chia Package Root Context

Verified: 2026-07-02 against 6526ab6f18. If source contradicts this doc, trust source and update the doc.

`chia/` package-root files are process-wide entrypoint and namespace glue. They are not the authority for consensus, wallet state, P2P semantics, daemon privileges, RPC endpoint behavior, plotting, farming, DataLayer stores, or tests; those decisions live in focused module contexts and source.

## When To Read This

Read this for `chia/__init__.py`, `chia/__main__.py`, `chia/py.typed`, package import-time behavior, version exposure, `python -m chia`, or service script wiring that crosses from package metadata into CLI, daemon launch, or service groups.

## Package-Root Contract

- `chia/__init__.py` resolves `__version__` from installed package metadata and falls back to `"unknown"` when metadata is unavailable. That value is visible in CLI output, daemon/RPC responses, peer handshakes, farmer pool headers, and logs.
- Import-time runtime gates are process-wide. Python assertions are required, and CPython free-threading is rejected when detected, because consensus, networking, store, native-extension, async, and DB assumptions rely on those runtime properties.
- `chia/__main__.py` should remain a thin bridge to `chia.cmds.chia:main`; CLI behavior belongs in `chia/cmds/`.
- `chia/py.typed` declares the package as typed for downstream consumers. Removing or moving it changes type-checking behavior even if runtime tests pass.

## Entrypoint And Service Wiring

- Console scripts in `pyproject.toml` are compatibility surfaces. Script names and targets must stay aligned with `chia.util.service_groups`, `chia start`, daemon service validation, PyInstaller executable names, installer payloads, GUI expectations, and tests.
- The root CLI applies root path, keys-root path, passphrase-file handling, and SSL permission checks before subcommands run. Preserve that ordering unless the owning `chia-cmds.md` context is re-audited.
- Avoid adding package-root imports from heavy service modules. Root imports can slow every command, break help text under missing optional dependencies, or initialize subsystems before root path, keys root, logging, config, and SSL checks are established.

## Source Pointers

For package startup, read `chia/__init__.py`, `chia/__main__.py`, and `chia/py.typed`. For console scripts and Python bounds, read `pyproject.toml`. For service groups and startup wiring, read `chia/util/service_groups.py`, `chia/cmds/chia.py`, `chia/cmds/start.py`, `chia/cmds/start_funcs.py`, and `chia/server/start_service.py`.
