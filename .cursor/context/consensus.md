# Consensus Layer — Deep Context

> Attach when touching `chia/consensus/`, block acceptance, reorgs, difficulty,
> or VDF iteration logic.

## File map

| File                            | Lines | Role                                                                                  |
| ------------------------------- | ----- | ------------------------------------------------------------------------------------- |
| `blockchain.py`                 | ~1090 | `Blockchain` class: chain state, `add_block()`, `_reconsider_peak()`                  |
| `blockchain_interface.py`       | ~54   | Protocol definitions: `BlockRecordsProtocol`, `BlocksProtocol`, `BlockchainInterface` |
| `augmented_chain.py`            | ~169  | `AugmentedBlockchain`: in-memory overlay for parallel validation                      |
| `block_header_validation.py`    | ~1060 | `validate_unfinished_header_block()`: all header checks                               |
| `block_body_validation.py`      | ~580  | `validate_block_body()`: transaction/coin checks, `ForkInfo`                          |
| `block_creation.py`             | ~650  | `create_unfinished_block()`, `unfinished_block_to_full_block()`                       |
| `difficulty_adjustment.py`      | ~410  | Difficulty & sub-slot-iters recalculation per epoch                                   |
| `pot_iterations.py`             | ~101  | SP/IP iteration math, quality → required_iters                                        |
| `pos_quality.py`                | ~29   | Expected plot size calculation                                                        |
| `block_rewards.py`              | ~54   | Pool/farmer reward schedule (halving)                                                 |
| `coinbase.py`                   | ~25   | Pool/farmer coin creation from block height                                           |
| `full_block_to_block_record.py` | ~170  | `block_to_block_record()`                                                             |
| `find_fork_point.py`            | ~109  | Fork point search between two chains                                                  |
| `get_block_challenge.py`        | ~170  | Challenge computation per block                                                       |
| `make_sub_epoch_summary.py`     | ~250  | Sub-epoch summary creation                                                            |
| `deficit.py`                    | ~55   | Deficit calculation for sub-epoch boundaries                                          |
| `multiprocess_validation.py`    | ~300  | `PreValidationResult`, parallel block validation                                      |
| `condition_tools.py`            | ~200  | `pkm_pairs()` for AGG_SIG conditions                                                  |
| `signage_point.py`              | ~10   | `SignagePoint` dataclass                                                              |
| `vdf_info_computation.py`       | ~180  | VDF info reconstruction from block records                                            |
| `default_constants.py`          | ~119  | All consensus constant values                                                         |
| `constants.py`                  | ~50   | `replace_str_to_bytes()` for config overrides                                         |

---

## `Blockchain.add_block()` — Core block acceptance

**Location**: `consensus/blockchain.py:294`

### Purpose

Single entry point for adding a validated block. Determines if a block
becomes the new peak, an orphan, or is rejected.

### Inputs & assumptions

- `block: FullBlock` — the full block to add
- `pre_validation_result: PreValidationResult` — must have valid
  `required_iters` and no error (pre-validation already ran in parallel)
- `sub_slot_iters: uint64` — pre-computed for this block's epoch
- `fork_info: ForkInfo` — must correctly describe the fork context
- **Caller holds the blockchain lock** (`priority_mutex`)
- Header validation already passed via `validate_unfinished_header_block()`

### Return

`(AddBlockResult, Err | None, StateChangeSummary | None)`

### Block-by-block logic

1. **Genesis check** (L326): `height == 0` requires `prev_header_hash ==
GENESIS_CHALLENGE`.

2. **Extending main chain?** (L331): Fast path when `prev_header_hash ==
peak.header_hash`.

3. **Disconnected block** (L337-343): If prev block not in cache →
   `DISCONNECTED_BLOCK`. Invariant: we only accept blocks connected to known
   chain.

4. **Pre-validation error** (L345-348): Reject immediately on any error.

5. **ForkInfo assertions** (L354-366): Multiple assertions verify fork_info
   consistency. Incorrect fork_info → assertion failure (crash, not silent
   corruption).

6. **Already-have-block** (L372-380): Even known blocks update fork_info
   (important for parallel batch validation).

7. **Body validation** (L392-403): `validate_block_body()` checks coins,
   merkle roots, rewards, timelocks.

8. **Block record creation** (L415-423): `block_to_block_record()` computes
   lightweight record.

9. **Atomic DB transaction** (L432-476):
   - `add_full_block()` → `_reconsider_peak()` → `add_block_record()`
   - On success: update `_peak_height` and height map
   - On failure: rollback in-memory state, fork_info, block store cache

### Invariants

- `fork_info.peak_height == block.height - 1` before body validation
- `block.height == 0 or fork_info.peak_hash == block.prev_header_hash`
- Database transaction atomicity: no partial state updates
- `_peak_height` only updated after commit

---

## `_reconsider_peak()` — Fork choice rule

**Location**: `consensus/blockchain.py:486`

### Fork choice criteria (in order)

1. Higher weight wins
2. On equal weight: lower `total_iters` wins
3. Otherwise: no change (current peak stays)

### Reorg handling

- `coin_store.rollback_to_block(fork_info.fork_height)` removes coins above
  fork point
- Replays all additions/removals from `fork_info` for the new chain
- `block_store.rollback()` clears sub-epoch summaries above fork point
- `block_store.set_in_chain()` marks new chain blocks
- `block_store.set_peak()` updates stored peak

### Assumption

