# Benchmarks Module Context

Verified: 2026-07-02 against 6526ab6f18. If source contradicts this doc, trust source and update the doc.

`benchmarks/` is a set of standalone executable workloads for measuring performance of production Chia subsystems. It is not imported by node runtime code and it is not a pytest suite. Its value is in preserving representative pressure on hot paths: SQLite stores, mempool admission/rebuilds, streamable serialization, full-block JSON conversion, generator-reference lookup, test-chain materialization, and peer address persistence.

## When To Read This

Read this for changes to benchmark scripts, benchmark data setup, performance workload fidelity, benchmark output artifacts, or production API assumptions encoded by benchmarks.

## Implementation Authority

- Benchmark scripts are consumers of production APIs, not alternate implementations. They should not contain benchmark-only behavior that production code depends on.
- Most workloads intentionally bypass full service orchestration. They create fake or synthetic inputs directly for `BlockStore`, `CoinStore`, `MempoolManager`, `Blockchain`, `Streamable`, and `AddressManager`. This makes runs cheap and targeted, but it also means the benchmark is only as realistic as the synthetic state it builds.
- The module depends heavily on `chia._tests.util.*` helpers for randomized blocks, reward coins, persistent test-chain data, and CLVM generator fixtures. Those helpers are test data factories, not stable public APIs.
- Run benchmark scripts through the repository Python wrapper, for example `tools/py -m benchmarks.streamable`, to use the repo environment and pinned native dependencies.

## Workload Groups

- Store benchmarks exercise SQLite persistence through the same `DBWrapper2` path used by the node. `coin_store.py` stresses `CoinStore.new_block()` with addition-heavy, removal-heavy, and full-block-like mixes, then batch coin lookups and spent-height queries. `block_store.py` creates synthetic `FullBlock`/`BlockRecord` pairs and measures inserts, canonical marking, peak updates, byte/object fetches, generator fetches, range reads, and compactification selection.
- Mempool benchmarks construct enough chain context for `MempoolManager` to accept synthetic spends. `mempool.py` compares threaded and inline validation for large bundles, normal bundles, replace-by-fee, block-generator construction, simple peak extension, and reorg-style peak changes. `mempool-long-lived.py` models a week of block arrivals with repeated transaction admission and spend invalidation.
- Serialization benchmarks are split by data shape. `streamable.py` is a configurable microbenchmark for `Streamable` object creation, bytes round-trips, and JSON round-trips using both a local nested streamable class and randomized `FullBlock`s. `jsonify.py` times `FullBlock.to_json_dict()` over persisted test block shards.
- Chain/generator benchmarks focus on realistic historical shape. `block_ref.py` opens an existing full-node database read-only, builds `Blockchain`, samples transaction-block reference lists from `transaction_height_delta`, and measures `get_block_generator()` over production `lookup_block_generators`.
- Networking persistence is represented by `address_manager_store.py`, which manually populates a large `AddressManager` and measures `serialize_bytes()`/`deserialize_bytes()` plus file IO for the peers file format.

## Data And Fidelity Assumptions

- Randomness is usually seeded to make comparisons reproducible. Preserve seeds unless the benchmark is deliberately being reshaped; unseeded randomness makes before/after comparisons noisy.
- Synthetic block data in `block_store.py` is structurally valid enough for store serialization and lookup, but it does not pass through full consensus validation. Do not use its results to infer consensus validation cost.
- `mempool.py` uses real wallet-generated signed transactions and reward coins, but its `BenchBlockRecord` is only the subset of `BlockRecord` consumed by `MempoolManager`. If mempool peak requirements change, this benchmark must be updated with the new fields or behavior.
- `mempool-long-lived.py` uses an identity puzzle and empty aggregate signature to focus on mempool lifecycle cost. It is intentionally lower-fidelity for wallet signing and signature cost than `mempool.py`.
- `block_ref.py` depends on an external full-node DB path and the sidecar `transaction_height_delta` fixture. It is the closest benchmark here to production chain shape, but it is read-only and measures generator reference lookup, not block validation.
- `address_manager_store.py` mutates `AddressManager` internals directly to build a large address book quickly. This is useful for serialization cost, but fragile because `AddressManager` counts, matrices, and random-position lists are one consistency domain.

## Shared Infrastructure

- `benchmarks.utils.setup_db()` deletes the target DB before each run, enables WAL and `synchronous=full`, optionally logs SQL with `--sql-logging`, and yields a managed `DBWrapper2`. Store benchmarks depend on these settings for comparable write behavior.
- `benchmarks.utils.get_commit_hash()` annotates streamable results with the short git hash and `-dirty` suffix. It changes process cwd to `benchmarks/`, so avoid calling it from code that assumes the original working directory remains stable.
- Several scripts optionally emit cProfile artifacts through `gprof2dot` and Graphviz `dot`. These external tools are not Python dependencies; missing binaries break profiling output, not the measured production APIs.
- Benchmarks write local artifacts such as `*-benchmark.db`, `.profile`, `.dot`, `.png`, `sql.log`, and optional JSON output. Treat these as generated files and keep them out of source changes unless the user explicitly asks for recorded results.

## Coupling To Production Contracts

- `BlockStore.add_full_block()` inserts blocks before canonical-chain state is set; benchmarks that call `set_in_chain()` and `set_peak()` are modeling the post-acceptance persistence sequence, not just raw insertion.
- `CoinStore.new_block()` expects additions and removals to represent one block at a specific height/timestamp. Query benchmarks depend on the source-defined spent-index semantics for unspent and spent-at-height states.
- `MempoolManager.new_peak()` has fast paths for simple transaction-block extension and slower paths for reorg or missing spent-coin information. Benchmarks should preserve both simple-extension and reorg-like paths because regressions often appear in different code.
- `MempoolManager.pre_validate_spendbundle()` can use an executor and caches in-flight/seen bundle state; comparing inline and priority-thread-pool runs is part of the intended coverage.
- `AddressManager.serialize_bytes()` is the current peers file format; service startup also supports an older migration path outside this benchmark. Serialization-only benchmarks should not be read as full peer-discovery coverage.

## Fragility Hotspots

- Changing benchmark constants can dominate results more than code changes. Keep `NUM_ITERS`, batch sizes, transaction-block cadence, and add/remove ratios stable when comparing branches.
- Direct construction of `chia_rs` consensus types is version-sensitive. When native type constructors change, update benchmarks close to the production data model rather than adding compatibility wrappers around stale shapes.
- SQLite benchmarks are sensitive to journal mode, synchronous setting, cache warmth, filesystem, and DB version. Preserve `setup_db()` settings when the goal is regression detection.
- Avoid broad refactors that make benchmarks prettier but less targeted. These scripts intentionally duplicate setup so each workload can be run independently and fail close to the subsystem it measures.
- If production APIs gain stricter invariants, prefer making benchmark synthetic state satisfy those invariants over weakening production code for benchmark convenience.

## Verification Guidance

- Syntax/import smoke checks: run the streamable and address-manager benchmark modules with their smallest practical iteration settings for non-DB subsystem coverage.
- Store benchmarks are heavier and write DB files: `tools/py -m benchmarks.coin_store` and `tools/py -m benchmarks.block_store`.
- `benchmarks.block_ref` requires a full-node database path argument and the sidecar transaction-height fixture; use it only when generator-reference lookup against realistic chain history is relevant.

## Source Pointers

- Benchmark workloads: `benchmarks/`.
- Shared benchmark helpers: `benchmarks/utils.py`.
- Production consumers commonly exercised here: `chia/full_node/`, `chia/types/`, `chia/server/address_manager.py`.
