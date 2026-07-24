# Chia Plot Sync Module Context

Verified: 2026-07-12 against 24db9ad3901d. If source contradicts this doc, trust source and update the doc.

`chia/plot_sync/` is the farmer-harvester inventory replication protocol. The harvester-side `Sender` converts `PlotManager` refresh callbacks into an ordered stream of plot-sync messages; the farmer-side `Receiver` validates that stream, accumulates a delta, commits it only at `plot_sync_done`, and exposes the farmer/UI view of each harvester's plots.

## When To Read This

Read this for harvester-to-farmer plot inventory replication, plot-sync ACK/retry behavior, farmer-side plot list state, and UI/RPC plot-count correctness. For local plot discovery/load rules, read `plotting.md`; for farmer proof handling, read `farmer.md`.

## Implementation Authority

- `Sender` is not the plot-state authority. It snapshots and serializes `PlotManager` state from the harvester and depends on refresh lifecycle callbacks for loaded, removed, invalid, key-missing, and duplicate plot lists.
- `Receiver` is the farmer-local authority for what the farmer believes a connected harvester has. Farmer RPC, pool plot counts, and UI state read from `Farmer.plot_sync_receivers`, not directly from the remote harvester.
- Protocol payloads live in `chia/protocols/harvester_protocol.py`; `chia/plot_sync/` owns sequencing, delta semantics, and ACK/error handling. Schema edits are network compatibility changes and must move with protocol message IDs, node-type sender maps, rate limits, API decorators, and tests.
- The farmer and harvester are operator-controlled peers, but plot-sync payloads still cross a network boundary. The receiver validates ordering, duplicate additions, removals of missing plots, `last_sync_id`, and sync/message identifiers before mutating committed state.

## Why This Is Tricky

Public farmer/RPC docs expose harvester plot lists as if they are current inventory, but the implementation is a replicated state machine with recovery. Mid-sync messages are progress, not committed truth. Reset is intentionally full-state reconciliation from the harvester's current `PlotManager` snapshot, so making deltas more incremental can reduce correctness if it weakens convergence after dropped ACKs, disconnects, or refresh races.

## Wrong Assumptions To Avoid

- Do not treat plot sync as plot validation; it is farmer-local inventory replication.
- Do not commit receiver state before `plot_sync_done`.
- Do not treat ACKs as protocol request/reply matching; they are application-level plot-sync messages.
- Do not assume a correct harvester `PlotManager` snapshot means the farmer/UI view has converged.

## Runtime Flow

- Farmer connection creates one `Receiver` per harvester peer in `Farmer.on_connect()`, then sends `harvester_handshake`.
- Harvester `harvester_handshake` installs farmer/pool keys in `PlotManager`, binds `Sender` to the farmer `WSChiaConnection`, starts the sender task, and then starts plot refreshing. This ordering matters: refresh before handshake can load plots without the farmer-owned key filter.
- A refresh cycle is encoded as `plot_sync_start`, one or more `plot_sync_loaded` batches, `plot_sync_removed`, `plot_sync_invalid`, `plot_sync_keys_missing`, `plot_sync_duplicates`, then `plot_sync_done`.
- Each inbound sync message is acknowledged by the farmer with `plot_sync_response`. This is application-level ACK behavior from `Receiver._process()`, not a `protocol_state_machine` request/reply pair.
- On disconnect, the farmer deletes the peer's `Receiver`; the harvester stops sender/refresh state and awaits sender closure. Reconnect creates a new receiver and must re-run handshake.

## Sender State Machine

- `Sender` keeps `_sync_id`, `_next_message_id`, `_last_sync_id`, pending `MessageGenerator`s, and one expected response. It sends exactly one in-flight plot-sync message and advances only after a matching `PlotSyncResponse`.
- `sync_start()` waits while a sync is active, then chooses a time-based sync id and increments it if needed to avoid same-second reuse in tests. `last_sync_id` is included so the receiver can reject missed or reordered sync cycles.
- Loaded plots are batched using the plot manager refresh batch size. Empty list phases still emit a final marker, which is how the receiver advances through every state even when a category is empty.
- `_reset()` clears local sender progress. If the sender task is running, it rebuilds a full initial-style inventory from the current `PlotManager` snapshot so recovery converges on the harvester's present state rather than replaying stale deltas.
- Response matching rejects unexpected, expired, wrong-sync, wrong-message, or wrong-message-type ACKs. Recoverable receiver errors with `expected_identifier` can rewind `_next_message_id`; unrecoverable errors reset the sender.

## Receiver State Machine

