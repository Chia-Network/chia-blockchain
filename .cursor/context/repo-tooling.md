# Repository Tooling Context

Verified: 2026-07-12 against a5647a9327e5. If source contradicts this doc, trust source and update the doc.

Scope: root-level packaging/config, service entrypoints, install wrappers, GitHub workflows, build/release scripts, developer tools, and GUI submodule integration. This is the single context file for repository tooling because these risks are tightly coupled.

## When To Read This

Read this for changes to repository metadata, install scripts, CI, packaged builds, root wrappers, service launcher wiring, dev tools, or GUI integration. Runtime behavior still belongs in the specific source module docs.

## Implementation Authority

- `pyproject.toml` is the Python packaging authority: project metadata, Python bounds, dependencies/extras, dynamic versioning, supplemental Chia index, and console scripts.
- Console script names and targets are compatibility surfaces. Service-facing executables must stay aligned with `chia.util.service_groups`, CLI start/stop behavior, PyInstaller specs, installer scripts, and GUI expectations.
- Setup may create local environment directories such as `.venv` and `.penv`, but wrapper commands are the repo contract for agents. Local agent/developer Python commands in this workspace must use `tools/py`; tests must use `tools/pytest`.
- `chia-blockchain-gui` is a git submodule, not part of the Python package, but install/build scripts bridge Python versioning, Node workspace layout, packaged daemon binaries, and Electron installers.
- `.github/workflows/` is the enforcement surface for tests, pre-commit, installers, packaging, release, dependency review, CodeQL, labels, Docker triggers, PyPI source upload, and CA updates.
- `build_scripts/` owns platform release packaging, PyInstaller payloads, installer artifact shape, signing/notarization inputs, and dependency artifact policy.
- `tools/` contains wrappers and operational utilities used by developers, CI, and replay/debug workflows. Treat wrapper behavior as part of the repo contract.

## Packaging, Install, And Service Wiring

- Supported Python is declared in `pyproject.toml`; install scripts and CI exercise a version matrix. Dependency changes can break wheel availability, private-index resolution, installer images, or import-time behavior even when unit tests pass.
- Chia native dependencies (`chia_rs`, `chiapos`, `chiavdf`, `chiabip158`, `chia-puzzles-py`, `chialisp`) define Rust/FFI and puzzle-bytecode boundaries used by consensus, wallet, plotting, and CLVM paths.
- Optional extras are meaningful: `dev` defines developer/CI quality tools, `upnp` enables private-index UPnP support, and `legacy_keyring` preserves old keyring behavior.
- `install.sh` / `Install.ps1` choose supported Python, validate platform prerequisites, setup Poetry, sync dependencies/extras, optionally do non-editable installs, create legacy `venv` links, and optionally install plotters.
- `activated.py` / `activated.sh` / `activated.ps1` dispatch commands inside the intended environment. Pre-commit hooks rely on this environment model.
- `chia/__main__.py`, package startup glue, service launchers, daemon/RPC/config helpers, and service groups are coupled to root console scripts and packaged build entrypoints.

## Quality Gates

- `ruff.toml` selects broad lint coverage, enforces future annotations, bans relative imports, and bans direct `asyncio.create_task` in favor of `chia.util.task_referencer.create_referenced_task`.
- `mypy.ini` is generated from template/exclusion files through `manage-mypy.py`; stale exclusions can fail pre-commit when configured.
- `tach.toml` declares enforced import boundaries; dependency-cycle tools and virtual project checks cover additional architecture constraints.
- `pytest.ini` centralizes warnings-as-errors behavior, test roots, xdist defaults, warning filters, and markers.
- `.pre-commit-config.yaml` wires SQL checks, `__init__.py` generation, ruff format/check-fix, tach, Poetry checks, prettier/shfmt/basic hygiene, Chialisp formatting, dependency-cycle checks, mypy config generation, and mypy.

Because hooks may auto-fix or regenerate files, commits touching root config should be reviewed after hooks run.

## CI, Release, And GUI Coupling

- `test.yml` generates a dynamic test matrix through `chia/_tests/build-job-matrix.py`; scheduled/release/full-matrix runs broaden Python and platform coverage.
- `pre-commit.yml` runs hooks across Linux/macOS/Windows and multiple Python versions; local single-platform checks are weaker.
- Install-script workflows validate native install scripts, GUI install scripts, editable/non-editable behavior, and Docker install paths.
- Installer workflows build macOS, Windows, deb, and rpm artifacts through `build_scripts/`; root metadata feeds versions, dependencies, console scripts, and GUI payload expectations.
- `build_scripts/check_dependency_artifacts.py` protects release builders from unexpected source builds by checking artifacts from PyPI plus the Chia index.
- GUI install/build flows initialize/update the submodule, propagate `chia version` into GUI package metadata, and package Python/PyInstaller payloads into Electron artifacts.

Workflow changes should be treated as product changes to supported platforms. Check path filters, branch/tag triggers, concurrency behavior, generated matrix inputs, submodule assumptions, and Chia-managed GitHub action usage.

## Tooling And Operational Utilities

- Repository wrappers (`tools/py`, `tools/pytest`) protect this workspace from global interpreter drift and must remain the default for Python commands.
- Chain generation, full-sync replay, JSON block execution, CLVM/RPC tooling, dependency analysis, and benchmark helpers often encode external artifact formats or process behavior. Avoid cosmetic refactors that hide what contract a tool is exercising.
- Tools that open node DBs, replay chains, or generate artifacts should preserve read-only/write intent, root path isolation, and output naming so they do not contaminate normal node state.
- Benchmark scripts should run via `tools/py -m benchmarks.<name>` and remain consumers of production APIs, not alternate implementations or production dependencies.

## Fragility Hotspots

- Python bounds, dependencies, package metadata, console scripts, or service entrypoints.
- Install scripts, Poetry setup, root wrappers, or environment dispatch.
- Ruff/mypy/tach/pytest/pre-commit config that silently weakens gates.
- CI matrix generation, workflow triggers, path filters, install/build actions, or release signing/notarization inputs.
- GUI submodule handling, version propagation, package payload paths, or installer layout.
- Dependency lock updates without checking private-index and wheel-artifact consequences.

Root/tooling code often looks like glue, but it encodes platform and release assumptions. Avoid cleanup edits unless the affected installer, hook, workflow, or package path is also validated.

## Verification Guidance

- Package metadata/dependencies: run the relevant Poetry/pre-commit path and at least an import/CLI smoke through repository wrappers.
- Console script/service changes: check source entrypoint, service group behavior, and PyInstaller packaging surfaces.
- Install scripts: exercise the affected native script path or CI-equivalent command when practical.
- Static tooling config: run the affected hook directly; use broader pre-commit when behavior is cross-cutting.
- Test matrix/config: check generated matrix behavior plus representative `tools/pytest` runs.
- CI workflow edits: reason about event triggers and matrix dimensions; local tests do not validate GitHub Actions semantics.
- GUI/build coupling: validate the phase that consumes the changed root contract, not just Python tests.

## Source Pointers

- Packaging and tool configuration: `pyproject.toml`, `poetry.lock`, `ruff.toml`, `mypy.ini.template`, `tach.toml`, `pytest.ini`, `.pre-commit-config.yaml`.
- Install and environment wrappers: `install.sh`, `Install.ps1`, `activated.py`, `activated.sh`, `activated.ps1`, `tools/`.
- CI and release automation: `.github/workflows/`, `build_scripts/`.
- GUI submodule integration: `chia-blockchain-gui`.
