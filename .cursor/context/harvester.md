# Chia Harvester Module Context

Verified: 2026-07-12 against 24db9ad3901d. If source contradicts this doc, trust source and update the doc.

`chia/harvester/` is the local farming edge. It connects only to farmers, learns the farmer/pool keys through the farmer-initiated harvester handshake, discovers local plot files, checks signage-point eligibility, returns V1 proofs or V2 partial proofs, signs selected farmer requests with plot-local keys, and streams plot inventory changes back to the farmer.

## When To Read This

Read this for farmer-harvester handshake behavior, local plot refresh, signage-point proof lookup, harvester signatures, plot-sync sender behavior, and harvester RPC/config mutation. For plot creation/cache/prover details, read `plotting.md`; for farmer-side proof handling and pool partials, read `farmer.md`.

## Landmarks

| file                                  | owns                                             |
| ------------------------------------- | ------------------------------------------------ |
| `chia/harvester/harvester.py`         | plot state, refresh lifecycle, plot-sync sender  |
| `chia/harvester/harvester_api.py`     | farmer-facing proof/signature/plot-sync handlers |
| `chia/harvester/harvester_rpc_api.py` | local plot list/refresh/delete, config mutation  |
| `chia/harvester/start_harvester.py`   | harvester Service construction                   |

## Implementation Authority

- `Harvester` is the service-local authority for plot state, refresh lifecycle, decompressor configuration, RPC state notifications, and the `Sender` used for plot-sync. It does not validate farmer/full-node consensus state; it trusts the farmer to send current signage point metadata and pool difficulty hints.
- `HarvesterAPI` is the farmer-facing peer API. It is where farmer messages become plot lookups, proof/partial-proof responses, signature responses, and plot list responses. It should stay thin around `PlotManager` and protocol types because it runs in latency-sensitive signage-point paths.
- `PlotManager` from `chia/plotting/manager.py` owns plot discovery and the canonical in-memory map from `Path` to `PlotInfo`. The harvester accesses `plot_manager.plots` under the manager lock; background refresh mutates the same state from a thread.
- `plot_sync.Sender` is the harvester-side inventory replication state machine. It sends ordered plot-sync messages and waits for `plot_sync_response` acknowledgements from the farmer. The farmer-side `Receiver` is the state authority for what the farmer/UI believes this harvester has.
- RPC methods are local operator controls over the same state: list/refresh/delete plots, mutate plot directories, and persist harvester config. They are not the farmer protocol and should not be used to infer peer behavior.

## Why This Is Tricky

Public docs describe harvesters as checking plots for a farmer, but source correctness depends on when plots become usable. The farmer handshake is not just greeting metadata: it installs the keys that decide which local plots may be farmed. Plot refresh, proof lookup, signature lookup, and plot sync all read the same `PlotManager` state under different timing constraints, so moving work across the lock or handshake boundary can make the farmer's inventory diverge from the harvester's local state.

## Wrong Assumptions To Avoid

- Do not load or report plots before the farmer handshake installs acceptable keys.
- Do not treat plot-sync inventory as proof that a plot can produce a valid proof for the current signage point.
- Do not perform expensive prover I/O while holding the plot-manager lock.
- Do not assume the harvester validates chain freshness; the farmer/full node supply and validate the consensus context.

## Service Lifecycle

- `start_harvester.create_harvester_service()` builds a `Service` with `NodeType.HARVESTER`, no advertised port, configured farmer peers, optional RPC, and network-specific consensus constant overrides.
- `Harvester.manage()` creates async runtime state, then on shutdown marks `_shut_down`, shuts down the proof lookup executor, stops plot refreshing, resets the plot manager, stops plot sync, and waits for plot-sync closure.
- A harvester starts loading plots only after receiving `harvester_handshake`. That handler installs farmer/pool public keys into `PlotManager`, binds the plot-sync sender to the farmer connection, starts plot-sync, then starts plot refreshing.
- On farmer disconnect, the harvester stops plot-sync and plot refreshing. Reconnect must re-run the farmer handshake before plots become usable again.

## Plot Discovery And State

