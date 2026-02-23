# Fresh Eyes MMR Review Context

## Scope and Intent

This document captures the concrete code paths, invariants, and current test coverage for the MMR-on-reorg fix described in `fresh_eyes_mmr_review_plan.md`.

## High-Level Flow

- MMR commitment verification is performed in `chia/consensus/block_header_validation.py` via `blocks.get_mmr_root_for_block(...)`.
- For augmented reorg prevalidation, `AugmentedBlockchain.get_mmr_root_for_block(...)` computes a fork height and forwards it to `BlockchainMMRManager`.
- `BlockchainMMRManager._build_mmr_to_block(...)` now supports reusing current MMR state and rebuilding fork segments by walking `prev_hash` links.

## Scenario-by-Scenario Verification

### 1) MMR mismatch on reorg validation

- **Code path**
  - `chia/consensus/blockchain_mmr.py`:
    - `_build_mmr_to_block(...)` uses:
      - fast-path current root when already at target,
      - scratch build when no usable context,
      - rollback-to-common-height + backward prev-hash walk for forked segments.
- **Key invariant**
  - On forked validation, appended hashes must come from the actual fork ancestry, not only canonical `height_to_hash`.
- **Current coverage**
  - Integration-level reorg tests in `chia/_tests/blockchain/test_blockchain.py` (`TestReorgs.test_basic_reorg`, `test_long_reorg`) exercise augmented-chain reorg validation paths.
- **Gap**
  - No focused unit test that isolates `_build_mmr_to_block()` on a synthetic fork graph.

### 2) Fork context bypass in header validation

- **Code path**
  - `chia/consensus/block_header_validation.py` now calls `blocks.get_mmr_root_for_block(...)` (wrapper-aware) instead of invoking the manager directly.
  - Protocol method added in `chia/consensus/blockchain_interface.py`.
- **Key invariant**
  - If `blocks` is an `AugmentedBlockchain`, fork-height context from the wrapper must be honored.
- **Current coverage**
  - Reorg integration tests using `AugmentedBlockchain` in `test_blockchain.py`.
- **Gap**
  - No unit test explicitly asserting wrapper dispatch for this callsite.

### 3) Fork-point detection in augmented chain

- **Code path**
  - `chia/consensus/augmented_chain.py::_get_fork_height()`
  - Walks backward from minimum overlay height block and compares `prev_hash` against underlying canonical `height_to_hash`.
- **Key invariant**
  - Detected fork height is the last common canonical ancestor for the overlay chain.
- **Current coverage**
  - Indirectly covered by reorg integration tests.
- **Gap**
  - No direct unit tests for `_get_fork_height()` edge cases.

### 4) Overlay gaps in `height_to_hash`

- **Code path**
  - `chia/consensus/augmented_chain.py::_overlay_hash_from_closest_height()`
  - `chia/consensus/augmented_chain.py::height_to_hash()`
- **Key invariant**
  - Missing intermediate overlay heights can be reconstructed from known fork ancestry.
- **Current coverage**
  - Indirect via augmented-chain reorg tests.
- **Gap**
  - No focused unit tests for gap reconstruction behavior.

### 5) Concurrent overlay-map access during prevalidation

- **Code path**
  - `chia/consensus/augmented_chain.py`
  - Snapshot copy (`self._height_to_hash.copy()`) is used before `min(...)` operations in `_get_fork_height()` and `_overlay_hash_from_closest_height()`.
- **Key invariant**
  - Avoid live-iteration failures while event-loop mutations and worker-thread reads occur concurrently.
- **Current coverage**
  - No explicit concurrency stress test.
- **Gap**
  - Race-hardening is present, but not directly validated by a deterministic test.

### 6) Genesis-level fork-height semantics

- **Code path**
  - `chia/consensus/blockchain.py`
  - MMR rollback now uses signed `fork_info.fork_height` context in add-block reorg flow.
- **Key invariant**
  - Internal rollback behavior preserves genesis-level `-1` semantics.
- **Current coverage**
  - Indirect in reorg tests.
- **Gap**
  - No targeted test asserting signed `-1` behavior in this exact path.

### 7) Reward-chain optional field parsing

- **Code path**
  - `chia/full_node/full_block_utils.py::skip_reward_chain_block()`
  - Parses combined optional tag byte:
    - bit 0 => `infused_challenge_chain_ip_vdf`
    - bit 1 => `header_mmr_root`
- **Key invariant**
  - Parser must correctly skip both independent optionals from one bitmask byte.
- **Current coverage**
  - Existing parser-equivalence tests in `chia/_tests/util/test_full_block_utils.py` are skipped due runtime cost.
- **Gap**
  - Missing lightweight, non-skipped regression for mixed optional combinations.

### 8) Protocol conformance after interface extension

- **Code path**
  - Implementations added for `get_mmr_root_for_block(...)` in:
    - `chia/consensus/blockchain.py`
    - `chia/consensus/augmented_chain.py`
    - `chia/wallet/wallet_blockchain.py`
    - `chia/util/block_cache.py`
    - `chia/_tests/util/blockchain_mock.py`
    - `chia/_tests/blockchain/test_augmented_chain.py` (`NullBlockchain`)
- **Key invariant**
  - All protocol implementers remain type-compatible and dispatch MMR root requests correctly.
- **Current coverage**
  - Compile/runtime exercised through existing tests; explicit mypy gate expected in pre-commit.

## Observed Follow-Ups Worth Tightening

1. `chia/consensus/block_creation.py` still directly calls `blocks.mmr_manager.get_mmr_root_for_block(...)` instead of the protocol wrapper method.
2. Parser change (scenario 7) needs a small dedicated regression test because the broad parser tests are skipped.
3. Augmented helper methods have duplicated "snapshot-min-overlay" logic that can be simplified and centralized.
