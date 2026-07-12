# chia-consensus

Verified: 2026-07-12 against 24db9ad3901d. If source contradicts this doc, trust source and update the doc.

Scope: `chia/consensus/`. This is distilled architectural context for future audit or implementation agents. It intentionally omits file inventory and obvious helper summaries.

## When To Read This

Read this for block validation, fork choice, reorg coin-state replay, difficulty/sub-slot logic, reward validation, VDF/POS validation, and hard-fork commitment behavior. If the task is peer sync, mempool admission, wallet state, or RPC shape, start with that module's context and return here only for consensus authority.

## Landmarks

| file                                        | owns                                          |
| ------------------------------------------- | --------------------------------------------- |
| `chia/consensus/blockchain.py`              | add_block() commit authority, peak/fork state |
| `chia/consensus/block_body_validation.py`   | coin/tx state transition checks, ForkInfo use |
| `chia/consensus/block_header_validation.py` | proof/timing/slot/header checks               |
| `chia/consensus/augmented_chain.py`         | speculative overlay for batch validation      |
| `chia/consensus/blockchain_mmr.py`          | post-HF2 header MMR state                     |
| `chia/consensus/pot_iterations.py`          | iteration/difficulty math                     |
| `chia/consensus/default_constants.py`       | consensus constants                           |

## Implementation Authority

`chia.consensus` is the local authority for deciding whether a block is valid and whether it becomes the canonical peak. It does not own networking, sync orchestration, or wallet notifications; those live in full-node modules. It does own the consensus-facing view of chain state: block records, height-to-hash mapping, fork-local additions/removals, difficulty and sub-slot iteration transitions, VDF/POS validation, reward/fee/body checks, and post-HF2 header commitments.

Most public paths split validation into two stages:

- Pre-validation computes `required_iters`, runs generator/signature work, validates finished headers, and builds an in-memory `BlockRecord`.
- `Blockchain.add_block()` revalidates body state under the blockchain lock, writes durable stores, applies fork choice, updates height map and MMR, then advances `_peak_height`.

That split is a core safety boundary. Pre-validation is allowed to be parallel and speculative. `add_block()` is the sequential commit point.

## Consensus State And Ownership

`Blockchain` coordinates four state stores that must agree after a committed peak change:

- `BlockStore`: full block bytes, block records, `in_main_chain`, peak pointer, sub-epoch challenge segments.
- `CoinStore`: UTXO state for the current canonical peak only.
- `BlockHeightMap`: dense canonical height -> hash cache plus canonical sub-epoch summaries.
- `BlockchainMMRManager`: post-HF2 header-MMR state over finalized canonical block hashes.

The update ordering in `Blockchain.add_block()` is deliberate:

- full block and peak-related DB writes happen inside `block_store.transaction()`;
- in-memory block record cache is updated after async DB work inside that transaction;
- `height_map` and MMR are updated only after the DB transaction commits;
- `_peak_height` is assigned last, after dependent stores can answer lookups for the new peak.

If this ordering changes, readers can observe a peak whose block, height map entry, MMR state, or coin records are not yet available.

## Fork Choice And Reorg Contract

Fork choice is purely:

- greater weight wins;
- equal weight with lower `total_iters` wins;
- otherwise current peak remains.

`ForkInfo` is the bridge between validation and reorg application. It is not just metadata. It must contain every addition/removal/reward coin across the candidate fork range, with `block_hashes` ordered by height. `_reconsider_peak()` replays coin-store state from this object when a fork becomes peak. If `ForkInfo` is incomplete, the reorg can validate but apply the wrong coin set.

Important sequencing rules:

- `fork_info.peak_height` must line up with the candidate block's parent height before body validation.
- Genesis and non-genesis candidates have different previous-hash expectations before body validation.
- `fork_info.block_hashes` must cover the expected post-fork range exactly.
- For main-chain extension, `fork_info.reset(...)` clears fork history before validating the new block.
- For known/orphan/fork blocks, `advance_fork_info()` may replay intermediate full blocks from `BlockStore` to rebuild additions/removals before the current block is handled.

The code uses assertions for many of these contracts. Treat assertion failures here as consensus-state corruption or caller misuse, not as normal invalid-block handling.

## Validation Layering