- Plot discovery is driven by `PlotManager.start_refreshing()`, which loads the plot cache and starts a thread that periodically scans configured directories for `*.plot` and `*.plot2` files.
- Refresh emits `started`, `batch_processed`, and `done` callbacks. `Harvester._plot_refresh_callback()` converts those into plot-sync start, loaded batches, and final removed/invalid/no-key/duplicate lists.
- `PlotManager` rejects or quarantines plots when keys do not match the farmer handshake, files fail to open, duplicates are found by filename, compression exceeds configured limits, compressed plots lack decompressor contexts, or uncompressed V1 files look too small to be complete.
- `plot_manager.plots` is protected by `PlotManager`'s lock. Code that enumerates plots for RPC, signage-point lookup, or signature lookup must use `with self.harvester.plot_manager:` to avoid racing the refresh thread.
- The plot cache is stored under `cache/plot_manager_v2.dat`; stale unused entries are evicted after refresh. Downgrade compatibility is intentionally handled by using a distinct v2 cache file.

## Farmer Protocol Flow

- The server layer enforces that farmers send `harvester_handshake`, `new_signage_point_harvester`, `request_signatures`, `request_plots`, and `plot_sync_response`; harvesters send proofs, signatures, plot inventory, plot-sync messages, and `farming_info`.
- The signage-point message has a live compatibility split. Old farmers/harvesters use `NewSignagePointHarvester` with precomputed `filter_prefix_bits`; newer peers use `NewSignagePointHarvester2` with `peak_height` and `last_tx_height`, letting the harvester compute filter bits per plot version and enforce fork-height rules. V2 gating (skip before `HARD_FORK2_HEIGHT`) and V1 phase-out (`v1_cut_off_height()`) are keyed on `last_tx_height`, not peak height.
- `new_signage_point_harvester()` ignores challenges until farmer/pool keys are available. This preserves the invariant that loaded plots have already been filtered against farmer-owned keys.
- For each challenge, the harvester snapshots eligible plots under lock, applies the plot filter, skips V2 plots before `HARD_FORK2_HEIGHT`, skips V1 plots after `v1_cut_off_height()`, and performs blocking quality/proof work in the harvester executor.
- V1 plots return full `NewProofOfSpace` messages directly. V2 plots return `PartialProofsData`; the farmer forwards each partial proof to solver services and later reconstructs a `NewProofOfSpace` for normal farmer processing.
- The harvester sends `FarmingInfo` to the farmer after each signage-point lookup with total plots, plots passing filter, V1 proof count, and elapsed lookup time. UI/metrics consumers receive this through farmer and harvester state-change paths.

## Proof Lookup Invariants

- Plot filter and quality checks must use `calculate_pos_challenge(plot_id, challenge_hash, sp_hash)`, `calculate_iterations_quality()`, and `calculate_sp_interval_iters()` with the correct plot parameter and difficulty source.
- Pool-specific difficulty overrides are keyed by `pool_contract_puzzle_hash`. If no matching `PoolDifficulty` exists, the global signage-point difficulty/sub-slot iters remain in force.
- V1 full proof retrieval can fail for decompressor timeouts, line point compression (`GRResult_NoProof received`), plot I/O/prover errors, or fork phase-out checks. These failures are logged and dropped per plot rather than aborting the whole challenge.
- V2 partial proof lookup returns only partial proofs that pass the same required-iterations threshold. It must carry plot id, plot index, `meta_group`, strength, plot public key, and pool identifiers because the farmer/solver path needs those fields to build the final `ProofOfSpace`.
- V2 filter eligibility uses the same `calculate_prefix_bits()` → `passes_plot_filter()` path as V1, but with `NUMBER_ZERO_BITS_PLOT_FILTER_V2` and height-based adjustments (`PLOT_FILTER_V2_FIRST/SECOND/THIRD_ADJUSTMENT_HEIGHT`). Plots with `strength_v2` below `MIN_PLOT_STRENGTH` or above `MAX_PLOT_STRENGTH` are rejected by `check_plot_param()`; harvester-side and validation-side filter math must stay identical or farmers produce proofs full nodes reject. See `chia/types/blockchain_format/proof_of_space.py` for exact constants.
- The lookup warning threshold is operationally important: late proof lookup risks missed rewards. Avoid adding synchronous work, unbounded logging, RPC calls, or long lock holds to the signage-point path.

## Signature Authority

- `request_signatures()` derives the local plot secret from the plot memo, not from a long-lived in-memory key table. It parses memo bytes into pool key-or-puzzle-hash, farmer public key, and local master secret, then derives the local secret with `master_sk_to_local_sk()`.
- The returned signature is the harvester half of the plot signature. The farmer combines it with the farmer key, and for pooled plots also taproot signature material, before declaring proofs or submitting pool partials.
- `plot_identifier` is overloaded: V1 proof responses combine the quality string with the resolved filename, and signature handling recovers the file path by reversing that encoding. Changing this format requires coordinated farmer changes.
- Source signature data fields in the protocol exist for CHIP-22/third-party harvester workflows. Local harvester behavior is source-owned; do not assume those optional protocol fields are unused globally.

