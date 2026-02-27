# Global Invariants, Workflows & Trust Boundaries

> Attach for cross-cutting changes, security review, reorg-related work,
> or when your change touches multiple subsystems.

---

## Global invariants

### 1. Weight monotonicity (fork choice)

Peak always has the heaviest weight. Equal weight resolves by lower
`total_iters`. This is enforced in `Blockchain._reconsider_peak()`.

### 2. Coin uniqueness

Each coin ID exists at most once in the UTXO set. Double-spends are rejected
at both mempool admission and block validation.

### 3. Conservation of value

`sum(removals) >= sum(additions)` for every transaction. The difference is
fees. Enforced in `validate_block_body()` and `MempoolManager.validate_spend_bundle()`.

### 4. Block cost bound

Every block's CLVM cost ≤ `MAX_BLOCK_COST_CLVM` (11 000 000 000).
Every mempool item's cost ≤ `MAX_BLOCK_COST_CLVM / 2`.

### 5. Timestamp ordering

For transaction blocks, timestamps must be:

- Strictly greater than the previous transaction block timestamp
- At most `now + MAX_FUTURE_TIME2` (120 seconds)

### 6. Difficulty bounds

Next difficulty is clamped to `[prev / DIFFICULTY_CHANGE_MAX_FACTOR, prev × DIFFICULTY_CHANGE_MAX_FACTOR]`
where factor = 3. Same applies to sub-slot iterations.

### 7. Reward schedule

Pool gets 7/8 of block reward, farmer gets 1/8 + fees.
Halving every 3 years (~1 681 920 blocks). Pre-farm at height 0.

### 8. Signage point ordering

`signage_point_index < NUM_SPS_SUB_SLOT` (64). Overflow blocks use the
last `NUM_SP_INTERVALS_EXTRA` (3) indices.

### 9. Sub-slot iteration divisibility

`sub_slot_iters % NUM_SPS_SUB_SLOT == 0` — always. Enforced by the
starting value and adjustment algorithm.

### 10. Fork info consistency

During block validation:

- `fork_info.peak_height == block.height - 1`
- `block.height == 0 or fork_info.peak_hash == block.prev_header_hash`
- `len(fork_info.block_hashes) == fork_info.peak_height - fork_info.fork_height`

---

## Cross-module state dependencies

| State                | Written by                          | Read by                                             | Consistency rule                           |
| -------------------- | ----------------------------------- | --------------------------------------------------- | ------------------------------------------ |
| `coin_record` table  | `Blockchain._reconsider_peak()`     | `MempoolManager`, `FullNodeRpcApi`, wallet protocol | Matches current peak chain                 |
| `_peak_height`       | `Blockchain.add_block()`            | All full node components                            | Only updated after DB commit               |
| `mempool._items`     | `MempoolManager.add_spend_bundle()` | Block creation, RPC, TX relay                       | All items valid at current peak            |
| `fork_info`          | `Blockchain.add_block()`            | `validate_block_body()`                             | Contains all adds/removes since fork point |
| `seen_bundle_hashes` | `MempoolManager`                    | `FullNodeAPI.new_transaction()`                     | Prevents re-processing                     |
| `block_store.peak`   | `block_store.set_peak()`            | `Blockchain._load_chain_from_store()`               | Matches `_peak_height`                     |
| `height_map`         | `Blockchain.add_block()`            | Height lookups throughout                           | Matches chain up to peak                   |
| `PeerSubscriptions`  | `FullNodeAPI` register handlers     | `FullNode.peak_post_processing_2()`                 | Wallet notifications                       |

---

## Trust boundary map

| Boundary                              | Trust level                 | Protection                                                                          |
| ------------------------------------- | --------------------------- | ----------------------------------------------------------------------------------- |
| P2P messages from peers               | **Untrusted**               | Streamable deserialization, rate limiting, protocol state machine, ban on violation |
| RPC from localhost                    | **Semi-trusted**            | TLS client cert required, inputs validated                                          |
| Farmer → Full Node                    | **Semi-trusted**            | Proofs cryptographically verified, signatures validated                             |
| Harvester → Farmer                    | **Trusted** (same operator) | Minimal validation                                                                  |
| CLVM execution (arbitrary puzzles)    | **Untrusted**               | Sandboxed in Rust, cost-metered, atom/pair count bounded                            |
| Block generators                      | **Untrusted**               | Cost limits, ref list size capped (512)                                             |
| Weight proofs                         | **Untrusted**               | Full VDF verification, sub-epoch summary validation                                 |
| Wallet → Full Node (send_transaction) | **Untrusted**               | Full mempool validation pipeline                                                    |

