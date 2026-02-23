# Snapshot-Free Overlay Concurrency Plan

## Goal

Remove read-side snapshot copying of `AugmentedBlockchain._height_to_hash` while preserving safe concurrent access during batch prevalidation (event-loop mutations + worker-thread reads).

## Failure Flow (Why snapshots were added)

1. `pre_validate_block()` mutates one shared `AugmentedBlockchain` via `add_extra_block()`.
2. Worker threads concurrently run `_pre_validate_block()` through `run_in_executor(...)`.
3. Header/MMR validation in workers reads overlay data and computes fork context.
4. Old read paths used `min(self._height_to_hash)` / `min(self._height_to_hash.items(), ...)`.
5. Concurrent mutation during iteration caused runtime iteration races (`dict changed size`) and/or fallback paths that could lose fork context.

## Principle for Snapshot-Free Fix

Avoid read-time dictionary iteration entirely.

Instead of computing min overlay height/hash by scanning dict in readers, maintain a writer-updated cached pointer to the lowest overlay entry.

## Proposed Design

### New state in `AugmentedBlockchain`

- Add:
  - `_overlay_floor: tuple[uint32, bytes32] | None`
  - Represents current minimum overlay `(height, hash)`.

### Writer responsibilities (single-writer event loop)

- Update `_overlay_floor` on each mutation:
  - `add_extra_block()`
  - `add_block_record()`
  - `remove_extra_block()`
- Rules:
  - On insert: if new height is lower than current floor, replace floor.
  - On delete of non-floor entry: keep floor unchanged.
  - On delete of floor entry: recompute floor once (scan dict in writer path only).
  - On empty dict: set floor to `None`.

### Reader responsibilities (worker threads)

- `_get_fork_height()` and `_overlay_hash_from_closest_height()` read `_overlay_floor` only.
- Never iterate `_height_to_hash` in read paths.
- Keep direct key lookups (`dict.get(height)`) where exact height is requested.

## Why this is concurrency-safe enough

- Current architecture has one logical writer (event loop) and many readers (workers).
- Race-prone operation was dictionary iteration; this is eliminated from readers.
- Reader sees eventually consistent floor pointer; correctness is preserved because reads are used for fork context derivation and can tolerate slightly stale view within one prevalidation wave.

## Alternative options considered

1. **RW lock around overlay maps**
   - Strong consistency but adds lock contention and cross-thread lock complexity.
2. **Immutable map / copy-on-write each mutation**
   - Simple reads, expensive writes and larger memory churn.
3. **Keep current snapshots**
   - Correctness workaround, but repeated O(n) read-side copies on hot path.

Chosen approach is lower overhead and simpler than lock-heavy alternatives.

## Implementation Steps

1. Add `_overlay_floor` field and initialize to `None`.
2. Implement helper `_recompute_overlay_floor_from_map()` for writer-only recompute.
3. Update `add_extra_block()` to maintain floor incrementally.
4. Update `add_block_record()` and `remove_extra_block()` to maintain/recompute floor.
5. Replace `_min_overlay_entry()` read-snapshot logic with floor read.
6. Keep existing external behavior unchanged.

## Validation Plan

- Existing focused tests:
  - `chia/_tests/blockchain/test_blockchain.py::TestReorgs::test_basic_reorg`
  - `chia/_tests/core/full_node/stores/test_coin_store.py::test_basic_reorg`
  - `chia/_tests/core/mempool/test_mempool.py::TestMempoolManager::test_basic_mempool_manager`
  - `chia/_tests/tools/test_full_sync.py::test_full_sync_test`
- Add targeted augmented-chain tests:
  - floor maintenance on insert/remove,
  - floor recompute when removing current minimum height,
  - gap resolution still works when floor moves.
- Run `pre-commit run mypy --all-files`.

## Risks / Watch Points

- Incorrect floor maintenance can mask fork context bugs.
- `remove_extra_block()` deletes contiguous heights in some paths; floor recompute logic must account for this.
- Future code introducing multiple writers would require revisiting this design.
