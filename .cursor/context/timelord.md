# Chia Timelord Module Context

Verified: 2026-07-12 against 24db9ad3901d. If source contradicts this doc, trust source and update the doc.

`chia/timelord/` is the proof-of-time production service. It does not decide chain validity: the full node sends peaks and unfinished blocks, the timelord schedules VDF work against its current local view, and the full node later validates every returned signage point, end-of-sub-slot, compact proof, and infusion point before accepting side effects.

## When To Read This

Read this for timelord VDF scheduling, peak/unfinished-block selection, VDF-client communication, compact proof production, timelord metrics, and full-node/timelord protocol coupling. For final block or VDF acceptance, also read `full-node.md` and `consensus.md`.

## Implementation Authority

- `Timelord` owns local VDF scheduling state, VDF client connections, proof collection, compact-proof work queues, and metrics events. Its state is operational state, not canonical chain state.
- `TimelordAPI` is the full-node protocol entry point. `new_peak_timelord`, `new_unfinished_block_timelord`, and `request_compact_proof_of_time` mutate `Timelord` state under `timelord.lock`; they trust the full node enough to schedule work, but the returned products are still checked by full-node consensus paths.
- `LastState` is the timelord's executable chain view. It can represent the first sub-slot, a peak, or an end-of-sub-slot; all challenge selection, initial classgroup form selection, deficit behavior, SES inclusion, and reward-challenge history derive from this object.
- `iters_from_block()` is the narrow bridge from unfinished/finished reward-chain block data to local SP/IP iteration targets. It calls consensus iteration helpers and PoS validation; exceptions or failed required-iters assertions mean the candidate is not schedulable.
- VDF clients are local subprocesses or external clients connected to the timelord TCP server. They are only accepted from configured IPs and capped while idle, but their returned proofs are still locally validated with `validate_vdf()` before broadcasting.
- Full node remains the acceptance authority. `FullNodeAPI` ignores timelord messages while syncing, serializes IP/EOS handling through `timelord_lock`, reconstructs finished blocks from infusion VDFs, and calls normal block validation before accepting them.

## Runtime Model

Normal timelord mode runs three logical VDF chains:

- challenge chain
- reward chain
- infused challenge chain, only when `LastState.get_challenge(INFUSED_CHALLENGE_CHAIN)` is available

`Timelord.manage()` starts a TCP server for VDF clients, initializes `LastState`, and launches `_manage_chains()` unless bluebox mode is enabled. `_manage_chains()` repeatedly handles failures, consumes pending peaks, maps free VDF clients to unspawned chains, submits iteration targets, and checks the lowest unfinished reward-chain iteration for IP, SP, or EOS completion.

The key reset operation is `_reset_chains()`. It stops existing chain clients after state changes, recomputes all future work relative to the current `LastState.last_ip`, clears stale proof lists by bumping `num_resets`, requeues schedulable unfinished blocks, seeds a limited window of signage points, and always queues the end-of-sub-slot iteration. Changes here affect liveness and correctness more than performance.

## State And Ordering Contracts

- `num_resets` labels proofs by generation. Proofs whose label does not match the current reset are intentionally ignored; removing or weakening this filter can mix old-challenge proofs into current-chain messages.
- `iters_to_submit`, `iters_submitted`, `iteration_to_proof_type`, `iters_finished`, and `proofs_finished` must stay aligned. A submitted iteration is meaningful only with its chain set and proof type.
- SP completion requires both challenge-chain and reward-chain proofs for the same iteration and current reset. The reward-chain VDF challenge must match `LastState.get_challenge(REWARD_CHAIN)` before broadcasting `NewSignagePointVDF`.
- IP completion requires CC/RC proofs and sometimes ICC proof. The matching unfinished block is found by recomputing IP iterations against current state; then the timelord broadcasts `NewInfusionPointVDF` and, after early-height safeguards, may locally synthesize a new `NewPeakTimelord` to continue working without waiting for the full node.
- EOS completion requires the expected chain count for the end-of-slot iteration. It builds `EndOfSubSlotBundle`, handles optional ICC and sub-epoch-summary inclusion, broadcasts `NewEndOfSubSlotVDF`, updates `LastState`, moves viable overflow blocks into the active unfinished set, and resets chains.
- `reward_challenge_cache` is bounded by the sub-slot block window and is used to decide whether an unfinished block's `rc_prev` is in the local chain window. It is not a general fork database.

## Peak And Unfinished-Block Selection

Peak handling intentionally does not always chase the newest heavier announcement. `new_peak_timelord()` accepts the first peak, a heavier peak, or equal weight with lower total iterations, but skips a one-height-ahead heavier peak if a cached unfinished/overflow block with lower or equal iterations would be orphaned. This lets a fast local timelord finish a lower-iteration competing block that can win fork choice.

Unfinished blocks are split into immediate `unfinished_blocks` and future `overflow_blocks`:

- Non-overflow blocks are scheduled when their IP is still ahead of the current last IP and `_can_infuse_unfinished_block()` approves them.
- Overflow blocks whose SP belongs to the previous sub-slot are cached until the EOS window makes their IP schedulable.
- Stale overflow blocks whose total iterations are already behind current total iterations are dropped so they cannot indefinitely block future peaks.
- New epochs disallow overflow infusion, matching consensus expectations.

The helper `overflow_sp_total_iters()` captures the core overflow invariant: an overflow block's signage point may live in the previous slot even though its infusion point is in the next slot.

## Full-Node Coupling

Full node sends `NewPeakTimelord` after peak processing with reward-chain block, next difficulty/SSI, deficit, possible SES, recent reward challenges, and last challenge-block/EOS total iterations. On unfinished block creation it sends `NewUnfinishedBlockTimelord` with the unfinished reward-chain block, foliage, `rc_prev`, SES, and MMR root context.

