# chia-tests-root

Verified: 2026-07-12 against a5647a9327e5. If source contradicts this doc, trust source and update the doc.

Scope: `chia/_tests/`. This is distilled architectural context for future audit or implementation agents. It focuses on the shared test harness and cross-suite contracts rather than inventorying individual test files.

## When To Read This

Read this for shared pytest fixtures, consensus-mode parametrization, persistent chain artifacts, simulator/full-node/wallet topologies, keyring isolation, async test conventions, and CI test partitioning.

## Module Role

`chia/_tests/` is the executable specification for the Python node implementation. It spans consensus validation, full-node sync, mempool policy, wallet behavior, data-layer lifecycle, service wiring, farmer/harvester/timelord flows, command handlers, serialization, DB migrations, simulator behavior, and CI workflow generation.

The root module is not a passive test directory. Its shared fixtures define the meaning of many lower-level tests:

- consensus constants and hard-fork activation modes;
- deterministic block and plot generation through `BlockTools`;
- persistent block artifact lookup and regeneration;
- in-memory blockchain/store construction;
- simulator/full-node/wallet/service topologies;
- keyring isolation and localhost/network assumptions;
- async convergence, benchmark, and runtime instrumentation;
- CI job partitioning and resource expectations.

When changing tests under this root, treat fixture edits as architecture changes. A small change in `chia/_tests/conftest.py`, `chia/_tests/util/setup_nodes.py`, `chia/_tests/connection_utils.py`, or wallet/data-layer conftests can alter the semantics of hundreds of tests.

## Consensus-Mode Contract

Most tests that depend on `blockchain_constants` run against five `ConsensusMode` values:

- plain pre-hard-fork behavior;
- hard-fork mode with lowered activation and plot-filter reduction heights;
- soft-fork mode with hard/soft fork heights forced to activation;
- hard-fork mode with lowered V2-plot difficulty;
- hard-fork mode after V1 plot phase-out.

This parametrization is one of the suite's strongest safeguards. It catches assumptions that only hold before or after a fork, especially around CLVM flags, canonical generator rules, plot eligibility, header commitments, transaction-block context, and cached block fixtures.

`@pytest.mark.limit_consensus_modes` is enforced during collection. It only works on tests that actually have the `consensus_mode` fixture; misuse fails collection rather than silently narrowing coverage. Use it to control runtime or isolate fork-specific behavior, not to hide mode-sensitive failures.

Persistent block fixtures are versioned by `test_chain_suffix(consensus_mode)`. `default_400_blocks`, `default_1000_blocks`, `default_10000_blocks`, long-reorg chains, compact chains, and fork-height variants are expected to match the active constants. If a new persistent chain is added, `test_build_chains.py` is part of the change so cached artifacts remain auditable.

## Harness Authority Boundaries

`BlockTools.get_consecutive_blocks()` is the authority for deterministic block shape. Use it when the test needs exact block anatomy: overflow, sub-slot boundaries, transaction-block guarantees, generator references, fork/reorg structure, VDF normalization, hard-fork commitments, or malformed variants.

`FullNodeSimulator` farming APIs are the authority for behavior-level lifecycle tests. Use them when exact block internals are irrelevant and the target contract is mempool admission, block confirmation, wallet sync, RPC state, or data-layer update visibility.

`chia/_tests/util/blockchain.py:create_blockchain()` creates a minimal in-memory production `Blockchain` with real `CoinStore`, `BlockStore`, `BlockHeightMap`, and `InlineExecutor`. It is the right base for isolated consensus/store tests where full service setup would obscure the invariant.

`chia/_tests/util/setup_nodes.py` is the service-topology layer. It builds real `Service` instances for full nodes, simulator nodes, wallets, farmers, harvesters, timelords, introducers, crawlers, seeders, daemons, and solvers. These are not mocks; tests using them are crossing process, RPC, websocket, DB, or peer-protocol boundaries.