---

## Key workflow traces

### Block production

```
Timelord → new_signage_point_vdf → FullNode
FullNode → new_signage_point → Farmer
Farmer → new_signage_point_harvester → Harvester
Harvester → new_proof_of_space → Farmer
Farmer → declare_proof_of_space → FullNode
FullNode creates unfinished block (mempool txs included)
Timelord → new_infusion_point_vdf → FullNode
FullNode creates finished block → add_block() → broadcasts new_peak
```

### Transaction lifecycle

```
Wallet → send_transaction → FullNode
FullNode: pre_validate_spendbundle() [thread pool, CLVM + BLS]
FullNode: add_spend_bundle() [under blockchain lock]
  → validate_spend_bundle() → check coins, fees, conflicts, timelocks
  → if SUCCESS: add to mempool, broadcast new_transaction
  → if PENDING: add to conflict/pending cache
  → if FAILED: return error

Peer receives new_transaction → request_transaction → respond_transaction
  → same validation pipeline

At block creation:
  mempool.create_block_generator2() → ordered by fee/cost → block generator
```

### Sync

```
Peer → new_peak (heavier) → FullNode
FullNode → request_proof_of_weight → Peer → respond_proof_of_weight
FullNode validates weight proof
FullNode → request_blocks (batches of 32) → Peer → respond_blocks
FullNode: pre_validate batches [parallel]
FullNode: add_block() [sequential, under lock]
Repeat until caught up
```

### Reorg

```
Receive block on fork with higher weight
Blockchain._reconsider_peak() detects weight > current peak
coin_store.rollback_to_block(fork_height)
Replay additions/removals from fork_info
Update peak, height map, block store
MempoolManager.new_peak() — re-validate mempool items
Broadcast new_peak to peers and wallets
```

---

## Concurrency model

### Blockchain lock (`priority_mutex`)

- **High priority**: Block validation and addition
- **Low priority**: Transaction processing (mempool)
- Blocks are never starved by transactions

### Thread pools

- `Blockchain.pool`: Block validation (CLVM execution)
- `MempoolManager.pool`: Spend bundle validation (2 workers)
- Both use `ThreadPoolExecutor`

### Async coordination

- `asyncio.Lock` for compact proof dedup
- `TransactionQueue` for async transaction processing
- `LimitedSemaphore` for concurrent block requests

---

## Fragility clusters

### 1. `FullNode` (~3400 lines)

Massive orchestration class. Sync, block processing, transaction handling,
peer management all interleaved. High coupling, hard to reason about
independently.

### 2. Fork handling in `ForkInfo`

Complex state tracking. `include_spends()` / `include_block()` / `rollback()`
must be called in exact sequence. Assertion-heavy (crashes on inconsistency).

### 3. Mempool FF/DEDUP logic

`eligible_coin_spends.py` + `check_removals()` + `new_peak()` FF rebase.
Multiple code paths for singleton chaining with subtle conflict resolution
rules.

### 4. Weight proof validation (~1740 lines)

Dense validation of compressed chain proofs. Many edge cases around
sub-epoch boundaries, VDF segment matching, and difficulty transitions.

### 5. Block header validation (~1060 lines)

~30+ numbered checks with complex interdependencies. VDF validation,
signage point verification, challenge computation. Ordering matters.

### 6. Difficulty adjustment

Complex epoch/sub-epoch boundary detection with lookback across multiple
block types (transaction vs non-transaction).

---

## Hard fork boundaries

| Fork                     | Height     | What changed                                                       |
| ------------------------ | ---------- | ------------------------------------------------------------------ |
| `HARD_FORK_HEIGHT`       | 5 496 000  | June 2024 — condition set changes, CLVM flags                      |
| `HARD_FORK2_HEIGHT`      | 0xFFFFFFFA | Placeholder sentinel for v2 plots; real height is network-specific |
| `SOFT_FORK8_HEIGHT`      | 8 655 000  | Soft fork conditions                                               |
| `PLOT_FILTER_128_HEIGHT` | 10 542 000 | June 2027 — plot filter reduction                                  |
| `PLOT_FILTER_64_HEIGHT`  | 15 592 000 | June 2030                                                          |
| `PLOT_FILTER_32_HEIGHT`  | 20 643 000 | June 2033                                                          |

Heights are checked via `get_flags_for_height_and_constants()` which returns
the appropriate flag set for CLVM execution at a given height.
