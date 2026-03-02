# Full Node Orchestration — Deep Context

> Attach when touching `chia/full_node/full_node.py`, `full_node_api.py`,
> `full_node_store.py`, `full_node_rpc_api.py`, sync logic, or block
> processing pipeline.

## File map

| File                       | Lines | Role                                                     |
| -------------------------- | ----- | -------------------------------------------------------- |
| `full_node.py`             | ~3400 | `FullNode`: main orchestrator, sync, block/tx processing |
| `full_node_api.py`         | ~2080 | `FullNodeAPI`: all P2P message handlers                  |
| `full_node_rpc_api.py`     | ~1170 | `FullNodeRpcApi`: HTTP/WS RPC endpoints                  |
| `full_node_rpc_client.py`  | ~380  | RPC client (used by CLI and tests)                       |
| `full_node_store.py`       | ~1060 | `FullNodeStore`: signage points, unfinished blocks       |
| `full_node_service.py`     | ~10   | Service registration                                     |
| `start_full_node.py`       | ~120  | Service startup config                                   |
| `block_store.py`           | ~700  | `BlockStore`: SQLite full block persistence              |
| `coin_store.py`            | ~680  | `CoinStore`: UTXO database                               |
| `sync_store.py`            | ~140  | `SyncStore`: sync state tracking                         |
| `weight_proof.py`          | ~1740 | `WeightProofHandler`: weight proof creation/validation   |
| `subscriptions.py`         | ~240  | `PeerSubscriptions`: wallet coin/puzzle subscriptions    |
| `hint_store.py`            | ~100  | `HintStore`: hint persistence                            |
| `hint_management.py`       | ~60   | Hint processing from conditions                          |
| `tx_processing_queue.py`   | ~250  | `TransactionQueue`: async tx processing                  |
| `check_fork_next_block.py` | ~40   | Fork-next-block utility                                  |
| `hard_fork_utils.py`       | ~55   | Hard fork flag computation                               |
| `full_block_utils.py`      | ~370  | Block ↔ header block conversion                         |
| `bundle_tools.py`          | ~20   | SpendBundle utilities                                    |

---

## `FullNode` — Main orchestrator

**Location**: `full_node/full_node.py`

### Key state

- `blockchain: Blockchain` — chain state + UTXO
- `mempool_manager: MempoolManager` — transaction pool
- `full_node_store: FullNodeStore` — signage points, unfinished blocks
- `sync_store: SyncStore` — sync state
- `full_node_peers: FullNodePeers` — peer discovery
- `weight_proof_handler: WeightProofHandler` — weight proof logic
- `subscriptions: PeerSubscriptions` — wallet subscriptions
- `_transaction_queue: TransactionQueue` — async tx processing
- `server: ChiaServer` — networking

### Key dataclass: `PeakPostProcessingResult`

After a new peak is accepted:

- `mempool_peak_added_tx_ids` — transactions re-added
- `mempool_removals` — transactions removed
- `fns_peak_result` — signage points and infusion points
- `hints` — new hints for wallet notifications
- `lookup_coin_ids` — coins to look up for wallet updates
- `signage_points` — signage points to forward to farmers after new peak

---

## Block processing pipeline

### 1. Receive block

`FullNodeAPI.respond_block()` / `FullNodeAPI.respond_blocks()` receive blocks
from peers.

### 2. Pre-validate

`pre_validate_block()` runs header validation + CLVM execution in parallel
(thread pool). Returns `PreValidationResult` with `required_iters` and
`conds`.

### 3. Add to blockchain

Under `blockchain.priority_mutex` (high priority):

- `Blockchain.add_block()` validates body, updates DB, reorgs if needed
- Returns `(AddBlockResult, Err, StateChangeSummary)`

### 4. Post-processing (peak_post_processing)

If `NEW_PEAK`:

- Update `FullNodeStore` with new signage points
- Update `MempoolManager` with `new_peak()`
- Process hints and subscriptions
- Compute wallet notifications

### 5. Broadcast

- Send `new_peak` to full node peers
- Send `new_peak_wallet` to wallet peers
- Send coin state updates to subscribed wallets
- Forward new signage points to farmer

---

## `FullNodeStore` — Signage point & unfinished block tracking

**Location**: `full_node/full_node_store.py`

### Key state

- Signage points per challenge hash (LRU-bounded)
- End-of-sub-slot bundles per challenge hash
- Unfinished blocks indexed by `(reward_hash, foliage_hash)`
- Peers that advertised each transaction (`peers_with_tx`)
- Seen compact VDFs (dedup set)

### Constants

- `MAX_UNFINISHED_BLOCKS_PER_REWARD_HASH = 20` — eviction of worst foliage

### `new_peak()` returns

