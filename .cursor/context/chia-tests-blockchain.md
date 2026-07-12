# chia-tests-blockchain

Verified: 2026-07-02 against 6526ab6f18. If source contradicts this doc, trust source and update the doc.

Scope: `chia/_tests/blockchain/`. This is distilled architectural context for future audit or implementation agents. It intentionally omits test inventory and obvious fixture descriptions.

## When To Read This

Read this for consensus/blockchain tests, block prevalidation/add-block helpers, fork/reorg tests, generator-reference tests, hard-fork commitment tests, and persistent block-fixture validation.

## Module Role

These tests are the executable regression spec for consensus block acceptance. They sit below full-node sync orchestration but above pure consensus helpers: most tests construct real `FullBlock` objects with `BlockTools`, pass them through production pre-validation/body-validation/add paths, and assert the exact `AddBlockResult` or `Err` that protects chain-state invariants.

The suite is not only checking small helpers. It validates that production sequencing remains coherent across:

- finished header validation and VDF/POS/slot rules;
- block body validation, CLVM condition handling, and coin-store transitions;
- fork choice, reorg replay, and `ForkInfo` accounting;
- `AugmentedBlockchain` overlay behavior used by batch validation;
- generator-ref lookup across canonical and fork branches;
- hard-fork commitment behavior for header MMR and sub-epoch challenge roots.

## Primary Harness Contract

`blockchain_test_utils._validate_and_add_block()` is the central abstraction. Treat it as a miniature full-node block-add pipeline, not as a loose assertion helper:

- It wraps the target `Blockchain` in `AugmentedBlockchain` unless the caller supplies a shared overlay.
- It computes current SSI/difficulty using `get_next_sub_slot_iters_and_difficulty(...)`.
- It finds the previous sub-epoch summary block for validation state.
- It runs `pre_validate_block(...)` unless `skip_prevalidation=True`.
- It passes the prevalidated overlay `BlockRecord` into `Blockchain.add_block(...)`.
- It checks the `BlockStore` main-chain invariant before and after each add.

`skip_prevalidation=True` is deliberate in malformed-body tests where the mutation would fail before the body code under test. In that mode, the helper fabricates `PreValidationResult` and signature conditions, so the test is no longer exercising header/CLVM prevalidation.

## State Invariants Under Test

The suite repeatedly defends these consensus invariants:

- Canonical chain has exactly one `in_main_chain` block at each height from genesis to peak.
- Peak selection follows weight first, then lower `total_iters` on equal weight.
- Main-chain extension and fork validation require coherent `ForkInfo`: `peak_height`, `peak_hash`, `fork_height`, `block_hashes`, additions, and removals must describe the branch being validated.
- Coin state is fork-relative, not just DB-relative. A coin may be canonical before the fork, created on the fork, ephemeral inside the same block, or invalid because it only exists on the abandoned branch.
- Transaction-block timestamp and previous transaction-block context drive timelocks, not necessarily the current peak height.
- Generator references must resolve on the same branch as the block being validated and must not cross forks.
- Post-HF2 header MMR/challenge-root commitments are gated by pre-signage-point transaction height, not naïve candidate height.

## Test Taxonomy

`test_blockchain.py` is the broad consensus regression file. Its structure mirrors the production validation pipeline: genesis/slot/header checks first, then prevalidation, body validation, reorg behavior, generator lookup, and direct `ForkInfo` accounting.

Header validation tests mutate otherwise valid blocks with `recursive_replace(...)`, then repair dependent hashes/signatures as needed so the intended check is reached. Common targets include bad previous hash, PoSpace, sub-slot challenge hashes, ICC/CC/RC VDFs, signage point/index constraints, deficit/SES rules, pool target signatures, foliage presence, timestamp ordering, height/weight, reward block hashes, and overflow/empty-slot cases.

Body validation tests build real spend bundles from `WalletTool` and assert transaction-state failures: missing or contradictory tx fields, reward claim mismatch, generator root/ref root mismatch, cost over/under-reporting, canonical generator encoding gates, Merkle/filter mismatches, duplicate outputs/removals, DB and fork double-spends, unknown fork spends, minting, invalid fees, and aggregate signature failures. Many tests bypass prevalidation only when the body path is the intended target.

