# chia-tests-clvm

Verified: 2026-07-12 against 24db9ad3901d. If source contradicts this doc, trust source and update the doc.

Scope: `chia/_tests/clvm/`. This is distilled architectural context for future audit or implementation agents. It intentionally omits exhaustive test inventory and obvious helper summaries.

## When To Read This

Read this for CLVM tests, `Program` helper behavior, puzzle compression, wallet puzzle-driver tests, SpendSim-backed smart-contract tests, singleton/custody/message-condition contracts, and CLVM verification strategy.

## Module Role

`chia/_tests/clvm/` is the executable contract for Python-facing CLVM program utilities, wallet puzzle drivers, condition builders, and lightweight smart-contract integration. It sits between pure wallet helper tests and full-node consensus tests: many cases construct real `Program`, `CoinSpend`, and `SpendBundle` objects, then either execute them directly or submit them through a small simulator backed by production mempool and coin-store code.

The suite protects these boundaries:

- `Program` convenience APIs (`at`, `replace`, `curry`, `uncurry`, run variants) and tree-hash helpers used by wallet puzzle construction.
- CLVM serialization/deserialization and puzzle compression compatibility, including deployed dictionary versions.
- Standard payment puzzles, taproot/hidden-puzzle signing, M-of-N delegated spends, singleton top-layer behavior, custody puzzle architecture, restrictions, and message conditions.
- `SpendSim`'s RPC-like surface for puzzle tests that need mempool admission, block farming, hints, rollback, or puzzle/solution lookup without booting full services.

## Execution Harnesses

There are two distinct testing modes. Do not blur them.

Pure CLVM/unit tests run `Program` methods, compiled puzzle modules, or helper functions directly. They are appropriate for structural invariants: exact curry shapes, tree hashes, decoded puzzle driver fields, compression round trips, chialisp deserialization, and CLVM stepping.

Simulator-backed tests use `sim_and_client()` from `chia/_tests/util/spend_sim.py`. This is not a mock mempool. `SpendSim` wires a real full-node `CoinStore`, `HintStore`, `MempoolManager`, `Mempool`, and `simple_solution_generator()` into an in-memory DB, then represents blocks with trimmed `SimFullBlock`/`SimBlockRecord` objects. `SimClient.push_tx()` calls production `pre_validate_spendbundle()` and `add_spend_bundle()`, so failures like `GENERATOR_RUNTIME_ERROR`, timelock errors, message pairing errors, and signature/condition validation are meaningful mempool results.

`SpendSim.farm_block()` includes current mempool items by asking `MempoolManager.create_bundle_from_mempool()`, updates the real coin store with additions/removals and hints, records a transaction generator, advances peak state, then clears/revalidates mempool through `new_peak()`. `rewind()` rolls back the coin store and resets mempool state, which is why singleton and custody tests can reuse a pre-spend height for alternate paths.

`chia/_tests/clvm/coin_store.py` is a much smaller legacy-style spend harness used by older puzzle tests. It validates a bundle through `get_name_puzzle_conditions()` in mempool mode and `check_time_locks()`, then applies additions/removals to an in-memory record map. Prefer `SpendSim` for behavior that depends on real mempool admission, hints, rollback, or block inclusion.

## Core Behavioral Contracts

`Program` tests defend exact Python wrapper behavior around Rust CLVM execution:

- `Program.run()` and instance `run_with_cost()` default to wallet-style flags including mempool/soft-fork behavior, while module-level run helpers can use non-mempool flags. Tests that assert cost or output bytes should be explicit about which path they use.
- `curry()` emits the canonical CLVM curry shape and `uncurry()` only recognizes that shape without trailing garbage or malformed quoted args. Wallet puzzle drivers rely on this form to inspect layered puzzles.
- `replace()` paths use the same `f`/`r` grammar as `at()` and reject conflicting or impossible paths rather than partially rebuilding malformed trees.
- Tree-hash helpers in `wallet.util.curry_and_treehash` must match `Program.to(...).get_tree_hash()` across atoms, ints, atom lists, and curried args, including negative and large integer encodings.

Puzzle compression tests are compatibility tests, not performance-only checks. `puzzle_compression.ZDICT` contains already-deployed puzzle bytes and legacy dictionaries; `lowest_best_version()` encodes which compression version is required for recognized modules. Decompression intentionally caps output, so tests around large buffers are resource-limit checks.

Chialisp deserialization tests run the CLVM deserializer module against serialized atoms/lists and overflow-sized atom headers. They protect canonical parsing and failure behavior at the CLVM byte-format boundary.

## SpendSim And RPC-Like Semantics

`test_spend_sim.py` is the contract for what smart-contract tests may assume from `SimClient`:

- farming creates realistic reward coins and heights;
- `push_tx()` surfaces `MempoolInclusionStatus` plus `Err`;
- hint lookup honors include-spent and height filters;
- puzzle-hash, puzzle-hashes, parent-id, name, block-record, block, additions/removals, mempool item, and puzzle/solution lookups behave close enough to full-node RPC for puzzle-driver tests;
- `get_puzzle_and_solution()` reconstructs coin spends from recorded block generators using production Rust lookup.