Header validation answers “is the block’s proof/timing/slot/header structure valid?” Body validation answers “does this block correctly transform transaction and coin state?”

Header validation depends on `ValidationState` (`ssi`, difficulty, previous SES block). `pre_validate_block()` mutates the caller-provided `ValidationState` while queuing batch validation, then passes a copy into the worker. Full node batch sync relies on this: the mutable `ValidationState` speculatively advances `ssi`/`difficulty` from raw `new_*` fields for scheduling, while `add_block()` later receives the preserved state needed for commit. Safety comes from `validate_finished_header_block()` rejecting those raw fields unless a valid `subepoch_summary_hash` accompanies them.

Difficulty and SSI transitions must flow through a validated sub-epoch summary. `validate_finished_header_block()` rejects raw `new_difficulty` or `new_sub_slot_iters` fields unless the finished sub-slot also carries a valid `subepoch_summary_hash`. `block_to_block_record()` converts that validated hash into `block_rec.sub_epoch_summary_included`, and that computed block-record field is the authoritative source for committed `ValidationState` advancement; do not treat peer-provided `block.finished_sub_slots[0].challenge_chain.new_*` fields as trusted state on their own.

Body validation relies on header validation already being complete. It checks:

- transaction-block vs non-transaction-block field presence;
- reward claim exactness for skipped non-transaction blocks since the previous transaction block;
- generator root/ref roots, ref count limits, and post-SF9 generator-ref ban;
- CLVM cost and canonical generator encoding after SF9;
- addition/removal Merkle roots and BIP158 transaction filter;
- duplicate additions/removals within the block;
- coin existence and double-spend rules across DB state plus `ForkInfo`;
- value conservation, reserve fee, farmer reward overflow bound, and declared fee equality;
- puzzle hash consistency for removals;
- Rust time-lock evaluation using previous transaction block height/timestamp;
- presence of an aggregate signature after pre-validation has already verified it.

The subtle part is coin lookup on forks. A removal may be:

- ephemeral, created earlier in the same block;
- from canonical DB state at or before the fork point;
- created inside `fork_info.additions_since_fork`;
- invalid because it only exists on the old canonical branch after the fork.

Do not simplify this into “query coin store and check spent”. That loses fork semantics.

## Parallel Validation Overlay

`AugmentedBlockchain` lets batch validation see blocks that are not committed yet. It is a chain overlay, not a passive cache:

- extra blocks must be added contiguously;
- height-to-hash lookups prefer the overlay;
- fork ancestry is populated when the batch starts on a non-canonical branch;
- generator references first walk overlay blocks, then delegate to the underlying chain;
- the MMR manager is deep-copied so speculative MMR roots do not mutate canonical MMR state;
- worker jobs receive `read_only_snapshot()` to prevent mutation from the executor path.

After a block successfully commits, full-node batch code removes it from the overlay. If the overlay and canonical chain disagree about height mapping, pre-validation can validate against a different ancestor path than `add_block()` later commits.

## Difficulty, Slots, And Time Coupling

Difficulty and sub-slot iterations are recomputed only at eligible epoch boundaries. Both use transaction-block timestamps around previous/current epoch reference points, are clamped by `DIFFICULTY_CHANGE_MAX_FACTOR`, then truncated to `SIGNIFICANT_BITS`; SSI is additionally rounded down to a multiple of `NUM_SPS_SUB_SLOT`.

Epoch/sub-epoch completion depends on:

- sufficient height;
- zero deficit;
- whether a sub-epoch summary was already included;
- whether the next height can be first in an epoch;
- lookback through previous records, sometimes through fork paths rather than canonical height lookups.

Overflow block handling changes both challenge selection and the “previous transaction block at signage point” calculation. Several hard-fork gates use `pre_sp_tx_block_height(...)`, not candidate height. This matters especially near HF2/SF9 boundaries.

## Hard Fork Commitments

The hard-fork commitment rules introduce two commitments in this module:

- sub-epoch summary `challenge_root` via `make_sub_epoch_summary(..., make_challenge_root=True)`;
- `reward_chain_block.header_mmr_root`, validated in finished-header validation.

Both are gated by pre-signage-point transaction height. `block_creation.unfinished_block_to_full_block_with_mmr()` and `validate_finished_header_block()` must compute the same MMR root for the same candidate context, including overflow/new-slot behavior.

