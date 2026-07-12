# chia-simulator

Verified: 2026-07-02 against 6526ab6f18. If source contradicts this doc, trust source and update the doc.

Scope: `chia/simulator/`. This is distilled architectural context for future audit or implementation agents. It intentionally omits generated SSL collateral and obvious helper inventories.

## When To Read This

Read this for simulator block farming, reorg/revert helpers, simulator-only RPC routes, `BlockTools`, service test harnesses, deterministic plots/keys, wallet transaction helpers, and local simulator startup. For production full-node behavior, read `chia-full-node.md`; for consensus acceptance rules, read `chia-consensus.md`.

## Implementation Authority

`chia.simulator` is the deterministic test and local-dev control plane for Chia services. It does not implement an alternate blockchain. Instead, it fabricates blocks, plots, VDFs, keys, config roots, and RPC affordances so tests and simulator users can drive the real `FullNode`, `Blockchain`, `MempoolManager`, wallet sync, and service stack quickly.

The two central surfaces are:

- `BlockTools`: constructs consensus-shaped objects, test plots, keys, block generators, VDF proofs, signage points, sub-slots, and block sequences.
- `FullNodeSimulator`: subclasses `FullNodeAPI` and wraps a real `FullNode` with high-level farming, reorg, revert, mempool-processing, and wallet-sync helpers.

The main architectural rule is: simulator conveniences may shortcut environment setup and block production, but accepted chain state must still flow through normal full-node validation/commit paths unless the function explicitly documents a destructive test-only state edit.

## Why This Is Tricky

Public simulator docs describe complete control of a private chain: farm blocks, reorg, revert, inspect state, and toggle autofarming. In source, that control is intentionally split between safe helpers that still pass through real full-node validation and destructive helpers that directly edit local stores for test convenience. Simulator code is useful because it is close to production paths; making shortcuts broader can create tests that pass against states a real node could never reach.

## Wrong Assumptions To Avoid

- Do not treat simulator block creation as consensus acceptance; generated blocks still need full-node/consensus commit unless a helper explicitly bypasses it.
- Do not use destructive revert helpers as a model for production reorg behavior.
- Do not assume simulator config/key/plot shortcuts are valid outside isolated test roots.
- Do not treat simulator RPC routes as normal full-node RPC behavior; they extend the full-node API for local private-chain control.

## Core Simulator Contracts

- `BlockTools.get_consecutive_blocks()` is a block factory, not a chain authority. It can create blocks with specific timing, overflow, references, transaction generators, reward targets, and seeds; the authoritative decision happens when `FullNode.add_block()`, `FullNode.add_block_batch()`, or `Blockchain.add_block()` accepts those blocks.
- `FullNodeSimulator.farm_new_block()` and `farm_new_transaction_block()` acquire the full node blockchain mutex, derive the next block from current persisted chain state, release the lock, then call `full_node.add_block()`. They rely on the same post-processing path as ordinary full-node operation.
- `add_blocks_in_batches()` intentionally mirrors batch sync: it builds `ForkInfo`, `ValidationState`, and `AugmentedBlockchain`, calls `FullNode.add_block_batch()` in chunks, then runs peak post-processing and `_finish_sync()`. It is the right path for large simulator-generated chains and reorg tails.
- `revert_block_height()` is the exception: it directly rolls `coin_store` and `block_store`, sets the block-store peak, mutates `blockchain._peak_height`, and refreshes the mempool. It does not broadcast and explicitly expects wallets to be wiped. Treat it as destructive local state surgery, not a reorg model.

## Block Generation Model

`BlockTools` lowers mainnet constants for tests (`test_constants`) and creates enough deterministic plots to find proofs quickly. The defaults reduce plot sizes, difficulty, VDF discriminant size, proof filter bits, weight-proof windows, and timing while preserving the consensus shape that validation expects.

`get_consecutive_blocks()` is the heart of the module. It:

- continues from an optional block list or creates genesis;
- computes signage points and end-of-sub-slot bundles;
- scans local test plots for qualified V1/V2 proofs;
- computes required iterations, overflow status, pool/farmer targets, VDF proofs, and MMR/header commitments;
- optionally injects a `SpendBundle` as transaction data or synthesizes spends from farmer reward coins;
- updates local block-record, height-to-hash, difficulty, sub-slot-iterations, MMR, pending-reward, and generator-reference state as it appends blocks.