Reorg tests are behavior-heavy. They validate short reorgs, reorgs from genesis, long reorgs over difficulty changes, heavier-lower-height branches, flip-flops back to a prior branch, stale fork-height handling, failed rollback behavior, reorg transaction replay, `get_tx_peak()` updates, and generator refs that point into the new fork. Shared `ForkInfo` and shared `AugmentedBlockchain` are reused across fork blocks to mirror full-node batch validation.

## Important Sibling Contracts

`AugmentedBlockchain` is the speculative overlay used during parallel validation. Its tests assert that extra blocks are contiguous, first-block ancestry exists in the underlying chain, fork ancestry is populated for orphan branches, generator refs search overlay before underlying chain, committed extra blocks are removed, MMR state is copied, and read-only snapshots reject mutation while preserving lookup behavior.

`find_fork_point.lookup_fork_chain()` and `find_fork_point_in_chain()` are tested with synthetic block graphs because boundary behavior matters at the pre-genesis/root edge, root-shared forks, same-height forks, asymmetric branch lengths, and no-common-ancestor cases. The returned fork-chain map excludes the fork point and uses the genesis challenge for the pre-genesis edge.

`get_block_generator()` is intentionally small but consensus-sensitive: a block with no generator must have no refs; a generator with no refs must not call lookup; refs are returned in the original ref-list order and missing refs surface as `KeyError`.

`test_build_chains.py` protects persistent block fixtures. It verifies cached chains still match `BlockTools` generation parameters and that additions/removals do not spend nonexistent coins. If generated-chain behavior changes intentionally, the cache regeneration path is part of the change.

`test_block_commitments.py` covers HF2 commitment activation by lowering fork heights, then validating both local block acceptance and two-node sync/weight-proof behavior. These tests are expensive but cover the production boundary where consensus commitments interact with full-node sync.

`test_blockchain_transactions.py` uses `two_nodes`, mempool submission, and block creation to bridge protocol/mempool behavior into block validation. It is useful for transaction conditions whose setup is easier through full-node APIs than through isolated consensus helpers.

## Review And Implementation Pitfalls

Do not replace shared fork `ForkInfo` with per-block fresh instances in reorg tests unless the production flow also changed. Fresh instances can hide missing additions/removals replay across fork blocks.

Do not treat `_validate_and_add_block_no_error()` as success-on-peak. It accepts `ALREADY_HAVE_BLOCK`, `ADDED_AS_ORPHAN`, and `NEW_PEAK`; use `_validate_and_add_block(..., expected_result=...)` when peak status matters.

When mutating signed/header-linked fields, update the dependent hash and plot signature or the test may fail earlier than intended. Existing tests often recalculate `transactions_info_hash`, `foliage_transaction_block_hash`, and `foliage_transaction_block_signature` after targeted body mutations.

Hard-fork-gated expectations often vary by `ConsensusMode`. The suite deliberately limits modes for slow or mode-sensitive cases; changing fixtures or heights can invalidate assumptions about which generated blocks are transaction blocks, overflow blocks, or generator-bearing blocks.

Avoid raw sleeps. Blockchain tests mostly use direct deterministic validation; full-node sync/transaction convergence uses `time_out_assert(...)`.

## Verification Guidance

For helper changes touching `_validate_and_add_block`, `AugmentedBlockchain`, generator lookup, or fork handling, include at least one focused test from the affected area plus a representative reorg/generator lookup test. For hard-fork commitment or generated-chain changes, include the relevant commitment/build-chain tests and expect longer runtime.

## Source Pointers

- Consensus regression tests: `chia/_tests/blockchain/`.
- Shared blockchain test helpers: `chia/_tests/blockchain/blockchain_test_utils.py`.
- Chain fixture generation: `chia/_tests/blockchain/test_build_chains.py`, `chia/_tests/util/blockchain.py`.
- Source behavior context: `.cursor/context/chia-consensus.md`, `.cursor/context/chia-full-node.md`.
