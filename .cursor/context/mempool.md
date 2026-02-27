# Mempool Subsystem — Deep Context

> Attach when touching `chia/full_node/mempool*.py`,
> `eligible_coin_spends.py`, `pending_tx_cache.py`, or fee estimation.

## File map

| File                         | Lines | Role                                                                 |
| ---------------------------- | ----- | -------------------------------------------------------------------- |
| `mempool_manager.py`         | ~1160 | `MempoolManager`: admission, validation, new_peak handling           |
| `mempool.py`                 | ~810  | `Mempool`: in-memory SQLite data structure, block generator creation |
| `eligible_coin_spends.py`    | ~290  | Fast-forward and dedup singleton logic                               |
| `pending_tx_cache.py`        | ~100  | `ConflictTxCache`, `PendingTxCache` for deferred items               |
| `bitcoin_fee_estimator.py`   | ~100  | Bitcoin-style fee estimation adapter                                 |
| `fee_estimation.py`          | ~80   | `MempoolInfo`, `FeeBlockInfo`, `MempoolItemInfo`                     |
| `fee_estimator.py`           | ~110  | Fee estimator implementation                                         |
| `fee_estimator_interface.py` | ~40   | `FeeEstimatorInterface` protocol                                     |
| `fee_tracker.py`             | ~600  | `FeeTracker`: fee bucket tracking                                    |
| `fee_history.py`             | ~20   | Fee history data                                                     |
| `fee_estimator_constants.py` | ~30   | Estimator tuning constants                                           |
| `fee_estimate_store.py`      | ~15   | Persistence (minimal)                                                |

## Related types

- `chia/types/mempool_item.py` — `MempoolItem`, `BundleCoinSpend`, `UnspentLineageInfo`
- `chia/types/internal_mempool_item.py` — `InternalMempoolItem` (signature separated)
- `chia/types/mempool_inclusion_status.py` — `SUCCESS`, `FAILED`, `PENDING`
- `chia/types/fee_rate.py` — `FeeRate`
- `chia/types/clvm_cost.py` — `CLVMCost`, `QUOTE_BYTES`, `QUOTE_EXECUTION_COST`

---

## Key constants

| Constant                   | Value                     | Meaning                                                |
| -------------------------- | ------------------------- | ------------------------------------------------------ |
| `MEMPOOL_BLOCK_BUFFER`     | 10                        | Mempool capacity = 10× max block cost                  |
| `MEMPOOL_MIN_FEE_INCREASE` | 10 000 000                | Min fee increase for replacement (0.00001 XCH)         |
| `MEMPOOL_ITEM_FEE_LIMIT`   | 2^50                      | Max fee per item (prevents SQLite int64 overflow)      |
| `nonzero_fee_minimum_fpc`  | 5                         | Min fee-per-cost to kick out others (~0.055 XCH/block) |
| `max_tx_clvm_cost`         | `MAX_BLOCK_COST_CLVM / 2` | Single tx cost limit                                   |
| `MAX_SKIPPED_ITEMS`        | 10                        | Max items skipped during block building                |
| `PRIORITY_TX_THRESHOLD`    | 3                         | FF/DEDUP items allowed before cutoff                   |
| `MIN_COST_THRESHOLD`       | 6 000 000                 | Heuristic for block fullness                           |
| `seen_cache_size`          | 10 000                    | Seen spend bundle hash cache                           |

---

## `MempoolManager.validate_spend_bundle()` — Admission pipeline

**Location**: `mempool_manager.py:596`

### Pipeline (in order)

1. **Peak check**: mempool must be initialized

2. **Coin spend processing** (per spend):

   - Track removal names, addition amounts
   - DEDUP eligibility requires canonical CLVM serialization
   - FF eligibility queries `get_unspent_lineage_info_for_puzzle_hash`
   - Builds `BundleCoinSpend` per coin

3. **FF-only rejection**: Bundles with ONLY FF spends are invalid. FF spends
   must be bundled with at least one normal spend.

4. **Coin record lookup**: Fetch from DB. Ephemeral coins (created + spent in
   same bundle) get synthetic records: `confirmed_index = peak.height + 1`,
   `timestamp = peak.timestamp`.

5. **Fee = removal_amount − addition_amount**

6. **Cost/fee limits**:

   - `cost > max_tx_clvm_cost` → reject
   - `fees > MEMPOOL_ITEM_FEE_LIMIT` or would overflow → reject

7. **Capacity check**: If mempool full:

   - `fee_per_cost < nonzero_fee_minimum_fpc (5)` → reject
   - `fee_per_cost ≤ min_fee_rate` → reject

