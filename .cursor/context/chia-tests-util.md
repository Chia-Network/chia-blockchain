# chia-tests-util

Verified: 2026-07-02 against 6526ab6f18. If source contradicts this doc, trust source and update the doc.

Scope: `chia/_tests/util/`. This is distilled architectural context for future audit or implementation agents. It intentionally omits helper-by-helper inventory and focuses on contracts that affect the wider test suite.

## When To Read This

Read this for shared test utilities, topology setup helpers, deterministic blockchain fixtures, SpendSim, async convergence helpers, protocol corpus generation, plot-cache monkeypatching, and cross-suite test infrastructure.

## Module Role

`chia/_tests/util/` is the shared test infrastructure layer for the repository. It is not a leaf test directory: changes here can alter the meaning, runtime, or flake profile of blockchain, full-node, mempool, wallet, server, farmer/harvester, timelord, data-layer, plotting, and protocol tests.

The package provides five architectural surfaces:

- service topology construction for real full nodes, simulators, wallets, farmers, harvesters, timelords, solvers, introducers, daemon, VDF clients, and RPC clients;
- deterministic chain and DB construction for consensus-heavy tests and persistent fixture chains;
- lightweight spend/mempool simulation for CLVM and wallet contract tests that need production mempool and coin-store behavior without a full node;
- async convergence, benchmark, protocol, RPC, and process helpers used as observable test contracts;
- protocol serialization corpora and generated tests that pin wire compatibility across node roles.

Treat edits here as harness changes, not local cleanup, unless the helper is demonstrably unused outside `chia/_tests/util/` itself.

## Implementation Authority

`setup_nodes.py` is the topology authority. Its context managers own keyring isolation, root/config construction, service lifetimes, port choices, capability toggles, wallet RPC client creation, and teardown order. `setup_two_nodes()` and `setup_n_nodes()` create real full-node services with separate DBs. `setup_simulators_and_wallets*()` creates simulator full nodes plus wallet services and is the fixture backbone for wallet, data-layer, RPC, and simulation tests. `setup_farmer_solver_multi_harvester()` and `setup_full_system()` cross into farmer/harvester/solver/timelord/daemon behavior and include explicit connection-settle loops.

`blockchain.py` is the deterministic chain authority. `create_blockchain()` constructs a production `Blockchain` over in-memory stores with an `InlineExecutor`; tests using it are still exercising real block/coin stores. `persistent_blocks()` and `new_test_db()` define the cached block-artifact contract used by long sync, weight proof, reorg, commitment, and generated-chain tests. In CI, missing persistent block files are hard failures, not cache misses.

`spend_sim.py` is a deliberately partial full-node substitute for Chialisp and wallet contract tests. It uses production `MempoolManager`, `Mempool`, `CoinStore`, and `HintStore`, but replaces `FullBlock` and `BlockRecord` with streamable minimal types. `SimClient` mirrors selected full-node RPC client methods so tests can later swap to a real client. This makes it useful for spend admission, mempool inclusion status, coin lookup, hints, puzzle-and-solution extraction, and block farming, but not for peer protocol, weight proofs, signage points, non-transaction blocks, or full consensus header behavior.

`time_out_assert.py` is the async convergence authority. Tests depend on it for retry semantics, adjusted timeouts, short polling intervals, pytest traceback hiding, and Ether/JUnit telemetry. Replacing it with sleeps or changing its comparison semantics can hide flakes or make CI diagnostics worse.

`build_network_protocol_files.py`, `network_protocol_data.py`, `protocol_messages_json.py`, and the generated protocol tests form the wire-compatibility corpus. Adding, removing, or reordering visited protocol messages changes the serialized byte stream and JSON fixtures that guard Streamable compatibility across farmer, full node, wallet, harvester, introducer, pool, timelord, shared, and solver protocols.

## Cross-Module Contracts

