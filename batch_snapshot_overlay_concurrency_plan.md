# Batch-Snapshot Overlay Concurrency Plan

## Goal

Replace shared live-read usage of `AugmentedBlockchain` in worker-thread prevalidation with a per-batch read snapshot.

## Motivation

`AugmentedBlockchain` is mutable and currently shared between:

- event-loop writer mutations (`add_extra_block()`, `remove_extra_block()`, `add_block_record()`),
- worker-thread reads during `_pre_validate_block()`.

Even with floor caching, this model is easy to misuse because thread-safety is implicit.

## Design

### 1) Keep a mutable writer chain

During batch preparation on the event loop, continue to:

- derive each `BlockRecord`,
- add it to the mutable augmented chain,
- resolve generator references.

This preserves current behavior and `ValidationState` progression.

### 2) Snapshot once per batch for readers

After all blocks in a batch are prepared, create one reader snapshot:

- shallow-copy `_extra_blocks`,
- shallow-copy `_height_to_hash`,
- copy `_overlay_floor`,
- copy `mmr_manager`.

No worker reads the writer instance directly.

### 3) Schedule worker jobs against the snapshot

Use the prepared block metadata + copied `ValidationState` for each block, and run `_pre_validate_block()` with the batch snapshot.

## Expected Tradeoff

- **Pros**
  - Cleaner ownership model: one writer object, many immutable reader snapshots.
  - Easier reasoning for future engineers than implicit shared-mutable concurrency.
- **Cons**
  - One extra snapshot allocation per batch.
  - Slightly delayed worker scheduling (prepare all, then schedule all).

## Validation

- Existing augmented-chain tests.
- Existing block batch prevalidation/sync tests.
- Focus check: no shared mutable overlay maps are read by workers after refactor.