8. **Conflict detection** via `check_removals()`:

   - Already-spent (non-FF) → `DOUBLE_SPEND`
   - Mempool collision → `MEMPOOL_CONFLICT` (may be resolvable)

9. **Puzzle hash match**: Revealed puzzle hash must match coin record

10. **Timelock validation**: `check_time_locks()` (Rust) against peak
    height/timestamp

11. **Impossible constraints**: `assert_before_height ≤ assert_height` → reject permanently

12. **Duration guard**: >2s validation time → reject (DoS protection)

### Return semantics

- `(None, item, conflicts)` → immediate add, remove conflicts
- `(MEMPOOL_CONFLICT, item, [])` → store in conflict cache for retry
- `(ASSERT_HEIGHT_*, item, [])` → store in pending cache for retry
- `(err, None, [])` → permanent failure

---

## `check_removals()` — Conflict detection

**Location**: `mempool_manager.py:229`

### Logic per coin

1. **Spent + non-FF** → `DOUBLE_SPEND` (immediate reject)
2. **In mempool**: look up conflicting items by coin ID
   - Both FF → can chain, no conflict
   - Both DEDUP + same solution → can merge, no conflict
   - Otherwise → `MEMPOOL_CONFLICT`
3. Handles edge case of FF spends indexed under latest singleton coin ID

---

## `MempoolManager.add_spend_bundle()` — Admission + conflict resolution

**Location**: `mempool_manager.py:525`

### Flow

1. Skip if already in mempool (idempotent)
2. Call `validate_spend_bundle()`
3. On success: remove conflicts, add to mempool, return `SUCCESS`
4. On `MEMPOOL_CONFLICT`: add to `_conflict_cache`, return `PENDING`
5. On height-not-met: add to `_pending_cache`, return `PENDING`
6. Otherwise: return `FAILED`

---

## `Mempool` data structure

**Location**: `mempool.py:85`

### Storage

- In-memory SQLite database with table `tx`:
  `name`, `cost`, `fee`, `assert_height`, `assert_before_height`,
  `assert_before_seconds`, `fee_per_cost`, `seq`
- `_items: dict[bytes32, InternalMempoolItem]` — full item data (signatures
  kept separate from SQLite for perf)
- Additional SQLite tables: `spends` (coin_id → item name mapping)

### Key operations

- `add_to_pool()` — insert, evict lowest-fee items if over capacity
- `remove_from_pool()` — remove by item names
- `new_tx_block()` — advance height/timestamp, expire items with
  `assert_before_height`/`assert_before_seconds` violations
- `get_min_fee_rate()` — lowest fee/cost in pool (for admission threshold)
- `at_full_capacity()` — `total_cost + new_cost > mempool_max_total_cost`

### Block building (`create_block_generator2()`)

1. Query items ordered by `fee_per_cost DESC, seq ASC`
2. Process FF/DEDUP info and build transaction batches
3. Try batches through `BlockBuilder.add_spend_bundles()` to account for real compression cost
4. Keep accepted batches and skip non-fitting batches
5. Stop on timeout, or when `BlockBuilder` reports the block is full

---

## `MempoolManager.new_peak()` — Reorg/new-block handling

**Location**: `mempool_manager.py:845`

### Optimization path (simple chain extension)

When `new_peak.prev_transaction_block_hash == self.peak.header_hash`:

1. Expire items violating new height/timestamp constraints
2. Find mempool items spending coins that were just spent on-chain
3. For regular spends: remove (they're included)
4. For FF spends: attempt to rebase to new singleton version
5. Re-add items from conflict/pending caches

### Full reinit path (reorg)

All mempool items re-validated against new chain state. Failed items removed.

---

## Fast-forward (FF) and dedup logic

**Location**: `eligible_coin_spends.py`

### Fast-forward singletons

FF-eligible spends can be "rebased" when the singleton they reference gets
spent. The mempool updates the coin spend to point to the latest unspent
singleton version.

**Key function**: `perform_the_fast_forward()` — replaces the coin in a
`CoinSpend` with the latest unspent version, preserving the puzzle and
solution.

**Tracking**: `UnspentLineageInfo` stores `coin_id`, `parent_id`,
`parent_parent_id` for the latest unspent singleton.

### Dedup

DEDUP-eligible spends with identical solutions can coexist in the mempool.
During block building, they're merged via `IdenticalSpendDedup`.

### Invariant

A bundle cannot contain ONLY FF spends. At least one normal spend is required
to ensure the bundle can eventually be invalidated.