Timelord responses re-enter full-node validation:

- `NewSignagePointVDF` is adapted into `RespondSignagePoint`, then validated and fanned out to farmers/full nodes by existing full-node signage-point logic.
- `NewEndOfSubSlotVDF` is passed to `FullNode.add_end_of_sub_slot()`, which checks predecessor slots, updates `FullNodeStore`, drains future infusion caches, and may resend peak data to a timelord that is on the wrong state.
- `NewInfusionPointVDF` looks up a matching unfinished block, reconstructs a `FullBlock` with MMR context, validates the pre-farm/pool signature path, and calls `add_block()`. On validation failure, the full node sends its current peak back to only the offending timelord peer.
- `RespondCompactProofOfTime` is a compact-proof response path for bluebox mode; it updates full-node compact VDF handling rather than block production.

## Bluebox / Compact Proof Mode

Bluebox mode turns the service into compact-proof production instead of live chain production. `TimelordAPI` ignores peak and unfinished-block messages in this mode and only queues `RequestCompactProofOfTime` entries. Stale compact-proof work is discarded before appending new requests.

There are two compact-proof execution paths:

- External VDF clients receive a `BLUEBOX` job via `_manage_discriminant_queue_sanitizer()`.
- On Windows or with `slow_bluebox`, `chiavdf.prove()` runs in a `ThreadPoolExecutor`; a tempfile path is used as the shutdown trigger.

Both paths intentionally choose a random target VDF field first, then fall back to the first queued item. This avoids starvation because CC SP/IP compact proofs are much more common than EOS/ICC proofs.

## Concurrency And Lifecycle

- `timelord.lock` is the module's main consistency boundary. API handlers, VDF-client mapping, iteration submission, proof appending, compact queue mutation, and reset operations rely on this lock around multi-field mutations.
- `_do_process_communication()` performs network reads outside many lock sections but appends validated proofs and failure records under the lock. Be careful not to hold the lock across long VDF-client reads.
- `_handle_failures()` prioritizes liveness. A current-generation VDF-client failure resets to EOS-only work; prolonged inactivity backs off the restart threshold up to a source-defined cap and resets all chains.
- Shutdown closes the executor trigger file, cancels communication/main-loop tasks, sends stop signals to VDF clients, closes idle and assigned writers, and closes the TCP server.
- `timelord_launcher.py` is a separate process manager for `chiavdf`'s `vdf_client` binary. It resolves the configured host, restarts clients until stopped, suppresses early stderr noise, and kills all active subprocesses on shutdown.

## RPC And Metrics Surface

`TimelordRpcApi` exposes no request routes. Its only external surface is websocket metrics payload generation for `finished_pot`, `new_compact_proof`, `skipping_peak`, and `new_peak`. Changing event names or payload keys affects daemon/UI/metrics consumers even though there is no route-level RPC API.

## Fragility Hotspots

- `_reset_chains()` is the primary correctness/liveness hotspot. It rewrites iteration queues, active unfinished caches, reset labels, and chain process state in one operation.
- Overflow handling is consensus-sensitive. Changes must preserve previous-slot SP math, EOS-window scheduling, stale overflow pruning, and no-overflow-in-new-epoch behavior.
- Peak skipping is intentional fork-choice support, not stale-state behavior. Removing the orphan check can make the timelord abandon a lower-iteration unfinished block that the full node would have preferred.
- `LastState` must mirror the full-node-provided peak/EOS fields closely enough to compute the same challenges, initial forms, deficits, SES inclusion, and transaction-block heights. Divergence typically appears as rejected VDFs or blocks, not as local exceptions.
- `proof_label == num_resets` checks protect against stale VDF clients racing after resets. Treat these labels as a concurrency invariant.
- The VDF client wire format is ad hoc and length-prefixed with decimal/byte encodings. Any change must be coordinated with the external `vdf_client` binary, not just Python tests.
- Bluebox mode and normal mode are mutually exclusive in API behavior. Avoid adding code paths that partially process peaks while compact-proof workers are active.

## Test Strategy

- Timelord state-machine tests should use `default_1000_blocks`, `create_blockchain()`, and `timelord_peak_from_block()` style helpers to exercise real block/iteration data.
- Peak-selection tests should cover heavier peaks, equal-weight lower-total-iteration peaks, unfinished block orphan prevention, and the full-node reorg result after an IP VDF finishes a lower-iteration candidate.
- Overflow tests should separately cover SP-total-iteration math, caching before EOS, scheduling after EOS, stale overflow pruning, and new-epoch rejection.
- VDF-client tests can unit-test `_handle_client()` whitelist/cap behavior and `_do_process_communication()` invalid-proof handling with synthetic readers/writers and monkeypatched `validate_vdf()`.
- Bluebox tests should cover stale queue expiry, random-field fallback behavior, slow/external proof validation failure, and response broadcasting.
- Full-node integration tests are needed for changes that alter timelord message payloads or response ordering, because the acceptance authority and many failure paths live in `FullNode`/`FullNodeAPI`, not in this module.

## Source Pointers

- Timelord service state and scheduling: `chia/timelord/timelord.py`, `chia/timelord/timelord_state.py`.
- Full-node-facing API and RPC metrics: `chia/timelord/timelord_api.py`, `chia/timelord/timelord_rpc_api.py`.
- Iteration derivation and VDF client launcher: `chia/timelord/iters_from_block.py`, `chia/timelord/timelord_launcher.py`.
- Service startup and local types: `chia/timelord/start_timelord.py`, `chia/timelord/types.py`.
