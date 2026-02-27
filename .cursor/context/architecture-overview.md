# Architecture Overview

> Attach this file when starting unfamiliar work or needing first-time
> orientation on the chia-blockchain codebase.

## Project shape

Python PoST blockchain. Core runtime is `chia/`, with `chia_rs` (Rust FFI)
handling performance-critical consensus, BLS signatures, CLVM execution, and
serialization.

## Module map

| Module             | Purpose                                                              | Criticality  |
| ------------------ | -------------------------------------------------------------------- | ------------ |
| `chia/consensus/`  | Block validation, difficulty, fork choice, VDF iters, rewards        | **Critical** |
| `chia/full_node/`  | Full node state, mempool, stores, fee estimation, weight proofs, RPC | **Critical** |
| `chia/server/`     | Networking: WebSocket, rate limiting, peer discovery, TLS            | **Critical** |
| `chia/protocols/`  | Wire protocol message definitions between all node types             | **Critical** |
| `chia/wallet/`     | Wallet state, coin selection, spend construction, sub-wallets        | **High**     |
| `chia/farmer/`     | Farming logic, signage point handling, proof forwarding              | **High**     |
| `chia/harvester/`  | Plot file management, PoS lookups                                    | **Medium**   |
| `chia/timelord/`   | VDF computation, infusion point management                           | **High**     |
| `chia/types/`      | Type definitions: blockchain format, mempool items, generators       | **High**     |
| `chia/util/`       | DB wrapper, streamable, keychain, bech32m, etc.                      | **Medium**   |
| `chia/simulator/`  | Test blockchain simulator                                            | Low          |
| `chia/data_layer/` | DataLayer (data-storage singleton)                                   | Medium       |
| `chia/cmds/`       | CLI command handlers                                                 | Low          |

## `chia_rs` boundary

Nearly all core consensus types live in Rust:

**Types**: `BlockRecord`, `FullBlock`, `ConsensusConstants`, `SpendBundleConditions`,
`CoinRecord`, `SpendBundle`, `EndOfSubSlotBundle`, `HeaderBlock`, `UnfinishedBlock`,
`SubEpochSummary`, `SubEpochChallengeSegment`, `Coin`, `CoinSpend`, `G1Element`,
`G2Element`, `AugSchemeMPL`, `BLSCache`.

**Functions**: `validate_clvm_and_signature`, `run_block_generator`,
`run_block_generator2`, `additions_and_removals`, `check_time_locks`,
`compute_merkle_set_root`, `fast_forward_singleton`, `supports_fast_forward`,
`get_flags_for_height_and_constants`, `solution_generator_backrefs`,
`get_puzzle_and_solution_for_coin2`, `is_canonical_serialization`,
`get_conditions_from_spendbundle`, `get_spends_for_trusted_block`.

**Rule of thumb**: Consensus-critical _math_ (VDF iteration calculation, difficulty
adjustment, quality computation) is Python. Signature/CLVM/serialization
validation is Rust.

## Actors

### Full Node (central)

- **P2P API**: `FullNodeAPI` in `full_node_api.py` (~2080 lines)
- **RPC API**: `FullNodeRpcApi` in `full_node_rpc_api.py` (~1170 lines)
- **State machine**: `FullNode` in `full_node.py` (~3400 lines)

### Farmer

- **API**: `FarmerAPI` in `farmer_api.py` — receives signage points, forwards proofs
- **RPC**: `FarmerRpcApi` — local management

### Harvester

- **API**: `HarvesterAPI` in `harvester_api.py` — receives challenges, checks plots

### Timelord

- **API**: `TimelordAPI` in `timelord_api.py` — receives peaks, produces VDFs
- **State**: `TimelordState` in `timelord_state.py`

### Wallet

- **P2P**: `WalletNodeAPI` in `wallet_node_api.py` — coin state updates
- **RPC**: `WalletRpcApi` in `wallet_rpc_api.py` (~158K) — full wallet surface
- **State**: `WalletStateManager` in `wallet_state_manager.py` (~167K)

## Wire protocol overview

147 message types in `ProtocolMessageTypes` enum. Key flows:

- **Full Node ↔ Full Node**: `new_peak`, `new_transaction`, `request_block(s)`,
  `new_signage_point_or_end_of_sub_slot`, `request_compact_vdf`
- **Full Node ↔ Wallet**: `new_peak_wallet`, `send_transaction`,
  `coin_state_update`, `request_puzzle_state`, `mempool_items_added/removed`
- **Farmer ↔ Full Node**: `new_signage_point`, `declare_proof_of_space`,
  `request_signed_values`
- **Farmer ↔ Harvester**: `new_signage_point_harvester`, `new_proof_of_space`,
  `request_signatures`
- **Full Node ↔ Timelord**: `new_peak_timelord`, `new_infusion_point_vdf`,
  `new_signage_point_vdf`

## Key type files

| File                                                 | Contents                                               |
| ---------------------------------------------------- | ------------------------------------------------------ |
| `chia/types/blockchain_format/coin.py`               | `Coin` (parent_id, puzzle_hash, amount)                |
| `chia/types/blockchain_format/vdf.py`                | `VDFInfo`, `VDFProof`                                  |
| `chia/types/blockchain_format/proof_of_space.py`     | PoS verification                                       |
| `chia/types/blockchain_format/program.py`            | CLVM program wrappers                                  |
| `chia/types/blockchain_format/serialized_program.py` | Lazy CLVM deserialization                              |
| `chia/types/mempool_item.py`                         | `MempoolItem`, `BundleCoinSpend`, `UnspentLineageInfo` |
| `chia/types/generator_types.py`                      | `BlockGenerator`, `NewBlockGenerator`                  |
| `chia/types/validation_state.py`                     | `ValidationState`                                      |
| `chia/types/weight_proof.py`                         | `WeightProof`                                          |
| `chia/consensus/block_record.py`                     | Re-export of `BlockRecord` from chia_rs                |
| `chia/consensus/default_constants.py`                | `DEFAULT_CONSTANTS` with all parameter values          |