## Plot Sync Contract

- Plot sync is ordered by `(sync_id, message_id)`. The sender sends exactly one in-flight sync message, waits for `plot_sync_response`, then advances or resets/retries based on the receiver's expected identifier.
- A refresh cycle is encoded as `plot_sync_start`, `plot_sync_loaded` batches, `plot_sync_removed`, `plot_sync_invalid`, `plot_sync_keys_missing`, `plot_sync_duplicates`, and `plot_sync_done`. Empty lists are still sent as final markers so the receiver can advance states.
- `Sender._reset()` rebuilds a full initial-style inventory from the current `PlotManager` state when recovery is needed while the task is running. This makes idempotent recovery depend on the plot manager's current lock-protected snapshot.
- Farmer `Receiver` applies deltas only at `plot_sync_done`, updates total/effective plot sizes, and emits UI updates for initial sync or non-empty deltas. Mid-sync callbacks are progress notifications, not committed inventory.
- If changing plot sync messages, update both harvester `Sender` and farmer `Receiver`, plus protocol sender maps and request/response expectations. The message sequence is a two-sided state machine, not a batch of independent notifications.

## RPC And Config Mutation

- `HarvesterRpcApi` exposes local endpoints for plot listing, refresh triggering, file deletion, plot-directory mutation, and harvester config mutation.
- `delete_plot()` unlinks the supplied path, triggers refresh, and emits a `"plots"` state change. There is no extra ownership model in this module; RPC authorization and local file permissions are the relevant gates.
- `update_harvester_config()` persists config changes but does not reconfigure an already-created decompressor or restart refresh with new scan settings by itself. Treat many settings as taking effect on future refresh/service restart unless the caller explicitly triggers the relevant lifecycle.
- RPC validates only the minimum refresh interval and basic type coercion. Validation of directory existence, plot readability, and key ownership remains in plot refresh.

## Fragility Hotspots

- Do not start plot refreshing before `harvester_handshake`; doing so loads plots without the farmer/pool key filter and can create incorrect inventory and eligibility state.
- Do not hold the `PlotManager` lock across disk proof reads. The current path snapshots work while scheduling executor tasks and releases the lock before expensive lookups.
- Do not alter `Plot.size` high-bit semantics without a protocol bump. The high bit distinguishes V2 strength from V1 k-size and is consumed by farmer-side plot-sync/UI calculations.
- Be careful with `plot_identifier` parsing and path normalization. Signature lookup depends on exact V1 identifier formatting and resolved paths matching the plot manager keys.
- GPU/compressed-plot behavior crosses into `chiapos.decompressor_context_queue`; failures may present as runtime strings from the prover/decompressor. Tests should cover timeout/drop behavior without assuming every failure raises the same Python exception.
- Protocol edits in this area are compatibility edits. Update `harvester_protocol.py`, `protocol_message_types.py`, sender authorization, API/stub decorators, farmer receiver/handler code, and protocol version behavior together.

## Test And Audit Strategy

- For signage-point changes, test V1 and V2 paths separately: plot filter eligibility, fork-height gating, pool difficulty override, no-key handshake gating, proof/partial-proof counts, and `FarmingInfo` side effects.
- For refresh or plot inventory changes, test `PlotManager` state plus plot-sync sender/receiver convergence. A correct local `get_plots()` result is not sufficient if the farmer receiver would apply a different inventory.
- For signature changes, verify both self-pooled and pool-contract memo shapes, aggregate plot public key generation, missing plot behavior, and farmer-side `_process_respond_signatures()` expectations.
- For RPC/config changes, test persisted config and runtime behavior separately. Several settings are read during service construction or refresh lifecycle rather than dynamically reconfigured.

## Source Pointers

In-module files are in the Landmarks table above. Cross-module authorities:

- Plot inventory and cache authority: `chia/plotting/manager.py`, `chia/plotting/cache.py`, `chia/plotting/prover.py`.
- Plot-sync sender/receiver contract: `chia/plot_sync/sender.py`, `chia/plot_sync/receiver.py`.
- Config helpers used by RPC mutation: `chia/plotting/util.py`.
