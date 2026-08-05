# Chia Full Node Module Context

Verified: 2026-07-12 against 24db9ad3901d. If source contradicts this doc, trust source and update the doc.

This module is the orchestration boundary where untrusted peer/RPC inputs become consensus, mempool, wallet-notification, and timelord/farmer side effects. The main safety property is not held in one class: it depends on preserving exact ordering between `Blockchain`, `FullNodeStore`, `MempoolManager`, SQLite stores, peer caches, and async fanout.

## When To Read This

Read this for full-node sync, block propagation, mempool coupling, peak processing, wallet/timelord/farmer notifications, full-node RPC reads, and `FullNodeStore` behavior. For pure block validity, read `consensus.md`; for wire schema or connection mechanics, read `protocols.md` or `server.md`.

## Landmarks

| file                                    | owns                                                 |
| --------------------------------------- | ---------------------------------------------------- |
| `chia/full_node/full_node.py`           | peak processing, sync orchestration, peer/RPC fanout |
| `chia/full_node/full_node_api.py`       | peer message handlers, tx/block/SP intake            |
| `chia/full_node/mempool_manager.py`     | transaction-admission authority                      |
| `chia/full_node/full_node_store.py`     | volatile SP/EOS/unfinished-block caches              |
| `chia/full_node/block_store.py`         | full block + peak persistence, in_main_chain         |
| `chia/full_node/coin_store.py`          | current-peak UTXO view, FF lineage markers           |
| `chia/full_node/sync_store.py`          | peak-to-peer targets, sync flags                     |
| `chia/full_node/tx_processing_queue.py` | per-peer tx backpressure/DoS queue                   |

## Implementation Authority

- `Blockchain.add_block()` is the validation and persistence authority for blocks and reorgs. `FullNode` may pre-validate, batch, cache, and broadcast, but it must not treat peer-provided peak, block, weight, signage point, or unfinished-block data as authoritative until consensus code accepts it.
- `MempoolManager.add_spend_bundle()` is the transaction-admission authority. P2P `new_transaction` fee/cost values are only advertisements used for fetch priority and peer-accountability checks; the locally computed `MempoolItem` cost/fee wins.
- `FullNodeStore` is not a consensus store. It is a bounded, volatile cache for signage points, end-of-slot bundles, unfinished blocks, future VDF-dependent objects, recent pooling data, and tx fetch bookkeeping. Do not infer chain truth from it without checking `Blockchain`/`BlockStore`.
- RPC is semi-trusted but still crosses a boundary. Expensive endpoints run CLVM or block-generator work, read chain/mempool state, and sometimes take `priority_mutex` at low priority. Keep RPC reads consistent with the current main chain when returning spend/addition/removal state.

## Mutation Ordering Contracts

- New peak processing is deliberately split into a locked phase and an unlocked fanout phase. `FullNode.peak_post_processing()` must run under `blockchain.priority_mutex`; it updates hints, `FullNodeStore`, mempool peak state, and gathers wallet/signage data. `peak_post_processing_2()` must run after releasing the lock; it sends timelord/full-node/wallet notifications and broadcasts tx changes.
- Block additions use high-priority blockchain locking; transaction admission uses low-priority locking after expensive pre-validation. This prevents transaction work from starving block acceptance while still making mempool insertion atomic with the chain peak used for validation.
- During batch sync, pre-validation can be pipelined, but actual `Blockchain.add_block()` calls are sequential and carry mutable `ValidationState`, `ForkInfo`, and an `AugmentedBlockchain`. The augmented view must be kept aligned with underlying MMR/cache state between batches.
- `ForkInfo` is a rolling validation context, not just metadata. Skipped/already-known fork blocks still need `advance_fork_info()`/`run_single_block()` when they are not on the current main chain, otherwise later block-body validation sees an incomplete additions/removals view.

## Sync Model

- `new_peak` announcements only populate `SyncStore` and trigger short/batch/long sync choices. Weight and height advertised by peers select candidates; weight proof validation and subsequent block validation decide whether to adopt.
- Long sync has two separate flags: `sync_mode` means the node is actively batch-adding toward a validated target; `long_sync` prevents duplicate long-sync tasks while the node is still collecting peaks/weight proof. Transaction processing treats syncing as a hard rejection path.
- Weight proofs are hostile input. `request_validate_wp()` checks tip height/weight against the selected peak, rejects cached-bad peaks, validates via `WeightProofHandler`, and bans peers that provide malformed or invalid proofs. The proof's recent chain must connect to sub-epoch summaries and VDF segment samples; it is not a substitute for downloading and validating blocks.
- `SyncStore.peak_to_peer` is bounded and preserves the active target peak when evicting old entries. Code that changes eviction or target handling can strand sync with no peers even though peers previously announced the target.

## Mempool Coupling