The factory deliberately exposes consensus edge knobs: `force_overflow`, `skip_slots`, `guarantee_transaction_block`, `keep_going_until_tx_block`, `dummy_block_references`, `block_refs`, normalized VDF proof flags, `current_time`, `genesis_timestamp`, `force_plot_id`, `skip_overflow`, `min_signage_point`, and deterministic `seed`.

Important coupling: block construction must stay aligned with consensus validation around `pre_sp_tx_block_height`, hard-fork gates, V1 phase-out, V2 plot activation/strength, generator reference bans, transaction-block reward maturity, and post-HF2 MMR commitments. A generated block that looks locally coherent can still be rejected by full-node validation if these gates diverge.

## Plot, Key, And Signature State

`BlockTools` owns an ephemeral root path, config, keychain, plot directory, `PlotManager`, expected plot IDs, and local key caches. In automated tests it creates config and SSL under temp roots, forces the test network, normalizes localhost to loopback, assigns free daemon/RPC/service ports, and uses pre-generated cert pools to avoid expensive cert generation.

Plot setup creates deterministic V1 and V2 plots with stable filenames and test private keys. `expected_plots` is the invariant checked after refresh; refresh callbacks assert batch accounting and duration. Deleted or excluded plots must update this set or refresh assertions will fail.

Signatures are produced from plot memo-derived local keys plus farmer/pool keys:

- plot signatures aggregate local, farmer, and optional taproot shares;
- pool signatures are only returned for pool public-key plots;
- `setup_keys()` can use simulator config fingerprint/reward address or synthesize farmer/pool keys in a local keychain.

Because locked-memory key material is expensive, plot local keys are cached by plot ID. Changes around `parse_plot_info()`, V1/V2 plot metadata, or keychain patching can break both block farming and harvester/farmer integration tests.

## Transaction And Wallet Helpers

There are two transaction paths:

- Low-level block inclusion: pass `transaction_data` to `BlockTools.get_consecutive_blocks()` or use `WalletTool` to build simple signed spends for fabricated chain tests.
- Full-node/mempool path: use wallet action scopes or spend bundles, wait for mempool inclusion through `FullNodeSimulator`, then farm a guaranteed transaction block.

`FullNodeSimulator` helpers are behavior-level conveniences:

- `wait_transaction_records_entered_mempool()` polls the full node mempool and can fail fast if a wallet transaction is marked invalid after retries.
- `process_transaction_records()`, `process_spend_bundles()`, and `process_coin_spends()` farm transaction blocks until expected additions exist in the coin store.
- `farm_blocks_to_wallet()` intentionally farms extra transaction blocks because block rewards are only claimable by later transaction blocks. It verifies the exact expected coinbase coin count before waiting for wallet spendability.
- `create_coins_with_amounts()` groups wallet-generated outputs, avoids duplicate puzzle-hash/amount pairs when necessary, farms one transaction block, filters change, and waits for wallet visibility.

Wallet sync checks require three states to converge: the simulator's full node reports synced, the wallet state manager reports synced, and retry-store states are exhausted. Height equality alone is not sufficient.

## RPC Surface

`SimulatorFullNodeRpcApi` extends `FullNodeRpcApi` with simulator-only endpoints:

- `/farm_block`
- `/set_auto_farming`
- `/get_auto_farming`
- `/get_farming_ph`
- `/get_all_blocks`
- `/get_all_coins`
- `/get_all_puzzle_hashes`
- `/revert_blocks`
- `/reorg_blocks`

The client wrapper converts these to typed Python calls and reuses the normal full-node RPC transport. Address inputs are decoded as testnet addresses; `farm_block()` returns a computed new peak height, while the actual block acceptance still happens through simulator/full-node methods.

Autofarm is implemented by installing `FullNode.simulator_transaction_callback = FullNodeSimulator.autofarm_transaction`. When enabled, accepted mempool transactions trigger a transaction-block farm to the simulator farming puzzle hash. The setting is persisted back into `config.yaml`.

## Service Harness

`setup_services.py` is the service-factory layer used by tests. It creates real `Service[...]` instances for full nodes, simulator nodes, wallets, farmer, harvester, timelord, introducer, crawler, seeder, daemon, and solver with test config mutations.