`fork_info.additions_since_fork` and `fork_info.removals_since_fork` contain
ALL coin operations from `fork_height + 1` to the new peak. Incomplete data →
inconsistent coin store.

---

## `ForkInfo` — Fork tracking state

**Location**: `consensus/block_body_validation.py:62`

### Fields

- `fork_height: int` — last block shared by fork and main chain
- `peak_height: int` — height of the fork tip (-1 for genesis validation)
- `peak_hash: bytes32`
- `additions_since_fork: dict[bytes32, ForkAdd]` — all coin additions since fork
- `removals_since_fork: dict[bytes32, ForkRem]` — all coin removals since fork
- `block_hashes: list[bytes32]` — ordered header hashes from fork_height+1

### Critical methods

- `reset()` — clear all fork state (used when extending main chain)
- `update_fork_peak()` — advance peak, append header hash
- `include_spends()` — record additions/removals from `SpendBundleConditions`
- `include_reward_coins()` — record coinbase additions
- `rollback()` — undo to a previous height

### Invariant

`len(block_hashes) == peak_height - fork_height` — always.

---

## `validate_block_body()` — Block body validation

**Location**: `consensus/block_body_validation.py:190`

### Checks performed

1. Non-tx blocks: foliage_transaction_block, transactions_info, generator all None
2. Tx blocks: foliage_transaction_block and transactions_info must exist
3. `transactions_info_hash` matches foliage commitment
4. `foliage_transaction_block_hash` matches foliage commitment
5. Reward claims valid (pool + farmer coins for all blocks since last tx block)
6. Previous transaction block reference is correct
7. Timestamp: `> prev_tx_block_timestamp` and `< max_future_time`
8. Transaction filter matches additions/removals
9. Generator cost ≤ `MAX_BLOCK_COST_CLVM`
10. Generator ref list size ≤ `MAX_GENERATOR_REF_LIST_SIZE` (512)
11. Merkle roots (additions and removals) match
12. `check_time_locks()` (Rust) validates absolute/relative height/seconds
13. Fees = `sum(removals) - sum(additions)` matches declared fees
14. Coins not double-spent (checked against fork_info and coin store)
15. Additions don't collide with existing coins

---

## Difficulty adjustment

**Location**: `consensus/difficulty_adjustment.py`

### Key function: `get_next_sub_slot_iters_and_difficulty()`

Called at epoch boundaries (every `EPOCH_BLOCKS = 4608` blocks).

### Algorithm

1. Find second-to-last transaction block in previous epoch
2. Compute elapsed time between reference points
3. New difficulty = `old_difficulty × target_time / actual_time`
4. Clamp to `[old / DIFFICULTY_CHANGE_MAX_FACTOR, old × DIFFICULTY_CHANGE_MAX_FACTOR]`
   (factor = 3)
5. Truncate to `SIGNIFICANT_BITS` (8)

### Same logic applies to sub-slot iterations (SSI)

### Invariant

Difficulty and SSI can change at most 3× per epoch.

---

## VDF iteration math

**Location**: `consensus/pot_iterations.py`

### `calculate_iterations_quality(quality_string, size, difficulty, cc_sp_output_hash)`

```
sp_quality = hash(quality_string + cc_sp_output_hash)
iters = difficulty × DIFFICULTY_CONSTANT_FACTOR × sp_quality_int / (2^256 × expected_plot_size)
return max(iters, 1)
```

### `calculate_ip_iters(sub_slot_iters, signage_point_index, required_iters)`

```
ip_iters = (sp_iters + NUM_SP_INTERVALS_EXTRA × sp_interval_iters + required_iters) % sub_slot_iters
```

### `is_overflow_block(signage_point_index)`

```
overflow = signage_point_index >= NUM_SPS_SUB_SLOT - NUM_SP_INTERVALS_EXTRA
```

i.e., the last 3 signage points of a sub-slot are overflow blocks.

### Constraints

- `required_iters ∈ (0, sp_interval_iters)`
- `signage_point_index < NUM_SPS_SUB_SLOT` (64)
- `sub_slot_iters % NUM_SPS_SUB_SLOT == 0`

---

## Block rewards

**Location**: `consensus/block_rewards.py`

### Schedule (pool = 7/8, farmer = 1/8 + fees)

| Period              | Per-block reward |
| ------------------- | ---------------- |
| Height 0 (pre-farm) | 21 000 000 XCH   |
| Years 0–3           | 2 XCH            |
| Years 3–6           | 1 XCH            |
| Years 6–9           | 0.5 XCH          |
| Years 9–12          | 0.25 XCH         |
| Year 12+            | 0.125 XCH        |

`_blocks_per_year = 1 681 920` (32 × 6 × 24 × 365)

### Coinbase parent IDs

- Pool: `genesis_challenge[:16] + height.to_bytes(16)`
- Farmer: `genesis_challenge[16:] + height.to_bytes(16)`

These are deterministic, not hashed.

---

## `AugmentedBlockchain` — Parallel validation overlay

**Location**: `consensus/augmented_chain.py`

### Purpose

Wraps a `BlocksProtocol` with an in-memory cache of extra blocks. Used during
parallel batch validation: blocks in the batch aren't committed to the DB until
all pass, but subsequent blocks in the batch need to reference earlier ones.

### Key invariant

Extra blocks must form a contiguous chain. `add_extra_block()` validates that
each new block's `prev_hash` matches the last added block.

### Generator ref resolution

`lookup_block_generators()` first checks extra blocks (walking backward via
`prev_header_hash`), then falls through to the underlying blockchain.