- `chia/_tests/conftest.py` imports this module heavily. Session fixtures install the plot cache, isolate keyring access, create shared `BlockTools`, construct persistent chains by consensus mode, and expose simulator/wallet/full-node fixtures through these helpers.
- Full-node and blockchain tests rely on `create_blockchain()` and `persistent_blocks()` preserving production store semantics. A helper that looks like fixture setup can affect fork choice, generator refs, MMR commitments, coin-store rollback, or DB-version coverage.
- Wallet and data-layer tests rely on `setup_simulators_and_wallets*()` to create wallet RPC clients against live wallet services. The returned environment couples wallet action scopes, full-node mempool admission, simulator farming, RPC reads, and wallet sync.
- Mempool tests rely on `spend_sim.py`, `get_name_puzzle_conditions.py`, and `misc.invariant_check_mempool()` for production CLVM flags, spend-bundle validation, pool accounting, and fast-forward singleton invariants.
- Server/protocol tests rely on generated protocol data and helpers like `time_out_messages()` and `patch_request_handler()` to observe message ordering, API metadata, request/reply state, and rate-limit coverage.
- Farmer/harvester and plotting tests rely on `setup_farmer_solver_multi_harvester()` and `plot_cache.install()`. The plot cache monkeypatches prover methods and `chia_rs.solve_proof` globally for the test process, merging cache state on exit under a file lock.
- `full_sync.py` is an executable sync harness, not a normal unit helper. It builds a `FullNode` from config, stubs network broadcast, streams compressed blocks from a DB, and chooses between `add_block_batch()` sync behavior and keep-up behavior. Changes here affect full-sync benchmarking and regression reproduction.

## Fragility And Review Signals

- Async topology helpers must keep `AsyncExitStack` ownership clear. Moving service creation out of the managed stack, changing keyring scope, or skipping shielded/ordered teardown can leak processes, sockets, DB handles, or keyring state into unrelated tests.
- Default config overrides in topology helpers are part of test semantics: sync waits, coin logging, and block-creation timeout settings make tests faster and more observable. Removing them can cause slow convergence or missing coin logs.
- Persistent block artifacts are shared by consensus mode. Changing generation parameters, suffixes, fork heights, seed values, dummy refs, transaction inclusion, or normalization flags requires updating the corresponding generated-chain tests and cached artifacts.
- `SpendSim` has intentional simplifications: every simulated block is effectively a transaction block, reward/header hashes are synthetic, and rewinds reset the mempool. Do not generalize conclusions from it to full-node sync, consensus header validation, or non-transaction block behavior.
- `get_name_puzzle_conditions()` chooses `run_block_generator` vs `run_block_generator2` at `HARD_FORK_HEIGHT` and always disables signature validation. It is suitable for condition extraction tests, not aggregate-signature correctness.
- `time_out_assert_custom_interval()` records caller file/line and timeout telemetry even on failure. Changing stack distance, `adjusted_timeout()`, interval behavior, or error messages can affect both debugging and test-report processing.
- `misc.py` mixes narrow utilities with high-blast-radius helpers. `BenchmarkRunner`, `BenchmarkData`, and `TestId` feed `process_junit`; `patch_request_handler()` mutates API metadata; `invariant_check_mempool()` reaches into private SQLite-backed mempool state by design.
- `split_managers.py` is explicitly transitional. New code should avoid depending on split enter/exit semantics unless a test genuinely needs lifecycle control across phases.
- `plot_cache.py` uses pickle and global monkeypatching intentionally for test speed. It should remain test-only; do not reuse its cache format or global patch behavior in production code.

## Change Guidance

Each shared helper represents a specific test layer: pure DB/store, production blockchain/store without networking, deterministic persistent chains, SpendSim, simulator-wallet lifecycle, real service wiring, or protocol corpus compatibility. When adding a helper, document that layer so future tests do not broaden runtime by accident.

## Verification Guidance

For shared harness edits, add at least one representative downstream test:

- `setup_nodes.py`: a wallet/simulator test plus a full-node or farmer/harvester topology user;
- `blockchain.py`: a blockchain helper test and a persistent-chain consumer such as generated-chain or reorg coverage;
- `spend_sim.py` or `get_name_puzzle_conditions.py`: the targeted mempool/CLVM/wallet contract tests;
- `time_out_assert.py` or benchmark telemetry: a direct util test plus `chia/_tests/process_junit.py`-related expectations if telemetry shape changes;
- protocol corpus files: rebuild/check generated protocol bytes and JSON tests;
- `plot_cache.py`: its util tests plus a plotting/farmer-harvester path if monkeypatch behavior changes.

## Source Pointers

- Service topology and environment setup: `chia/_tests/util/setup_nodes.py`, `chia/_tests/environments/`.
- Deterministic chain and DB helpers: `chia/_tests/util/blockchain.py`.
- Spend simulation and condition helpers: `chia/_tests/util/spend_sim.py`, `chia/_tests/util/get_name_puzzle_conditions.py`.
- Async and protocol helpers: `chia/_tests/util/time_out_assert.py`, `chia/_tests/util/network_protocol_data.py`.
- Plot and process helpers: `chia/_tests/util/plot_cache.py`, `chia/_tests/process_junit.py`.
