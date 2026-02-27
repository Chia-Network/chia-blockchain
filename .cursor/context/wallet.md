# Wallet Layer — Deep Context

> Attach when touching `chia/wallet/`.

## File map (top-level)

| File                             | Lines | Role                                                  |
| -------------------------------- | ----- | ----------------------------------------------------- |
| `wallet_state_manager.py`        | ~167K | `WalletStateManager`: all wallet state, coin tracking |
| `wallet_rpc_api.py`              | ~158K | `WalletRpcApi`: full wallet RPC surface               |
| `wallet_rpc_client.py`           | ~41K  | RPC client for CLI/tests                              |
| `wallet_node.py`                 | ~85K  | `WalletNode`: SPV sync, peer communication            |
| `wallet_node_api.py`             | ~9K   | P2P message handlers                                  |
| `wallet.py`                      | ~30K  | `Wallet`: standard XCH wallet logic                   |
| `wallet_blockchain.py`           | ~12K  | Lightweight chain tracking for wallet                 |
| `conditions.py`                  | ~53K  | Condition parsing and construction                    |
| `coin_selection.py`              | ~8.5K | Coin selection algorithm                              |
| `trade_manager.py`               | ~51K  | Offer/trade management                                |
| `wallet_request_types.py`        | ~76K  | RPC request type definitions                          |
| `wallet_coin_store.py`           | ~16K  | Wallet-side coin persistence                          |
| `wallet_transaction_store.py`    | ~22K  | Transaction record persistence                        |
| `wallet_puzzle_store.py`         | ~16K  | Derivation/puzzle hash store                          |
| `wallet_weight_proof_handler.py` | ~5K   | Weight proof handling for wallet                      |
| `notification_manager.py`        | ~5K   | Notification handling                                 |
| `wallet_action_scope.py`         | ~7K   | Action scope for atomic operations                    |
| `derive_keys.py`                 | ~5K   | Key derivation                                        |
| `singleton.py`                   | ~4K   | Singleton utilities                                   |
| `wallet_coin_record.py`          | ~3K   | `WalletCoinRecord` type                               |
| `transaction_record.py`          | ~4K   | `TransactionRecord` type                              |
| `start_wallet.py`                | ~4K   | Service startup                                       |

## Sub-wallet modules

| Directory     | Purpose                                         |
| ------------- | ----------------------------------------------- |
| `cat_wallet/` | Chia Asset Token (CAT) wallet                   |
| `did_wallet/` | Decentralized Identity wallet                   |
| `nft_wallet/` | NFT wallet                                      |
| `vc_wallet/`  | Verifiable Credentials wallet                   |
| `db_wallet/`  | DataLayer wallet                                |
| `trading/`    | Offer trading utilities                         |
| `puzzles/`    | CLVM puzzle definitions                         |
| `util/`       | Wallet utilities, tx config, puzzle compression |

---

## Coin selection

**Location**: `wallet/coin_selection.py`

### `select_coins(spendable_amount, config, spendable_coins, unconfirmed_removals, log, amount)`

1. **Filter**: Remove unconfirmed removals, excluded coin IDs/amounts,
   coins outside min/max amount bounds
2. **Max coins**: 500 per selection
3. **Insufficiency check**: If filtered coins sum < amount → raise ValueError
4. **Algorithm**: Greedy selection from largest to smallest, with
   randomization to avoid deterministic patterns

### `CoinSelectionConfig` fields

- `min_coin_amount`, `max_coin_amount`
- `excluded_coin_ids: set[bytes32]`
- `excluded_coin_amounts: set[uint64]`

---

## Wallet sync model

**Location**: `wallet/wallet_node.py`

### Sync flow

1. Receive `new_peak_wallet` from full node
2. If behind: request weight proof → validate
3. Subscribe to puzzle hashes via `register_for_ph_updates`
4. Subscribe to coin IDs via `register_for_coin_updates`
5. Receive `coin_state_update` pushes for subscribed items
6. Process coin state changes → update local wallet DB

### Mempool tracking (if capability supported)

- Receive `mempool_items_added` / `mempool_items_removed`
- Track pending transactions in mempool

### Trust model

- **Trusted mode**: Connected to own full node, skip weight proof verification
- **Untrusted mode**: Full weight proof validation required

---

## Wallet state manager

**Location**: `wallet/wallet_state_manager.py`

### Responsibilities

- Key management and derivation
- Coin record tracking (confirmed/unconfirmed/pending)
- Transaction creation and signing
- Sub-wallet registry and lifecycle
- Puzzle hash generation and caching
- Action scope management for atomic multi-step operations

### Key state

- `puzzle_store: WalletPuzzleStore` — derivation indexes and puzzle hashes
- `coin_store: WalletCoinStore` — wallet-side coin records
- `tx_store: WalletTransactionStore` — transaction history
- `user_store: WalletUserStore` — sub-wallet metadata
- `interested_store: WalletInterestedStore` — tracked coin/puzzle IDs

### Sub-wallet types

Each sub-wallet type handles its own puzzle construction, spend creation,
and coin tracking:

- Standard wallet (XCH)
- CAT wallet (fungible tokens)
- DID wallet (identity)
- NFT wallet (non-fungible tokens)
- DataLayer wallet
- VC wallet (verifiable credentials)

---

## Transaction construction

### General flow

1. Select coins via `coin_selection.py`
2. Construct puzzle reveals and solutions
3. Create `CoinSpend` objects
4. Aggregate into `SpendBundle`
5. Sign with BLS keys
6. Submit via `send_transaction` to full node

### `WalletActionScope`

Provides atomic operation scope for multi-step wallet operations.
Tracks additions, removals, and intermediate state. On failure,
all changes can be rolled back.

---

## Wallet RPC surface

**Location**: `wallet/wallet_rpc_api.py`

The wallet RPC is the largest single file in the codebase (~158K).
Key endpoint categories:

- **Key management**: `log_in`, `get_public_keys`, `generate_mnemonic`
- **Wallet info**: `get_wallets`, `get_wallet_balance`, `get_sync_status`
- **Transactions**: `send_transaction`, `get_transactions`, `delete_unconfirmed_transactions`
- **Coin management**: `get_spendable_coins`, `select_coins`, `get_coin_records_by_names`
- **CAT**: `cat_spend`, `cat_get_asset_id`, `create_new_cat_wallet`
- **NFT**: `nft_mint_nft`, `nft_transfer_nft`, `nft_get_nfts`
- **DID**: `did_create_attest`, `did_update_recovery_ids`
- **Offers**: `create_offer_for_ids`, `take_offer`, `get_all_offers`
- **DataLayer**: `dl_*` endpoints
- **Fee estimation**: `get_fee_estimate`

---

## Wallet blockchain

**Location**: `wallet/wallet_blockchain.py`

Lightweight chain state for the wallet. Tracks:

- Peak height and header hash
- Sub-epoch summaries (for weight proof validation)
- Does NOT store full blocks — only enough for sync verification
