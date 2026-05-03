# Chia Blockchain — Deep Context Index

> Generated from deep context-building pass. Each subsystem file is
> self-contained: pull only the file(s) relevant to the code you're touching.

## How to use

1. Read **this file** first for orientation.
2. Attach the subsystem file(s) that cover the code you're working on.
3. If your change crosses subsystem boundaries, also attach
   `global-invariants.md` — it documents the contracts between modules.

---

## Subsystem files

| File                                                 | Covers                                                                                             | When to attach                                                                   |
| ---------------------------------------------------- | -------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------- |
| [architecture-overview.md](architecture-overview.md) | Module map, actors, entrypoints, key types, `chia_rs` boundary                                     | Starting any unfamiliar work; first-time orientation                             |
| [consensus.md](consensus.md)                         | Block validation, difficulty adjustment, fork choice, VDF iterations, rewards                      | Touching `chia/consensus/`, block acceptance, reorgs                             |
| [mempool.md](mempool.md)                             | Transaction admission, eviction, fee logic, conflict detection, FF/DEDUP                           | Touching `chia/full_node/mempool*.py`, `eligible_coin_spends.py`, fee estimation |
| [full-node.md](full-node.md)                         | FullNode orchestration, sync, block processing pipeline, FullNodeStore, FullNodeAPI                | Touching `chia/full_node/full_node.py`, `full_node_api.py`, `full_node_store.py` |
| [networking.md](networking.md)                       | WebSocket connections, rate limiting, peer discovery, protocol state machine                       | Touching `chia/server/`, `chia/protocols/`, connection handling                  |
| [wallet.md](wallet.md)                               | Coin selection, wallet state manager, wallet node sync, sub-wallets                                | Touching `chia/wallet/`                                                          |
| [clvm-execution.md](clvm-execution.md)               | CLVM execution, condition processing, canonical serialization, cost metering                       | Touching puzzle execution, spend validation, generator logic                     |
| [global-invariants.md](global-invariants.md)         | Cross-module invariants, state dependencies, trust boundaries, workflow traces, fragility clusters | Cross-cutting changes, security review, reorg-related work                       |

---

## Quick reference — key files by size/complexity

| File                                        | Lines | Role                              |
| ------------------------------------------- | ----- | --------------------------------- |
| `chia/full_node/full_node.py`               | ~3400 | Main orchestrator                 |
| `chia/wallet/wallet_state_manager.py`       | ~3330 | Wallet state                      |
| `chia/wallet/wallet_rpc_api.py`             | ~3610 | Wallet RPC surface                |
| `chia/full_node/full_node_api.py`           | ~2080 | P2P message handlers              |
| `chia/full_node/full_node_rpc_api.py`       | ~1170 | Full node RPC                     |
| `chia/consensus/blockchain.py`              | ~1090 | Chain state + add_block           |
| `chia/consensus/block_header_validation.py` | ~1060 | Header checks                     |
| `chia/full_node/weight_proof.py`            | ~1740 | Weight proof validation           |
| `chia/full_node/mempool_manager.py`         | ~1160 | Mempool admission                 |
| `chia/full_node/mempool.py`                 | ~810  | Mempool data structure            |
| `chia/consensus/block_body_validation.py`   | ~580  | Body checks                       |
| `chia/consensus/difficulty_adjustment.py`   | ~410  | Difficulty/SSI                    |
| `chia/full_node/coin_store.py`              | ~680  | UTXO database                     |
| `chia/full_node/full_node_store.py`         | ~1060 | Signage points, unfinished blocks |

---

## Consensus constants cheat-sheet

| Constant                       | Value          | Note                       |
| ------------------------------ | -------------- | -------------------------- |
| `SLOT_BLOCKS_TARGET`           | 32             | Target blocks / sub-slot   |
| `NUM_SPS_SUB_SLOT`             | 64             | Signage points / sub-slot  |
| `SUB_SLOT_TIME_TARGET`         | 600 s          | ~10 min / sub-slot         |
| `EPOCH_BLOCKS`                 | 4608           | Blocks / difficulty epoch  |
| `SUB_EPOCH_BLOCKS`             | 384            | Blocks / sub-epoch         |
| `MAX_BLOCK_COST_CLVM`          | 11 000 000 000 | Max CLVM cost / block      |
| `COST_PER_BYTE`                | 12 000         | Generator byte cost        |
| `MAX_BLOCK_COUNT_PER_REQUESTS` | 32             | Max blocks / P2P request   |
| `DIFFICULTY_CHANGE_MAX_FACTOR` | 3              | Max epoch difficulty ratio |
| `MAX_FUTURE_TIME2`             | 120 s          | Max timestamp drift        |
| `HARD_FORK_HEIGHT`             | 5 496 000      | June 2024 hard fork        |
| `MEMPOOL_BLOCK_BUFFER`         | 10             | Mempool = 10× block cost   |
