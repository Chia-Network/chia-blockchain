# Fresh-Eyes Review Plan (MMR Commitments and Reorg Validation)

## Short Context: Header MMR Commitments

- `header_mmr_root` is a commitment included in `reward_chain_block`.
- The commitment is validated from `HARD_FORK2_HEIGHT` onward.
- The root is computed over finalized header hashes using MMR, from `aggregate_from` to a selected cutoff block.
- Cutoff selection depends on block context:
  - `starts_new_slot=True`: finalized set includes blocks up to `prev_block`.
  - `starts_new_slot=False`: finalized cutoff is found by walking back from `prev_block` to the highest block finalized for the new signage point.
- Validation recomputes the expected root and compares it to `reward_chain_block.header_mmr_root`; mismatch returns `Err.INVALID_REWARD_BLOCK_HASH`.
- Weight-proof validation may skip this check via `skip_commitment_validation=True`.

## Files in Scope

- `chia/consensus/blockchain_mmr.py`
- `chia/consensus/augmented_chain.py`
- `chia/consensus/block_header_validation.py`
- `chia/consensus/blockchain_interface.py`
- `chia/consensus/blockchain.py`
- `chia/full_node/full_block_utils.py`
- `chia/wallet/wallet_blockchain.py`
- `chia/util/block_cache.py`
- `chia/_tests/util/blockchain_mock.py`
- `chia/_tests/blockchain/test_augmented_chain.py`

## Problem / Scenario / Solution Inventory

### 1) MMR mismatch on reorg validation

- Problem: MMR build could use `height_to_hash` for fork segments that were not represented correctly in augmented overlay state.
- Scenario: one-by-one fork validation where orphan ancestors exist in records but not fully in overlay `height_to_hash`.
- Solution used: `_build_mmr_to_block()` now reuses current MMR, rolls back to common height, then appends fork hashes collected by backward `prev_hash` traversal.

### 2) Fork context bypass in header validation

- Problem: header validation called manager method directly, bypassing augmented wrapper fork-height logic.
- Scenario: `blocks` is an `AugmentedBlockchain`, and MMR computation needs wrapper-provided fork context.
- Solution used: call site switched to `blocks.get_mmr_root_for_block(...)`; protocol updated to include that method.

### 3) Fork-point detection in augmented chain

- Problem: simple fork-point derivation could select an incorrect common ancestor.
- Scenario: reorgs validated with partial overlay and cached orphan ancestry.
- Solution used: `_get_fork_height()` now walks backward from the minimum overlay height block and compares parent hash to underlying canonical `height_to_hash`.

### 4) Overlay gaps in `height_to_hash`

- Problem: augmented `height_to_hash` could have gaps for intermediate fork heights.
- Scenario: intermediate fork ancestors are available as block records but absent from `_height_to_hash`.
- Solution used: `_overlay_hash_from_closest_height()` reconstructs lower-height hashes by backward parent traversal from minimum overlay height.

### 5) Concurrent overlay-map access during prevalidation

- Problem: live iteration over `_height_to_hash` could race with concurrent mutation.
- Scenario: sync/batch prevalidation uses one `AugmentedBlockchain` instance for event-loop mutations and worker-thread reads.
- Solution used: replaced exception-based fallback with snapshot-based reads (`overlay_height_to_hash = self._height_to_hash.copy()` before `min(...)` lookups).

### 6) Genesis-level fork-height semantics

- Problem: clamped `uint32` fork heights can lose signed `-1` meaning.
- Scenario: rollback paths where fork context is at/before genesis.
- Solution used: MMR rollback in blockchain flow uses signed `fork_info.fork_height` context.

### 7) Reward-chain optional field parsing

- Problem: skip parser treated combined tag byte like a standard optional marker.
- Scenario: reward-chain block serialization where infused ICC VDF and MMR root presence are encoded in one bitmask byte.
- Solution used: parser reads combined tag bits explicitly and skips fields accordingly.

### 8) Protocol conformance after interface extension

- Problem: adding `get_mmr_root_for_block` to protocol caused mypy errors in mocks and wallet chain implementations.
- Scenario: pre-commit mypy across test and wallet code.
- Solution used: added `get_mmr_root_for_block` implementations in mocks and wallet blockchain.

## Fresh-Eyes Execution Checklist

1. Verify each problem/scenario/solution path in code.
2. Confirm each path has direct regression coverage.
3. Re-run focused tests:
   - `chia/_tests/blockchain/test_blockchain.py::TestReorgs::test_basic_reorg`
   - `chia/_tests/core/full_node/stores/test_coin_store.py::test_basic_reorg`
   - `chia/_tests/core/mempool/test_mempool.py::TestMempoolManager::test_basic_mempool_manager`
   - `chia/_tests/tools/test_full_sync.py::test_full_sync_test`
   - `./venv/bin/pre-commit run mypy --all-files`
4. Record per-scenario verification:
   - trigger conditions,
   - data structures used,
   - expected invariants,
   - confirming test(s).
