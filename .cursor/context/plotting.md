# Chia Plotting Module Context

Verified: 2026-07-12 against 24db9ad3901d. If source contradicts this doc, trust source and update the doc.

`chia/plotting/` is the shared plot lifecycle boundary. It creates plot files, opens and abstracts V1/V2 provers, scans configured harvester plot directories, persists a prover cache, parses plot memos into farming keys, and supplies the lock-protected plot inventory consumed by the harvester, plot sync, `chia plots check`, simulator block tools, and external plotter wrappers.

This module does not own consensus validity, farmer pooling state, or network protocol handling. It prepares local plot state and proof/prover primitives so those higher layers can make fork-, difficulty-, and protocol-aware decisions.

## When To Read This

Read this for plot creation, plot IDs, memo parsing, V1/V2 prover abstraction, plot cache/refresh behavior, plot directory config helpers, and diagnostics such as `chia plots check`. For live signage-point handling, read `harvester.md`; for pool singleton state, read `pools.md`.

## Implementation Authority

- `create_plots.py` owns in-process chiapos V1 plot creation and experimental Rust-backed V2 plot creation. It resolves farmer/pool keys from explicit CLI values or the keychain, writes plot memo bytes, computes plot IDs, and calls `DiskPlotter` or `create_v2_plot()`.
- `PlotManager` owns local plot discovery and the canonical in-memory `Path -> PlotInfo` map. It runs a background refresh thread, batches directory scans, filters unusable plots, tracks duplicate/no-key/failed-open sets, and updates the on-disk cache.
- `Cache` owns serialized prover metadata under `cache/plot_manager_v2.dat`. It is an optimization, not the authority for file existence or key ownership; refresh revalidates cache entries against the filesystem, keys, compression policy, and size heuristics.
- `prover.py` is the compatibility layer over external proof libraries. It hides V1 `chiapos.DiskProver` and V2 `chia_rs.Prover` behind `ProverProtocol`, preserving common calls for plot ID, memo, parameter, compression level, serialized prover data, and quality lookup.
- `util.py` owns config-facing plot scan helpers, refresh event/result shapes, memo parsing/streaming, duplicate filename checks, harvester config mutation helpers, and plot-size CLI validation.
- `check_plots.py` is an operator diagnostic flow. It uses `PlotManager` loading semantics, then stress-tests quality lookup and proof validation. It should not be treated as the production harvesting path.

## Why This Is Tricky

Public plotting docs frame plots as files tied to a farmer key, pool key, or pool contract address. In source, those choices become long-lived binary contracts: plot IDs seed proof generation, memos recover local secrets for later signatures, and portable plots route rewards through singleton-controlled puzzle hashes. A plotting change can therefore break harvesting, farmer aggregate signatures, pool portability, external plotters, simulator fixtures, or diagnostics even if plot creation itself still succeeds.

## Wrong Assumptions To Avoid

- Do not treat the plot cache as authoritative; it accelerates refresh but file/key/prover checks still decide loadability.
- Do not treat plot ID, memo, and plot public key as independent fields; they are coupled through creation, signature derivation, and proof validation.
- Do not infer production harvesting behavior from `chia plots check`; diagnostics intentionally open and inspect cases normal harvesting may reject.
- Do not make V2 support look like compressed V1 support; the prover contract and farmer/solver flow are different.

## Plot Identity And Memo Contracts

- Every loaded plot must have exactly one pool target form: old-style `pool_public_key` or pool-contract `pool_contract_puzzle_hash`. Creation asserts this, memo parsing returns either a `G1Element` or `bytes32`, and later farmer/harvester signature logic branches on that type.
- V1 plot memos have two exact source-defined layouts for public-key and pool-contract plots. `parse_plot_info()` rejects any other length. This memo is the source of the local plot secret used by harvester signature responses.
- The plot public key is derived as `local_pk + farmer_pk` for pool-public-key plots, and `local_pk + farmer_pk + taproot_pk` for pool-contract plots. This must stay aligned with `chia.types.blockchain_format.proof_of_space.generate_plot_public_key()` and farmer aggregate-signature verification.
- V1 plot IDs are computed from pool public key or pool contract puzzle hash plus plot public key. V2 plot IDs are computed by `compute_plot_id_v2()` from strength, plot public key, pool key/hash, plot index, and meta group.
- Current V2 creation hardcodes placeholder plot-index and meta-group values; `V2Prover.get_param()` mirrors this placeholder. Any future multi-index/group support must update creation, prover metadata, proof construction, farmer/harvester protocol payloads, and tests together.