- `added_eos`: any end-of-sub-slot that becomes relevant
- `new_signage_points`: signage points that can now be released
- `new_infusion_points`: infusion points for timelord

---

## Sync logic

### Weight proof sync

1. Peer announces `new_peak` with higher weight
2. Request `request_proof_of_weight` → `WeightProof`
3. Validate weight proof (sub-epoch summaries, VDF segments)
4. If valid: switch to batch download

### Batch sync

1. Download blocks in ranges via `request_blocks` (max 32 per request)
2. Pre-validate batches in parallel
3. Add blocks sequentially under blockchain lock
4. Continue until caught up to peer's peak

### Long sync detection

If peer peak is significantly ahead, enters long sync mode. During long sync,
transactions are not processed (mempool frozen).

---

## `FullNodeAPI` — P2P message handlers

**Location**: `full_node/full_node_api.py`

### Key handlers

| Handler                                              | Trigger                  | Notes                                    |
| ---------------------------------------------------- | ------------------------ | ---------------------------------------- |
| `new_peak()`                                         | Peer has new peak        | Triggers sync if heavier                 |
| `new_transaction()`                                  | Peer has new tx          | Adds to `peers_with_tx`, schedules fetch |
| `request_transaction()`                              | Peer wants a tx          | Look up in mempool                       |
| `respond_transaction()`                              | Received requested tx    | Pre-validate + add to mempool            |
| `send_transaction()`                                 | Wallet submits tx        | Pre-validate + add to mempool            |
| `respond_block()`                                    | Received single block    | Add to blockchain                        |
| `respond_blocks()`                                   | Received block batch     | Add batch to blockchain                  |
| `new_signage_point_or_end_of_sub_slot()`             | New SP/EOS               | Store + broadcast                        |
| `new_unfinished_block()` / `new_unfinished_block2()` | Farmer block             | Validate + infuse                        |
| `request_compact_vdf()`                              | Peer wants compact proof | Look up + respond                        |

### Transaction processing

`respond_transaction()` and `send_transaction()` both:

1. Check `seen_bundle_hashes` for dedup
2. Run `pre_validate_spendbundle()` in thread pool
3. Acquire blockchain lock (low priority)
4. Call `add_spend_bundle()`
5. On success: broadcast `new_transaction` to peers

---

## `FullNodeRpcApi` — RPC endpoints

**Location**: `full_node/full_node_rpc_api.py`

### Key endpoints

- `get_blockchain_state` — peak, sync status, mempool info, space estimate
- `get_block` / `get_blocks` — fetch by height or hash
- `get_block_record` / `get_block_records` — lightweight records
- `get_coin_record_by_name` — single UTXO lookup
- `get_coin_records_by_*` — batch lookups by puzzle hash, parent, hint
- `push_tx` — submit transaction (same as `send_transaction` P2P)
- `get_mempool_item_by_tx_id` — mempool query
- `get_fee_estimate` — fee estimation
- `get_network_space` — estimated network space

---

## `CoinStore` — UTXO database

**Location**: `full_node/coin_store.py`

### Schema

```sql
coin_record(
    coin_name BLOB PRIMARY KEY,
    confirmed_index BIGINT,
    spent_index BIGINT,   -- >0 spent at that height; 0 = normal unspent; -1 = FF lineage unspent
    coinbase INT,
    puzzle_hash BLOB,
    coin_parent BLOB,
    amount BLOB,          -- 8-byte uint64
    timestamp BIGINT
)
```

### Indexes

- `coin_confirmed_index` — reorg rollbacks
- `coin_spent_index` — spent coin queries
- `coin_puzzle_hash` — address lookups
- `coin_parent_index` — parent traversal
- `coin_record_ph_ff_unspent_idx` (partial, new DBs only) — FF singleton optimization

### Key operations

- `new_block()` — batch insert additions, mark removals as spent
- `rollback_to_block()` — revert coins confirmed/spent above a height
- `get_coin_records()` — fetch by coin IDs
- `get_coin_records_by_puzzle_hash()` — wallet queries
- `get_unspent_lineage_info_for_puzzle_hash()` — FF singleton lineage

---

## `BlockStore` — Full block persistence

**Location**: `full_node/block_store.py`

### Schema

- `full_blocks` table: header_hash, height, in_main_chain flag, block_record, full block bytes
- `sub_epoch_segments_v3` table: sub-epoch challenge segments for weight proofs

### Key operations

- `add_full_block()` — insert with block record
- `get_full_block()` / `get_full_blocks_at()` — fetch
- `set_in_chain()` — mark blocks as main chain
- `set_peak()` — update peak pointer
- `rollback()` — clear in_chain and sub-epoch data above height
- Transaction support via `self.db_wrapper.writer_maybe_transaction()`