MMR root semantics:

- genesis has no MMR root;
- at a new slot, all blocks through previous block are finalized;
- within a slot, only prior blocks with earlier signage point, or blocks before the crossed slot boundary, are included;
- fork validation may rebuild an MMR root by rolling back to a fork height and walking the candidate branch.

`BlockchainMMRManager.add_block_to_mmr()` requires sequential canonical insertion. Reorgs must roll the manager back before appending new canonical records. The current MMR implementation is in-memory and rebuilt on startup from canonical `height_map` starting at `HARD_FORK2_HEIGHT`.

## Block Creation Mirrors Validation

Block creation constructs commitments that body/header validation later recomputes:

- reward claims include pool/farmer coins for the previous transaction block and intervening non-transaction blocks;
- transaction filter includes puzzle hashes for additions/rewards and coin IDs for removals;
- addition root groups by puzzle hash and hashes coin IDs per puzzle hash;
- non-transaction blocks have transaction foliage, generator, and generator refs stripped at infusion;
- `calculate_infusion_point_total_iters()` adds an extra sub-slot when SP iters exceed IP iters.

Creation APIs accept callbacks for signatures and fee computation. Consensus validity still comes from the deterministic commitments and later validation; callback behavior must not be trusted as validation.

## Trust Boundaries

Inputs from peers/farmers are untrusted until they pass validation. The highest-risk external calls are:

- Rust CLVM generator execution and `SpendBundleConditions` production;
- Rust BLS/signature validation as part of generator execution;
- Rust `check_time_locks()`;
- VDF proof validation;
- SQLite-backed `BlockStore`/`CoinStore` reads during fork reconstruction;
- BIP158 filter construction/serialization.

Failure mode expectations:

- generator or VDF failure should return an invalid-block error, not partially mutate state;
- DB lookup inconsistency often asserts because consensus code expects local stores to be internally coherent;
- `PreValidationResult.error` must be checked before trusting `required_iters` or `conds`;
- `conds.validated_signature` is required for blocks with generators before body validation accepts them.

## Persistence And Cache Gotchas

`BlockHeightMap` is a canonical-chain cache, not a source of orphan/fork truth. It is reconciled from the DB at startup by walking backward from the stored peak and stops early only when both block hash and sub-epoch summary match. Reorg rollback truncates height-to-hash and deletes SES entries above the fork height.

`try_block_record()` only checks the in-memory cache. Code paths that need orphan records or records outside the cache use `get_block_record_from_db()` or `block_store`. Mixing these up changes whether a valid fork appears disconnected.

`lookup_block_generators()` is fork-aware: generator refs may resolve on a fork branch first, then the canonical chain. After SF9 refs are banned, but legacy paths still matter for historical blocks and tests.

## Audit Focus Areas

- Any change that touches `ForkInfo`, `advance_fork_info()`, `include_spends()`, or `_reconsider_peak()` can corrupt reorg coin-state replay.
- Any change that moves `_peak_height` earlier, flushes height map/MMR before DB commit, or catches commit exceptions differently can expose inconsistent peak state.
- Any change to `pre_sp_tx_block_height()`, overflow detection, or finished-sub-slot counting can shift hard-fork gates, generator flags, challenge roots, and MMR roots.
- Any change to `AugmentedBlockchain` height mapping, read-only snapshots, or MMR copying can make sync batch validation disagree with sequential commit validation.
- Any change to body validation that treats DB coin records as canonical without considering `fork_info` can reject valid fork spends or accept invalid branch spends.
- Any change to MMR bagging, pop logic, finalized-block cutoff, or fork rebuild must be checked against block creation and validation together.
- Any change to sub-epoch summary generation must preserve the relationship between `prev_ses_block`, challenge root gating, and difficulty/SSI boundary computation.

## Source Pointers

For files in the Landmarks table above, read the source in `chia/consensus/` directly. In-module but not landmarked: `chia/consensus/block_rewards.py` (reward/fee amount math). Cross-module authority: `chia/full_node/mempool_manager.py`. For regression coverage, start with `chia/_tests/blockchain/test_blockchain.py`, `chia/_tests/blockchain/test_augmented_chain.py`, `chia/_tests/blockchain/test_block_commitments.py`, and `chia/_tests/core/consensus/test_mmr.py`.