Key setup contracts:

- `setup_full_node(..., simulator=True)` returns a `SimulatorFullNodeService`; otherwise it creates a normal `FullNodeService`.
- Most service ports are set to request ephemeral binding or assigned via `find_available_listen_port()` to avoid collisions. The helper only reserves recently returned ports inside the current process; it is not a cross-process lock.
- In-memory DB URIs are used unless `reuse_db=True`; DB version tables may be pre-created for migration tests.
- Test full nodes disable introducers/DNS by default, reduce peer connect churn, reserve all but one logical core, and force simulator autofarm/current-time off for deterministic tests.
- Capability overrides preserve `BASE`, allow explicit disables, and then force important modern capabilities (`HARD_FORK_2`, `RATE_LIMITS_V3`) on in test setup.

`chia/_tests/util/setup_nodes.py` builds higher-level pytest environments on top of this module. `setup_simulators_and_wallets*()` creates one `BlockTools` per simulator and additional `BlockTools` if wallets outnumber simulators, then returns `FullNodeEnvironment`/`WalletEnvironment` wrappers plus the first `BlockTools`.

## Local Simulator Startup

`start_simulator.async_main()` is the user-facing simulator startup path. It loads config, extracts simulator fingerprint, farming address, and plot directory, forces `simulator.use_current_time=True`, creates `BlockTools`, sets up keys and a small plot set, initializes logging, and returns/runs a full-node service whose peer API is `FullNodeSimulator` and whose RPC API is `SimulatorFullNodeRpcApi`.

This path is intentionally close to a normal full-node service after `BlockTools` setup. If a change only belongs to the CLI/local simulator experience, keep it out of test fixtures unless deterministic tests also need it.

## Small Support Modules

- `WalletTool` is a minimal standard-puzzle wallet for test spend creation. It derives child keys, tracks puzzle-hash-to-key mappings, creates announcement-linked multi-coin spends, computes change, and signs all relevant aggregate-signature opcodes. It is not wallet state management.
- `vdf_prover.get_vdf_info_and_proof()` calls `chiavdf.prove()` directly and wraps the output as `VDFInfo`/`VDFProof`. Simulator block creation depends on this being structurally identical to validation expectations, even with tiny test discriminants.
- `TempKeyring` patches `KeyringWrapper` and `supports_os_passphrase_storage()` so tests use isolated file keyrings. Cleanup restores the old shared keyring root when needed.
- `ssl_certs*.py` are pre-generated test collateral. `ssl_certs.py` cycles through ten CA/node-cert sets and warns if a set is reused while still marked in use.

## Fragility Hotspots

- Do not bypass full-node validation for convenience unless the API is explicitly destructive test state manipulation. Most simulator bugs become false-positive tests.
- `get_consecutive_blocks()` has many consensus mirror points. Edits around overflow, sub-epoch summaries, MMR, `pre_sp_tx_block_height`, V1/V2 plot eligibility, transaction-generator cost, or reward maturity need consensus tests across hard-fork modes.
- `BlockTools` caches block records and MMR state between calls when the input tip matches. Cache invalidation is by header hash; mutating a passed block list or reusing stale `BlockTools` state can produce surprising chains.
- `WalletTool` has mutable class attributes noted by a TODO. Tests that share instances or assume pristine address/key lookup state should be treated carefully.
- `revert_block_height()` intentionally leaves network peers and wallets uninformed. Use reorg helpers for wallet/full-node behavior and revert only for local chain reset scenarios.
- Test setup mutates nested config dicts in place before saving. Passing shared config objects across services can leak simulator-specific settings unless callers copy or isolate roots.

## Source Pointers

- Block generation and deterministic plot/key setup: `chia/simulator/block_tools.py`.
- Simulator full-node API and RPC routes: `chia/simulator/full_node_simulator.py`, `chia/simulator/simulator_full_node_rpc_api.py`, `chia/simulator/simulator_full_node_rpc_client.py`.
- Local simulator startup: `chia/simulator/start_simulator.py`.
- Test service factories: `chia/simulator/setup_services.py`, `chia/_tests/util/setup_nodes.py`.
- Minimal wallet spend helper: `chia/simulator/wallet_tools.py`.