`wallet_environments` is a higher-level wallet integration contract. It creates one simulator full node plus N wallets, connects wallets to the node, configures trusted/untrusted mode, opens wallet/full-node RPC clients, optionally prefarms rewards, and returns a `WalletTestFramework`. It also multiplies tests across trusted/untrusted full-node sync and reuse/new-puzzle-hash transaction modes unless explicitly pinned.

## Shared Async And Network Contracts

`time_out_assert()` is the standard convergence primitive. It records structured timeout metadata via `ether.record_property`, applies adjusted timeouts, and polls at short intervals. Use it for node height, peer tables, wallet sync, mempool contents, logs, ban state, and service readiness. Raw sleeps are acceptable only for narrow process/socket settle cases where no observable condition exists yet.

`connection_utils.py` constructs real websocket peers with generated certs and performs protocol handshakes. Dummy connections default to modern `HARD_FORK_2` and `RATE_LIMITS_V3` capabilities, which means protocol and rate-limit tests may be asserting post-fork behavior even when the peer is synthetic.

`self_hostname` is pinned to loopback. Tests that exercise ban logic may patch localhost exemptions; do not generalize those cases to normal local peer behavior without checking the patch.

Keyrings are isolated by autouse/root fixtures. Test code must not prompt for production keyring passphrases. Use `TempKeyring`-backed fixtures for keys and avoid sharing key roots between service topologies.

## Behavioral Test Regions

`blockchain/` is the consensus block-acceptance spec. It constructs real blocks and pushes them through production validation/add paths, with exact `AddBlockResult` and `Err` expectations. Shared `ForkInfo`, `AugmentedBlockchain`, generator-reference lookup, hard-fork commitments, and persistent block cache checks are central contracts.

`core/` is the broad integration boundary for full-node orchestration, mempool policy, server/protocol safety, RPC, stores, data layer, daemon/service startup, and custom type invariants. It often depends more on shared fixtures and topology semantics than on local helper code.

`wallet/` is the wallet behavior spec. Its own conftest installs autouse patches that shortcut consensus-heavy block validation and replace normal `BlockTools` with `WalletBlockTools` unless a test is marked `standard_block_tools`. This is intentional: default wallet tests focus on mempool acceptance, coin-state notifications, and wallet DB updates rather than full consensus validity.

`simulation/`, `harvester/`, `farmer_harvester/`, `timelord/`, `solver/`, `plot_sync/`, and `pools/` are service-flow suites. They validate real service wiring, plots, signage points, VDF/solver interactions, farming/harvesting protocols, pool wallet flows, and sync behavior. These tests are sensitive to ports, temp roots, pre-generated plots, and service cleanup.

`cmds/` tests usually patch RPC client factories through `get_test_cli_clients` and a temp config root. They are command-surface tests, not service integration tests, unless they explicitly use the root `chia_root` subprocess helpers.

`util/`, `clvm/`, `generator/`, `fee_estimation/`, `db/`, and custom-type tests are mostly fast deterministic guards for serialization, CLVM execution, cost accounting, DB wrappers, cache behavior, network protocol files, and helper APIs. Prefer local assertions here instead of service topology.

## Cross-Subsystem Correlation

These per-cluster details are not obvious from conftest or individual test files:

- Farmer proof flow is correlation-heavy: `sps`, `proofs_of_space`, `quality_str_to_identifiers`, `number_of_responses`, `cache_add_time`, and `pending_solver_requests` must agree across async harvester, full-node, pool, and solver messages.
- Plotting and plot-sync tests protect the harvester-to-farmer inventory state machine: `(sync_id, message_id)` ordering, dropped/delayed/duplicated responses, quarantine behavior, and reset/retry.
- Pool tests span config/CLI parsing, CLVM pool puzzle lifecycle, wallet pool store, `plotnft` commands, singleton identity, trusted/untrusted wallet sync, and reorg/revert.
- Daemon tests: websocket registration, keychain proxy, and do not apply P2P message/rate-limit assumptions to daemon JSON traffic.
- RPC structured error tests intentionally preserve both legacy `error` strings and newer `structuredError` payloads.
- Directory config files affect runtime shape: moving tests between core subdirectories can change checked-out blocks/plots, parallelism, CI timeout behavior, and consensus-mode coverage.
- DB wrapper behavior underpins full-node, wallet, and DataLayer stores. Reader transaction visibility, WAL mode, savepoint rollback, and foreign-key delay semantics are infrastructure contracts.