Because `SpendSim` stores simplified block records, it is good for puzzle and mempool behavior, not for consensus/header/weight-proof assertions.

## Custody Architecture Contracts

The custody tests exercise `wallet.puzzles.custody.*` as a small composable puzzle framework:

- `PuzzleWithRestrictions.memo()` is the on-chain/exported synchronization contract. `from_memo()` must reconstruct unknown members/restrictions, including recursive `MofN`, so later wallet code can fill known puzzle implementations by puzzle hash.
- `PuzzleWithRestrictions.puzzle_reveal()` layers `INDEX_WRAPPER`, optional restriction layer, and top-level `DELEGATED_PUZZLE_FEEDER`; `puzzle_hash()` uses precalculated hashes to match the reveal without materializing every layer.
- `solve()` must align member validator solutions, delegated-puzzle validator solutions, member solution, and optional delegated puzzle/solution in the exact order expected by the CLVM modules.
- `MofN` rejects impossible thresholds and duplicate member nodes. Its solve format differs across threshold shapes, so tests iterate combinations to catch proof-format regressions.

Concrete member puzzle tests cover BLS-with-taproot, singleton-backed membership, and fixed-puzzle membership. They intentionally check both success and escape paths: invalid hidden puzzle, wrong fixed delegated puzzle, missing singleton approval message, and constructor/solve misuse errors.

Restriction tests cover delegated-puzzle wrapper stacks, heightlocks, fixed `CREATE_COIN` destinations, and `SEND_MESSAGE` bans. A valid restriction often wraps the delegated puzzle before submission; submitting the original delegated puzzle with only a matching solution is expected to fail.

## Message Conditions

Message-condition tests cover the paired `SEND_MESSAGE`/`RECEIVE_MESSAGE` invariant. For every nonzero sender/receiver commitment mode, a lone send or receive fails with `MESSAGE_NOT_SENT_OR_RECEIVED`, while the aggregate succeeds.

`MessageParticipant` is deliberately strict: no anyone-can-send/receive participant, coin-id commitments must either stand alone or match all parent/puzzle/amount fields, and manual `mode_integer` values must match supplied arguments. These are API footgun tests as much as condition tests.

## Singleton Contracts

Singleton tests cover both legacy and current top layers. They assert launcher flow, eve spend, steady-state spend, P2-singleton claims, P2-singleton-or-delayed claims, delayed escape, melting, and negative odd-amount invariants.

Key invariants:

- launcher amounts must be odd;
- singleton spends must create exactly one odd child unless melting;
- lineage proofs derive from the parent coin spend and include inner puzzle hash for non-launcher parents;
- P2-singleton claims couple coin and puzzle announcements;
- delayed escape requires elapsed seconds/blocks in simulator state;
- legacy and current singleton layers may surface different `Err` values for the same malformed even-coin path, and tests encode that distinction.

## Editing And Review Guidance

Use `sim_and_client()` when the assertion depends on mempool admission, condition validation, hints, rollback, or inclusion in a transaction generator. Use direct `Program` execution for deterministic CLVM structure, serialization, hashing, and helper API behavior.

Keep negative-path assertions specific. These tests often distinguish `FAILED` from `PENDING` and specific `Err` codes such as `GENERATOR_RUNTIME_ERROR`, `ASSERT_HEIGHT_RELATIVE_FAILED`, `ASSERT_SECONDS_RELATIVE_FAILED`, `ASSERT_MY_AMOUNT_FAILED`, or `MESSAGE_NOT_SENT_OR_RECEIVED`.

Do not replace simulator farming/rewind flows with raw state mutation unless the production behavior being skipped is irrelevant. Many tests depend on `new_peak()`, coin-store rollback, hint persistence, or mempool clearing.

When modifying wallet puzzle drivers, assert both the pure representation contract (memo, puzzle hash, parse/fill behavior) and an on-chain spend path through `SpendSim`. The former catches wallet sync/recognition regressions; the latter catches CLVM or mempool acceptance regressions.

For compression changes, preserve deployed dictionary compatibility and the decompression output cap. Adding a dictionary version should update `LATEST_VERSION` behavior and `lowest_best_version()` expectations without making older compressed blobs undecodable.

## Verification Guidance

For changes touching `SpendSim`, include `test_spend_sim.py` plus at least one simulator-backed puzzle suite that uses rollback or mempool errors. For changes touching `Program`, include `test_program.py` and `test_curry_and_treehash.py`. For wallet puzzle-driver changes, include the relevant CLVM test file and consider the corresponding wallet module tests if the puzzle is surfaced through wallet recognition or transaction creation.

## Source Pointers

- CLVM test suite: `chia/_tests/clvm/`.
- SpendSim harness: `chia/_tests/util/spend_sim.py`.
- Python-facing CLVM wrappers: `chia/types/blockchain_format/program.py`, `chia/wallet/puzzles/`.
- Source behavior context: `.cursor/context/types.md`, `.cursor/context/wallet.md`.
