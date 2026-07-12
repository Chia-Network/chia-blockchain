# Chia Tests Integration Context

Verified: 2026-07-12 against a5647a9327e5. If source contradicts this doc, trust source and update the doc.

Scope: integration and cross-subsystem tests under `chia/_tests/core/**` plus service/test buckets such as `farmer_harvester`, `harvester`, `plot_sync`, `plotting`, `pools`, `rpc`, `simulation`, `solver`, `timelord`, `tools`, `weight_proof`, DB/generator/fee-estimation, and environment wrappers.

## When To Read This

Read this when a test crosses real services, simulator/full-node/wallet lifecycles, protocol wiring, RPC transport, DataLayer singleton publication, farmer/harvester/solver/timelord flows, plot inventory, or weight-proof/timelord fixture behavior. For shared fixture semantics, also read `testing/architecture.md` and `testing/infrastructure.md`.

## Harness Boundaries

- Shared fixtures in `chia/_tests/conftest.py` define consensus modes, `BlockTools`, persistent chains, simulator/full-node/wallet topologies, keyring isolation, database versions, and localhost assumptions.
- Use deterministic `BlockTools.get_consecutive_blocks()` or persistent chains when exact block structure, fork shape, generator output, weight proofs, or iteration math is under test.
- Use `FullNodeSimulator` farming APIs when exact block anatomy is irrelevant and the behavior is mempool inclusion, confirmation, wallet sync, DataLayer update, or RPC-visible state.
- Use real multi-node fixtures (`two_nodes`, `three_nodes`, `five_nodes`) only when peer protocol, sync, weight proof, connection state, or non-simulator full-node behavior matters.
- Use in-memory production stores when the contract is production state mutation without peer networking. Full-node store/blockchain invariants do not always need simulator or socket setup.
- Use isolated unit-style harnesses for `RateLimiter`, streamable/list-limit metadata, DB wrapper semantics, generator/serialization helpers, fee bucket math, config/keyring helpers, Merkle/filter utilities, and pure DataStore behavior.
- Service-backed farmer/harvester/solver/timelord/pool tests intentionally use real services and protocol APIs. Mocks are mostly for targeted negative paths.

## Behavioral Clusters

- Full-node sync tests validate weight-proof selection, batch vs long sync, fork-point discovery, bad-peak caching, peer disconnects, and reorg catch-up. Assert height convergence and sync-mode transitions separately.
- Mempool tests check canonical CLVM parsing, coin lookup, timelocks, fee/cost thresholds, replacement, pending/conflict caches, FF singleton rebasing, DEDUP behavior, block-generator selection, and exact `MempoolInclusionStatus`/`Err` pairs.
- Server/protocol tests cover handshake compatibility, `ApiError` transport, request/reply state-machine behavior, duplicate connections, stale closed connections, ban exemptions, oversized messages, and capability-gated rate limits.
- DataLayer tests split pure Merkle/data-store invariants from chain-backed RPC/client/function/CLI parity and wallet-confirmed singleton/update lifecycles.
- Daemon and service tests validate local admin/process boundaries: websocket registration, keychain proxy compatibility, service launch/termination, RPC health, signal handling, and config-root isolation. Do not apply P2P message/rate-limit assumptions to daemon JSON traffic.
- Farmer/harvester tests cover keychain startup, handshakes, signage-point accounting, invalid signature responses, protocol version compatibility, pool partial accounting, filter-prefix behavior, and V2 partial-proof forwarding to solvers.
- Plotting and plot-sync tests protect local plot authority plus the harvester-to-farmer inventory state machine: refresh timing, invalid/no-key/duplicate quarantine, symlink/recursive options, `(sync_id, message_id)` ordering, dropped/delayed/duplicated responses, reset/retry, and final `done` commit.
- Pool tests span config/CLI parsing, CLVM pool puzzle lifecycle, wallet pool store persistence, `plotnft` commands, singleton identity, trusted/untrusted wallet sync, transaction confirmation, and reorg/revert behavior.
- Timelord and weight-proof tests rely on persistent block fixtures, sub-epoch summaries, real iteration data, and consensus-mode-specific skips. Treat those skips as coupling signals.
- RPC transport tests preserve response shape, structured errors, TLS/no-TLS behavior, websocket handling, and malformed-input safety separately from product endpoint semantics.

## Cross-Subsystem Assumptions

- Wallet, pool, and DataLayer tests need visible phases: wallet action/RPC creates transactions, full node accepts them into mempool, simulator farming confirms them, wallet sync observes confirmation, and config/store state persists.
- Chain state assertions depend on `Blockchain`, `BlockStore`, `CoinStore`, `FullNodeStore`, and `MempoolManager` staying in lockstep. A passing RPC response can still be wrong if it reads a fork block as canonical or mempool state against the wrong transaction peak.
- Farmer proof flow is correlation-heavy. `sps`, `proofs_of_space`, `quality_str_to_identifiers`, `number_of_responses`, `cache_add_time`, and `pending_solver_requests` must agree across async harvester, full-node, pool, and solver messages.
- DB wrapper behavior underpins full-node, wallet, and DataLayer stores. Reader transaction visibility, WAL mode, savepoint rollback, and foreign-key delay semantics are infrastructure contracts.
- RPC structured error tests intentionally preserve both legacy `error` strings and newer `structuredError` payloads.
- Directory config files affect runtime shape. Moving tests between core subdirectories can change checked-out blocks/plots, parallelism, CI timeout behavior, and consensus-mode coverage.

## Flake And Review Signals

- Prefer `time_out_assert()` and domain wait helpers over raw `asyncio.sleep()` for handshakes, mempool entry, wallet sync, plot sync, peer tables, logs, and RPC-visible state.
- Keep async workflows layered: immediate response shape, eventual service/peer state, mempool or plot-sync convergence, block confirmation, wallet/RPC sync, and persisted config/store state are separate facts.
- Negative-path tests should assert the exact observable contract: `Err`, `MempoolInclusionStatus`, close code, response type, structured RPC error, exception type/message, pool singleton state, proof validation result, log line, or store row state when it is the observable side effect.
- Do not broaden or narrow consensus-mode coverage casually. `limit_consensus_modes` markers usually document runtime cost, irrelevance, or fork/fixture sensitivity.
- A change to `chia/_tests/environments/`, `chia/_tests/util/setup_nodes.py`, simulator setup, `connection_utils.py`, or `BlockTools` can alter many tests without changing their local files.

## Source Pointers

- Shared fixtures and topology helpers: `chia/_tests/conftest.py`, `chia/_tests/util/setup_nodes.py`, `chia/_tests/environments/`.
- Core CI/runtime controls: `chia/_tests/core/config.py` and subdirectory `config.py` files under `full_node/`, `mempool/`, `data_layer/`, `services/`, `server/`, `daemon/`, `ssl/`, `custom_types/`, and related core test directories.
- Async and connection utilities: `chia/_tests/util/time_out_assert.py`, `chia/_tests/connection_utils.py`.
- Simulator and block tools used by integration tests: `chia/simulator/full_node_simulator.py`, `chia/simulator/block_tools.py`.