## Discovery And Refresh Model

- Plot discovery reads configured harvester directories via `get_plot_directories()` and scans `*.plot` plus `*.plot2`. Recursive scan and symlink following are config driven; path resolution failures and unreadable directories are logged and skipped.
- `PlotManager.start_refreshing()` loads the cache and starts a thread that periodically scans directories when `needs_refresh()` is true. `stop_refreshing()` joins that thread; `reset()` clears loaded plots and error state.
- Refresh emits `started`, `batch_processed`, and `done` callbacks. Harvester converts those callbacks into plot-sync messages, so callback ordering and result semantics are observable by farmer/UI state.
- `PlotManager.plots` is protected by the manager's lock. Harvester code snapshots or reads it under `with plot_manager:` and then performs expensive proof work outside the lock. Do not add disk proof reads, RPC calls, or long logging loops while holding this lock.
- Batch refresh work opens files concurrently with a `ThreadPoolExecutor`, but result mutation is centralized through locks and the final `self.plots.update()` under the manager lock.

## Load Filters And Quarantine State

- A plot is not loaded if it fails extension-specific prover opening, has missing farmer/pool keys, duplicates an already-loaded filename, exceeds `max_compression_level_allowed`, is compressed while no parallel decompressor is configured, or appears too small under source-defined V1 plot-size policy.
- `failed_to_open_filenames` stores retry timestamps and suppresses repeated open attempts until `retry_invalid_seconds` elapses. Removed or renamed files are dropped from this set on refresh.
- `no_key_filenames` records plots whose farmer public key or pool public key is not currently available. `open_no_key_filenames=True` lets diagnostics open them while preserving the warning state.
- Duplicate detection in `PlotManager` is filename-based across directories, not plot-ID validation. `find_duplicate_plot_IDs()` is a separate operator diagnostic that parses filename suffixes and is intentionally lightweight.
- Compressed plot handling crosses the `chiapos.decompressor_context_queue` boundary. GPU initialization may fall back to CPU harvesting; runtime decompressor failures may surface as stringly `RuntimeError`s from lower libraries.

## Cache And Persistence

- Cache serialization uses `VersionedBlob(uint16(CURRENT_VERSION), bytes(CacheDataV1(...)))` with streamable entries. Field changes are persistence changes and must account for older cache files.
- Cache entries store serialized prover data, farmer/pool identifiers, derived plot public key, and last-use time. They intentionally do not remove the need to check path existence, file size, compression policy, and key ownership during refresh.
- Cache cleanup removes expired unused entries after refresh and bumps last-use for loaded plots. The retention lifetime belongs in source policy.
- `Cache.load()` has a compatibility guard for suspicious oversized V1 prover data from older bladebit/chiapos behavior. Removing it can resurrect bad cache entries for users who have not manually deleted `plot_manager_v2.dat`.
- `plot_manager_v2.dat` was introduced to avoid downgrading/upgrading cache shape collisions after compression-level metadata was added. Do not casually rename it or collapse it with older cache files.

## V1/V2 Prover Contract

- V1 uses `chiapos.DiskProver`; full proofs are retrieved locally with `get_full_proof(challenge, index, parallel_read)`, and proof validation uses `chiapos.Verifier`.
- V2 uses `chia_rs.Prover`; quality lookup returns `PartialProof` wrappers, and full proof solving is done by `chia_rs.solve_proof()` in diagnostics or by solver services in the farmer flow.
- `get_prover_from_file()` and `get_prover_from_bytes()` dispatch solely by filename suffix: `.plot2` means V2, `.plot` means V1. Unsupported extensions raise `ValueError`.
- `V1Prover.get_strength()` intentionally raises because strength is V2-only. Code that needs plot parameters should use `get_param()` and branch on `size_v1` vs `strength_v2`.
- `V2Prover.get_compression_level()` returns zero because V2 plots are not treated as compressed V1 plots. Do not reuse V1 compression policy as a V2 strength policy.

## Harvester And Farmer Coupling

