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
| [architecture-overview.md](architecture-overview.md) | Module map, actors, entrypoints, key types, `chia_rs` boundary, package root                       | Starting any unfamiliar work; first-time orientation                             |
| [consensus.md](consensus.md)                         | Block validation, difficulty adjustment, fork choice, VDF iterations, rewards, reorg contract      | Touching `chia/consensus/`, block acceptance, reorgs                             |
| [mempool.md](mempool.md)                             | Transaction admission, eviction, fee logic, conflict detection, FF/DEDUP                           | Touching `chia/full_node/mempool*.py`, `eligible_coin_spends.py`, fee estimation |
| [full-node.md](full-node.md)                         | FullNode orchestration, sync, block processing pipeline, FullNodeStore, FullNodeAPI                | Touching `chia/full_node/full_node.py`, `full_node_api.py`, `full_node_store.py` |
| [server.md](server.md)                               | WebSocket connections, rate limiting, peer discovery, TLS, address-manager behavior                | Touching `chia/server/`, connection handling                                     |
| [protocols.md](protocols.md)                         | Wire protocol message schemas, numeric IDs, sender authorization, reply maps, capabilities         | Touching `chia/protocols/`, message definitions                                  |
| [apis.md](apis.md)                                   | API stub metadata, request/reply declarations, protocol-visible method names                       | Touching `chia/apis/*_stub.py`, API decorators                                   |
| [types.md](types.md)                                 | Shared blockchain-format types, CLVM `Program` helpers, `Coin`/condition contracts, Rust boundary  | Touching `chia/types/`, serialization compatibility                              |
| [wallet.md](wallet.md)                               | Coin selection, wallet state manager, wallet node sync, sub-wallets, persistence, offers           | Touching `chia/wallet/`                                                          |
| [clvm-execution.md](clvm-execution.md)               | CLVM execution paths, resource limits, canonical serialization, generator resolution, AGG_SIG      | Touching puzzle execution, spend validation, generator logic                     |
| [farmer.md](farmer.md)                               | Farmer proof flow, pool partial submission, reward targets, plot-sync receiver, solver management  | Touching `chia/farmer/`                                                          |
| [harvester.md](harvester.md)                         | Plot file management, PoS lookups, signage-point filter, plot sync                                 | Touching `chia/harvester/`                                                       |
| [timelord.md](timelord.md)                           | VDF scheduling, peak/unfinished-block selection, compact proof production                          | Touching `chia/timelord/`                                                        |
| [plotting.md](plotting.md)                           | Plot creation, plot format, plot keys                                                              | Touching `chia/plotting/`                                                        |
| [plot-sync.md](plot-sync.md)                         | Plot sync protocol, delta sync, sender/receiver state                                              | Touching `chia/plot_sync/`                                                       |
| [pools.md](pools.md)                                 | Pool NFT / pool singleton state, pool wallet transitions, pool protocol payloads                   | Touching `chia/pools/`                                                           |
| [daemon.md](daemon.md)                               | Daemon routing, keychain/process authority, service launch                                         | Touching `chia/daemon/`                                                          |
| [data-layer.md](data-layer.md)                       | DataLayer store mutations, root publication, mirror sync, proof verification                       | Touching `chia/data_layer/`                                                      |
| [rpc.md](rpc.md)                                     | RPC transport, error shapes, daemon websocket envelopes                                            | Touching `chia/rpc/`                                                             |
| [ssl.md](ssl.md)                                     | Certificate generation, public/private CA material, SSL file permissions                           | Touching `chia/ssl/`                                                             |
| [simulator.md](simulator.md)                         | Simulator block farming, reorg/revert helpers, BlockTools, service test harnesses                  | Touching `chia/simulator/`                                                       |
| [solver.md](solver.md)                               | V2 plot partial proof solving, solver service, farmer coupling                                     | Touching `chia/solver/`                                                          |
| [seeder.md](seeder.md)                               | Crawler peer discovery, DNS seed responses, bootstrap-peer publication                             | Touching `chia/seeder/`                                                          |
| [introducer.md](introducer.md)                       | Introducer peer collection, TCP vetting, DNS fallback                                              | Touching `chia/introducer/`                                                      |
| [cmds.md](cmds.md)                                   | CLI command handlers, service start/stop wiring                                                    | Touching `chia/cmds/`                                                            |
| [util.md](util.md)                                   | DB wrapper, streamable, keychain, bech32m, error enum, config, caching                             | Touching `chia/util/`                                                            |
| [benchmarks.md](benchmarks.md)                       | Benchmark harness, benchmark scripts, performance measurement                                      | Touching `benchmarks/`                                                           |
| [repo-tooling.md](repo-tooling.md)                   | Packaging, install scripts, CI workflows, build/release, GUI submodule, developer tools            | Touching root config, `build_scripts/`, `.github/`, `tools/`, install scripts    |
| [global-invariants.md](global-invariants.md)         | Cross-module invariants, state dependencies, trust boundaries, workflow traces, fragility clusters | Cross-cutting changes, security review, reorg-related work                       |

---

## Test guidance

Test harness selection and patterns live under `.cursor/context/testing/` and
are routed by `.cursor/rules/testing-guide.mdc`. Read that rule when working in
`chia/_tests/`.

| File                                                   | Covers                                                       |
| ------------------------------------------------------ | ------------------------------------------------------------ |
| [testing/architecture.md](testing/architecture.md)     | Test architecture, consensus modes, fixture authority, CI    |
| [testing/patterns.md](testing/patterns.md)             | Block creation, transaction submission, assertion patterns   |
| [testing/blockchain.md](testing/blockchain.md)         | Consensus/blockchain tests, reorg, overflow, fork invariants |
| [testing/full-node.md](testing/full-node.md)           | Full node sync, propagation, mempool-to-block, reorg tests   |
| [testing/mempool.md](testing/mempool.md)               | Mempool acceptance/rejection, replacement, eviction          |
| [testing/data-layer.md](testing/data-layer.md)         | DataStore logic, wallet-backed RPC, singleton lifecycle      |
| [testing/server.md](testing/server.md)                 | Connection lifecycle, API errors, DoS/ban, rate limiting     |
| [testing/wallet.md](testing/wallet.md)                 | Wallet fixtures, `wallet_environments`, wallet RPC tests     |
| [testing/clvm.md](testing/clvm.md)                     | Direct CLVM execution vs SpendSim                            |
| [testing/cmds.md](testing/cmds.md)                     | CLI harness, mock RPC boundaries                             |
| [testing/infrastructure.md](testing/infrastructure.md) | Shared harness, setup_nodes, SpendSim, convergence helpers   |
| [testing/service-wiring.md](testing/service-wiring.md) | Cross-subsystem service setup, async test layering           |

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