- `MempoolManager.peak` must always be the most recent transaction block, not merely the chain peak. Timelocks and block-generator selection depend on timestamped transaction-block context.
- The fast `new_peak()` path is valid only for simple transaction-chain extension with `spent_coins` supplied. Reorgs, missing spent coins, or non-linear transaction block ancestry force full mempool reinitialization and revalidation.
- `seen_bundle_hashes` and `in_flight_bundle_hashes` serve different DoS controls. `in_flight` deduplicates concurrent expensive pre-validation without churn; `seen` suppresses repeated known-invalid or recently processed bundles. On pending/conflict outcomes, `FullNode.add_transaction()` removes the seen mark so resubmission can succeed after state changes.
- Peer-advertised tx fee/cost is checked twice: before fetching already-known txs and after local validation for fetched txs. Old nodes get a narrow cost tolerance for quote overhead; outside that tolerance, the peer can be banned.
- Pending and conflict caches are retried on each new transaction peak. FF singleton spends may be rebased on simple extension; bundles containing only FF spends are intentionally rejected so every bundle has a normal invalidation path.
- `TransactionQueue` is part of the DoS model. Local/trusted transactions bypass peer queues; peer queues are per-peer limited and use advertised fee/cost for priority plus round-robin deficit to prevent one peer from monopolizing validation.

## Signage, EOS, and Unfinished Blocks

- `FullNodeStore.finished_sub_slots` is rebuilt on every peak to represent the relevant SP/IP slots around the peak. Reorgs across a sub-slot-iterations change clear cached slots; same-difficulty reorgs preserve only signage points before the fork total-iterations boundary.
- Future EOS/SP/IP caches exist because VDF-derived objects may arrive before the infused reward-chain challenge they depend on. They are bounded by key, entries-per-key, and TTL; peak processing drains the matching challenge and forwards only the recent cached signage points accepted by source policy.
- `new_finished_sub_slot()` intentionally uses timelord locking rather than blockchain locking. It may reject a valid-looking EOS if a concurrent peak has made it obsolete; peak processing is expected to add the canonical sub-slot later.
- Unfinished blocks are keyed by reward hash with an optional foliage hash because the old protocol cannot distinguish duplicate transaction-block variants. The v2 path prefers the deterministically "best" foliage hash and refuses to fetch worse or excessive duplicates.
- `seen_unfinished_blocks`, `pending_tx_request`, `peers_with_tx`, and tx fetch tasks are volatile anti-duplication/backpressure state. Failure to clear timeout entries does not corrupt consensus, but it can suppress useful fetches or misattribute peer tx advertisements.

## Persistence Semantics

- `BlockStore.add_full_block()` inserts blocks with `in_main_chain=False`; `Blockchain`/store peak management later marks the canonical path. Reorg rollback clears `in_main_chain` above the fork but does not delete fork blocks.
- `CoinStore` represents the current peak's UTXO view. Its spent-index sentinels distinguish normal unspent coins, coins spent at a height, and FF singleton lineage optimization. Rollback recalculates the FF marker based on parent lineage, so FF behavior depends on rollback correctness.
- Coin-store writes expect exact row counts when marking spends. A mismatch is treated as invalid state rather than a soft miss, which protects the one-coin-one-record invariant but makes DB consistency assumptions visible as exceptions.
- Hint persistence is derived from `StateChangeSummary` after block acceptance. Hint size policy lives in source; maximum-size hints also serve as puzzle-hash subscriptions for wallet notification lookup.

## RPC and Wallet Notification Gotchas

- `get_blockchain_state` reports `sync_mode` as `sync_mode or long_sync`; this can show syncing before block download begins. `synced` additionally requires recent transaction-block time and at least one full-node connection unless in simulator mode.
- Recent signage point/EOS RPC responses may report `reverted=True` by searching recent chain context, because `recent_*` caches outlive reorgs for pooling/UI support.
- `/get_additions_and_removals` explicitly checks that the requested block hash is still the main-chain hash at its height while holding the blockchain mutex; without that check fork blocks in `BlockStore` would look like canonical history.
- `/push_tx` calls `FullNode.add_transaction()` directly and returns only `FAILED` as an `RpcError`; it does not use the peer transaction queue. Wallet P2P `send_transaction` enqueues a `TransactionQueueEntry` (trusted peers get high-priority treatment), waits up to 45 seconds on `queue_entry.done`, and returns `PENDING` on timeout.

## Fragility Hotspots

- The highest-risk edits are those that move work across the blockchain mutex boundary, change `sync_mode`/`long_sync` transitions, alter `ForkInfo` advancement during skipped blocks, or treat non-transaction peaks as mempool peaks.
- Cache limits in `FullNodeStore`, `SyncStore`, and `TransactionQueue` are behavioral controls, not just memory tuning. Raising or removing them changes peer-driven resource exposure.
- Weight-proof code mixes deterministic sampling, cached sub-epoch segments, recent-chain reconstruction, and multiprocessing VDF validation. Keep seed derivation, summary ordering, and segment count bounds stable unless the consensus proof format changes.
- Tests around this module often need to assert timing/ordering effects rather than just return values: lock phase vs fanout phase, tx queue timeout vs eventual mempool inclusion, sync flag transitions, and reorg-driven mempool rebuilds.

## Source Pointers

For exact store schemas, volatile cache behavior, sync-target handling, transaction backpressure, mempool admission behavior, and block-processing sequence, read the source files in `chia/full_node/` listed in the Landmarks table above. For focused coverage, start with the matching tests under `chia/_tests/core/full_node/stores/`, plus `chia/_tests/core/full_node/test_tx_processing_queue.py`.