- Harvester startup constructs `PlotManager`, configures decompressor state, and starts refreshing only after farmer handshake installs farmer and pool public keys. Starting refresh before handshake can load plots against empty key lists and produce wrong inventory.
- Harvester signage-point handling reads `PlotInfo` from `PlotManager`, applies consensus plot filters and fork gates, then uses prover methods to find V1 proofs or V2 partial proofs. Plotting must preserve the metadata needed for `make_pos()` and solver requests.
- Harvester signature responses parse the plot memo and derive the local key on demand. Memo format, plot public key generation, and resolved filename identity are therefore part of the farmer-harvester signature contract.
- Plot sync depends on `PlotRefreshResult.loaded`, `removed`, `failed_to_open_filenames`, `no_key_filenames`, and duplicate state. A local refresh change can become a farmer/UI compatibility change through `chia.plot_sync`.
- Farmer reconstructs and validates proofs with `verify_and_get_quality_string()`. Plotting-side changes to plot ID, parameter, strength, memo, or key derivation must be checked against consensus proof validation and farmer aggregate-signature construction.

## CLI, External Plotters, And Simulator Coupling

- `chia plots create` and `chia.plotters.chiapos` both call `resolve_plot_keys()` and `create_plots()`; external plotter wrappers for bladebit and madmax call `resolve_plot_keys()` and pass the resulting keys to subprocess CLIs.
- Plot size validation lives in `util.validate_plot_size()` and is CLI/operator policy: mainnet min k comes from config, and `--override-k` still applies source-defined lower bounds.
- `chia plots check` deliberately opens no-key plots, can list duplicate filename-style plot IDs, and can reveal raw memo bytes. Treat it as an admin/debug surface with more permissive loading than normal harvesting.
- Simulator `BlockTools` uses `create_plots()`, `create_v2_plots()`, and `PlotManager` to generate deterministic local plots for tests and block generation. Test-only private keys and debug plot IDs/memos in creation should not leak into production assumptions.

## Fragility Hotspots

- Do not change memo lengths, field order, or key derivation without updating create, cache, harvester signature handling, farmer aggregate verification, external plotter arguments, and tests.
- Do not hold the `PlotManager` lock across expensive prover I/O. The signage-point path is latency-sensitive; slow lookups risk missed rewards.
- Be careful with V1/V2 fork semantics. Plotting exposes parameters and proof material, but consensus helpers decide V1 phase-out, V2 activation, plot filter prefix bits, and proof-size rejection.
- Filename and path identity matter. Duplicate tracking is by filename, cache keys are `Path`s, harvester signature lookup resolves paths from `plot_identifier`, and refresh maps prover filenames back into `self.plots`.
- Cache data can be stale, malformed, or from older external plotters. Refresh must stay robust to bad serialized prover data and treat cache failures as recoverable operator issues.
- External libraries (`chiapos`, `chia_rs`) define much of the runtime behavior and exception surface. Tests should not assume all invalid plots or decompressor failures raise uniform Python exceptions.

## Test And Audit Strategy

- For creation/key changes, cover pool-public-key and pool-contract plots, explicit keys vs keychain-derived keys, memo bytes, plot ID calculation, and taproot inclusion.
- For refresh changes, cover added/removed files, invalid retry timing, no-key handling, duplicate filenames, recursive scan/symlink settings, cache load/save/expiry, suspicious cache entry dropping, and compression/decompressor policy.
- For prover changes, test suffix dispatch, V1 wrapper compatibility, V2 parameter/quality behavior, bytes round trips where supported, and unsupported extension failures.
- For harvester-facing changes, test plot sync convergence and signage-point lookup separately. A correct `PlotManager.plots` result is not enough if farmer-side plot sync or signature routing would diverge.
- For diagnostics, test `check_plots()` behavior with V1 and V2 paths, low challenge counts, duplicate listing, memo display, and proof validation failures without relying on production harvesting side effects.

## Source Pointers

- Plot creation and key resolution: `chia/plotting/create_plots.py`, `chia/plotting/util.py`.
- Plot discovery/cache: `chia/plotting/manager.py`, `chia/plotting/cache.py`.
- Prover abstraction: `chia/plotting/prover.py`.
- Operator diagnostics: `chia/plotting/check_plots.py`.
- Consensus proof helpers: `chia/types/blockchain_format/proof_of_space.py`.