## CI And Test Partitioning

`chia/_tests/README.md` and `testconfig.py` define CI job generation. Treat `testconfig.py` as the source of truth for default settings, with the README as process guidance for regenerating workflows. Test files are discovered by `test_*.py`; each subdirectory below configured root test dirs becomes a workflow matrix job. Parent-directory jobs do not include subdirectory tests, and subdirectory jobs do not include parent tests.

The default CI settings are intentionally conservative: tests can run in parallel by default, block/plot checkout and timelord installation are disabled by default, and per-directory `config.py` files opt heavy suites into block artifacts, timelord install, lower parallelism, or longer job timeouts.

Moving or adding test files can require running workflow generation, even when no test contents changed. Changing only test contents does not require workflow regeneration.

Heavy suites opt into longer timeouts or artifacts for a reason. `blockchain`, `core/full_node`, `core/mempool`, wallet asset suites, `simulation`, `harvester`, `solver`, `timelord`, and persistent-chain users often rely on cached blocks/plots or long-running service flows. Do not collapse their CI config into defaults without measuring runtime and artifact needs.

## Fragility Hotspots

- Fixture-scope changes are high blast radius. `bt` is session-scoped and expensive; service fixtures are function-scoped for isolation; wallet autouse patches are function-scoped to keep consensus shortcuts local to wallet tests.
- Consensus-mode narrowing can hide fork regressions. If a test is mode-limited, the reason should be cost or explicit fork relevance.
- Persistent block artifacts use pickle-backed bytes and file locks under the default root's sibling `blocks` directory. In CI, missing expected artifacts fail instead of regenerating.
- Service tests mutate config dictionaries and temp roots. Reusing mutable config objects or roots can leak ports, daemon settings, trusted peers, autofarm flags, or single-threaded settings between tests.
- Wallet tests are not always consensus-valid by default. Use `standard_block_tools` when testing header validation, weight proofs, BIP158/additions/removals proofs, or wallet protocol behavior that relies on real block structure.
- A final height, balance, or RPC response is usually too weak for async lifecycle tests. Assert the intermediate boundary that matters: advertised, fetched, admitted to mempool, farmed, evicted, synced, persisted, or rolled back.
- Broad `pytest.raises(Exception)`, raw sleeps, non-empty collection checks, and topology-heavy tests for pure policy are weak signals. Tighten them when touching nearby code.

## Change Guidance

Preserve layered assertions. Good tests show the subsystem boundary being protected, not just the final observable state.

When adding or moving tests, check the local directory's `config.py`, root `testconfig.py` defaults, and README workflow-generation rules. Runtime, artifact checkout, timelord install, and parallelism are part of the architecture.

## Verification Guidance

For root fixture changes, include representative downstream coverage from each affected topology: a pure consensus/blockchain test, an isolated mempool or store test, a single full-node/simulator test, a wallet-environment test if wallet fixtures changed, and a service/network test if setup or connection helpers changed.

For workflow-layout changes, update generated workflows as described by `chia/_tests/README.md`. For persistent block fixture changes, include the relevant `test_build_chains.py` coverage and expect artifact/runtime impact.

## Source Pointers

- Root fixtures and test configuration: `chia/_tests/conftest.py`, `chia/_tests/README.md`, `chia/_tests/testconfig.py`.
- Shared topology and utility layers: `chia/_tests/util/setup_nodes.py`, `chia/_tests/util/blockchain.py`, `chia/_tests/connection_utils.py`.
- Wallet environment harness: `chia/_tests/environments/wallet.py`, `chia/_tests/wallet/conftest.py`.
- CI matrix generation: `chia/_tests/build-job-matrix.py`.