- `Receiver` starts idle and moves strictly through `loaded -> removed -> invalid -> keys_missing -> duplicates -> done`. Each message must match the current `sync_id` and `next_message_id`; `plot_sync_start` is allowed to establish the new sync id but still must have the expected message id.
- `initial=True` resets all committed receiver state before processing. Non-initial starts must carry `last_sync_id == receiver.last_sync().sync_id`.
- During a sync, changes live only in `current_sync.delta`. Valid plot additions, valid removals, invalid filenames, key-missing filenames, and duplicates are accumulated separately.
- `plot_sync_done` computes path-list deltas for invalid/key-missing/duplicate categories, applies the valid additions/removals to `_plots`, replaces the side lists with the new synced lists, recalculates total and effective plot sizes, stores the completed sync as `_last_sync`, and returns to idle.
- Progress callbacks with `delta=None` are emitted during batched phases. The committed update callback receives a non-`None` `Delta` only after `done`; farmer state-change fanout suppresses empty non-initial deltas.

## Data Contracts

- `Plot.filename` is the dictionary key on the farmer side. Path normalization changes affect duplicate detection, removals, RPC sorting/filtering, and signature/proof correlation elsewhere in farmer-harvester code.
- `Plot.size` is compatibility-packed: v1 plots use k-size; v2 plots set the high bit and store strength in the low bits. `Plot.param()` reconstructs `PlotParam` from the source-owned v2 plot index/meta group policy.
- Effective plot size is recomputed by the receiver with `_expected_plot_size(plot.param(), constants)` and `UI_ACTUAL_SPACE_CONSTANT_FACTOR`, so `Receiver` needs consensus constants even though plot sync itself is not consensus validation.
- `Delta` is a reporting/commit artifact, not a standalone operation log. For path lists, removals are computed by comparing the previous committed list against the new synced list at `done`.

## Failure And Recovery

- Message timeout is defined in `Constants`. The sender polls for responses and sleeps for the timeout interval after send failures/timeouts before retrying.
- Receiver exceptions are converted into `PlotSyncError` responses. `InvalidIdentifierError` includes an `expected_identifier` so the sender can resend from the receiver's expected point.
- The sender has one special recovery case for a missed final ACK: if the receiver reports expected sync/message ids of zero after the sender already sent the final `plot_sync_done`, the sender finalizes locally.
- Non-recoverable receiver errors, lost connection, or invalid message generators force sender reset. Because reset rebuilds from current plot manager state, recovery is eventually full-state reconciliation rather than minimal delta preservation.

## Concurrency And Lifecycle

- `Sender._run()` is an async task, but `sync_start()` may be called from the plot refresh thread and uses blocking `time.sleep()` while waiting for an active sync to finish. Avoid adding slow work or event-loop-only assumptions to refresh callback paths.
- `Sender._messages` is appended by refresh callbacks and consumed by the async sender task without an explicit lock. The current design relies on simple append/index behavior and one active sync.
- `Receiver` has no broad lock. Farmer handlers, callbacks, and RPC reads rely on asyncio sequencing and short mutation windows. Multi-step receiver changes must preserve callback ordering and committed-vs-in-progress separation.
- Harvester shutdown awaits sender closure after stopping plot refreshing and resetting `PlotManager`; receiver shutdown is implicit in farmer disconnect handling.

## Fragility Hotspots

- Do not treat plot-sync ACKs as server-level replies unless the protocol state machine is deliberately changed. Today they are normal messages with node-type authorization: plot-sync data from harvesters, responses from farmers.
- Do not commit receiver state before `plot_sync_done`. Mid-sync state is progress-only; committing early can make farmer RPC/UI observe partial refreshes and makes recovery from missing later phases inconsistent.
- Preserve the exact phase order, final markers, and message id increments. Empty categories are still protocol states.
- Be careful changing reset behavior. It is the main convergence mechanism after dropped ACKs, late responses, unrecoverable errors, and reconnect-like cases.
- Edits to `Plot` encoding, especially the `size` high bit, affect farmer UI effective space, pool plot counts, and third-party harvester compatibility.
- `set_connection()` expects a farmer connection; changes here should be checked against harvester handshake order and tests. The exception's expected-node wording is easy to regress because it is primarily tested by behavior, not user-facing text.

## Test And Audit Strategy

- Unit-test sender start/stop, connection type validation, response matching, timeout/expired ACK handling, negative duration clamping, reset, and recoverable/unrecoverable error paths.
- Unit-test receiver phase transitions, invalid identifiers, `last_sync_id`, duplicate additions, removals of missing plots, counts-only serialization, committed totals, and effective plot-size calculation.
- Integration-test real farmer-harvester service sync across multiple harvesters, repeated refreshes, valid/invalid/key-missing/duplicate transitions, removals, recovered invalid plots, reconnect-like starts, dropped/late/duplicate ACKs, and not-connected resets.
- For protocol edits, include sender-map/rate-limit/API decorator coverage and farmer-harvester compatibility tests; serialization-only tests are insufficient.

## Source Pointers

- Harvester sender state machine: `chia/plot_sync/sender.py`.
- Farmer receiver state machine: `chia/plot_sync/receiver.py`.
- Plot-sync payloads: `chia/protocols/harvester_protocol.py`.
- Farmer receiver ownership and RPC consumers: `chia/farmer/farmer.py`, `chia/farmer/farmer_rpc_api.py`.
- Harvester refresh callbacks that feed sync: `chia/harvester/harvester.py`, `chia/plotting/manager.py`.
