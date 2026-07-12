# chia-types

Verified: 2026-07-12 against a5647a9327e5. If source contradicts this doc, trust source and update the doc.

Scope: `chia/types/`. This is distilled architectural context for future audit or implementation agents. It intentionally omits file inventory and obvious helper summaries.

## When To Read This

Read this for shared blockchain-format types, CLVM `Program` helpers, `Coin`/condition contracts, proof/VDF wrappers, block generator carriers, mempool item carriers, peer info types, and streamable schemas under `chia/types/`. For ownership of behavior, also read the consuming module context: consensus, full node, wallet, server, farmer/harvester, or timelord.

## Implementation Authority

`chia.types` is the shared type and helper boundary between consensus, full node, wallet, farmer/harvester, timelord, networking, RPC, and tests. It does not usually own orchestration or persistence. Its job is to expose stable Python-facing shapes for consensus objects, CLVM programs, block generators, mempool items, VDF/POS checks, peer addresses, fee units, condition opcodes, and lightweight protocol-adjacent records.

The most important design fact is that many "types" are Rust-backed `chia_rs` objects re-exported or wrapped for Python compatibility. Local Python code often adds only:

- compatibility imports for historical module paths;
- CLVM convenience APIs that convert between `Program` and `SerializedProgram`;
- validation glue around external proof libraries;
- carrier objects that preserve metadata computed by full-node, consensus, or wallet code.

Treat this module as a shared contract layer. Small edits here can change consensus validation, wallet spend construction, mempool ordering, network address bucketing, or wire/persistence serialization even when the file being edited looks like a simple dataclass.

## Rust And Serialization Boundary

`chia_rs` owns the canonical implementations for core consensus types and CLVM execution-heavy objects: `Coin`, `CoinSpend`, `SpendBundle`, `SpendBundleConditions`, `ProofOfSpace`, `VDFInfo`, `VDFProof`, `BlockRecord`, `G1Element`, `G2Element`, and `SerializedProgram` (`chia_rs.Program`). Python files in this module frequently preserve old import paths while delegating behavior to Rust.

The boundary is compatibility-sensitive:

- `SerializedProgram` is an alias to `chia_rs.Program`, not a Python class. `isinstance(..., SerializedProgram)` checks are really checks against the Rust extension type.
- `Coin`, `ClassgroupElement`, `VDFInfo`, and `VDFProof` are re-exported for legacy import paths; removing those paths can break broad call sites outside the apparent file.
- `Streamable` dataclasses in this module are persisted or sent over APIs. Field type changes, enum numeric value changes, and list element changes should be treated like schema migrations.
- JSON helpers such as `MempoolItem.to_json_dict()` and `MempoolSubmissionStatus.to_json_dict_convenience()` are RPC/UI compatibility surfaces, not internal debug formatting.

## CLVM Program Contracts

`blockchain_format.program.Program` is the Python CLVM s-expression wrapper used heavily by wallet puzzle construction, tests, simulator tooling, and some RPC paths. It is not the consensus-hot block validation path, but it calls Rust CLVM execution and tree hashing.

Key contracts:

- `Program.from_bytes()` intentionally parses through the Rust CLVM path. This gives a Python-compatible object while using the faster Rust parser/LazyNode path.
- `Program.run()` and `run_with_cost()` default to wallet-style flags, while module-level run helpers preserve lower-level legacy semantics. This distinction matters for strict mempool/soft-fork behavior.
- `_run()`, `uncurry()`, and `make_spend()` are compatibility adapters accepting both `Program` and `SerializedProgram`. They should not silently accept arbitrary objects because callers rely on type errors to catch malformed puzzle/solution construction.
- `curry()` and `uncurry()` encode/decode the canonical CLVM curry shape. Wallet puzzle drivers and tests assume this shape when matching layered puzzles.
- `sha256_treehash()` is deliberately iterative to avoid Python recursion limits on deeply nested CLVM. Replacing it with a recursive implementation changes a robustness property.
- `get_tree_hash_precalc()` treats any atom matching a supplied `bytes32` as already hashed. That is a performance and semantic contract used by puzzle-hash construction.

Canonical serialization rules are enforced elsewhere for block/mempool validation, but this module is where many tools construct and inspect programs before they reach those validators.

## Coin And Condition Contracts

`Coin` identity and condition opcode values are consensus-level contracts even though their local Python definitions are small.

- `coin_as_list()` preserves the CLVM list order `[parent_coin_info, puzzle_hash, amount]`. This order feeds coin-name and puzzle semantics across wallet and consensus code.
- `hash_coin_ids()` sorts coin IDs descending before hashing the concatenation, with a special single-coin path. Addition-root and Merkle-style commitments elsewhere must remain consistent with this ordering.
- `ConditionOpcode` byte values are CLVM output ABI. Renaming is low risk; changing numeric bytes or deleting legacy opcodes is consensus/protocol risk.
- `ConditionWithArgs` is a lightweight parsed-condition carrier. Semantic validation of argument counts, timelocks, announcements, and signatures happens in Rust/full-node/wallet code, not in this dataclass.
- `SigningMode` strings are external signing domain identifiers. They must stay in lockstep with the relevant CHIP, BLS augmentation modes, and hardware-wallet/offline signing expectations.

## Proof Of Space And VDF Contracts

`blockchain_format.proof_of_space` and `blockchain_format.vdf` contain real validation gates around external proof libraries. They are consensus-critical glue, not just type helpers.

Proof-of-space validation in `verify_and_get_quality_string()` couples:

- pool key vs pool-contract puzzle-hash exclusivity;
- plot parameter min/max checks from `ConsensusConstants`;
- challenge derivation from plot id, original challenge hash, and signage point;
- V1 plot-filter prefix reductions by candidate height;
- V1 phase-out starting at `HARD_FORK2_HEIGHT` and full cutoff after configured epochs;
- SF9 V1 proof-size rejection;
- V2 activation gating and Rust `validate_proof_v2()`.

The `prev_transaction_block_height` parameter is not interchangeable with candidate height. It gates V1 phase-out and V2 activation based on the last transaction block before the current signage point, matching consensus hard-fork semantics. Candidate `height` still feeds V1 prefix reductions. V2 plots use the same prefix-bit plot filter path as V1; both call `calculate_prefix_bits()` and `passes_plot_filter()`.

VDF validation in `validate_vdf()` couples `VDFProof`, `VDFInfo`, `ClassgroupElement`, and consensus constants:

- optional `target_vdf_info` equality check catches callers validating the wrong VDF field;
- witness type is bounded by `MAX_VDF_WITNESS_SIZE`;
- classgroup input must satisfy the exact serialized size expected by VDF validation;
- discriminants and Wesolowski verification are cached, but failures return `False` rather than raising invalid-block exceptions.

`CompressibleVDFField` values identify which block field a compressed VDF proof belongs to. Changes must match full-node/consensus compression and decompression paths.

## Block Generator And Mempool Contracts

`BlockGenerator` is the validation-time view of a block generator: program bytes plus the raw previous generator bytes referenced by height. `NewBlockGenerator` extends it for block creation with block-ref heights, aggregate signature, additions, removals, and total cost.

Important boundaries:

- Generator reference bytes are resolved by consensus/full-node code; this module stores them but does not validate fork ancestry or ref-list limits.
- `NewBlockGenerator.cost` is the total CLVM plus byte plus condition cost used by block creation. Do not confuse it with per-spend cost or mempool virtual cost.
- `BlockInfo` is a structural protocol for blocks/header-like objects that expose generator fields. It supports code that works across full blocks, unfinished blocks, and similar objects without imposing inheritance.

`MempoolItem` is the admitted transaction carrier after expensive validation has already produced `SpendBundleConditions`. It does not independently validate spend correctness.

Core contracts:

- `fee_per_cost` controls ordering via `__lt__`; `fee_per_virtual_cost` includes `SPEND_PENALTY_COST` for alternate ordering/estimation paths.
- `cost` and `num_spends` are derived from Rust `SpendBundleConditions`. If `conds` is absent, these properties fall back to zero for compatibility, but normal admitted items should have conditions.
- `bundle_coin_spends` maps coin id to the original spend plus dedup/fast-forward metadata. `removals` and `to_spend_bundle()` reconstruct from this map, so missing entries produce incorrect RPC output or rebroadcast bundles.
- `latest_singleton_lineage` records fast-forward eligibility and current unspent singleton lineage. It is interpreted by full-node mempool logic and coin-store rollback behavior; this module only stores it.
- `assert_height`, `assert_before_height`, and `assert_before_seconds` are admission-window metadata used around new peaks. They are not replacements for Rust timelock validation.

## Peer And Network-Adjacent Contracts

`PeerInfo`, `UnresolvedPeerInfo`, and `TimestampedPeerInfo` are shared by server, discovery, RPC, tests, and introducer flows. They sit near the network trust boundary but do not decide peer admission.

- `PeerInfo` currently accepts `str` or `IPAddress` for compatibility and remains mutable/`unsafe_hash=True` until call sites fully migrate. Treat it as legacy-sensitive.
- `host` returns the string form for compatibility; `ip` is the normalized address object used for policy and bucketing.
- `get_key()` maps IPv4 into an IPv6-derived key space before appending port. `get_group()` groups addresses by network-specific byte prefixes. AddressManager peer selection and anti-sybil bucketing depend on these exact bytes.
- `TimestampedPeerInfo` is streamable peer-list data. Freshness and address validity are normalized by server/discovery code, not trusted from the dataclass.

## Cross-Module Coupling

Primary consumers:

- `chia.consensus` consumes `BlockGenerator`, `ValidationState`, VDF/POS helpers, `Coin`, and generator/program aliases during block validation, difficulty/slot checks, and fork-aware generator resolution.
- `chia.full_node` consumes `MempoolItem`, `NewBlockGenerator`, `BlockGenerator`, `PeerInfo`, VDF/POS helpers, and `WeightProof` for sync, block creation, tx admission, RPC, and peer handling.
- `chia.wallet` consumes `Program`, `SerializedProgram`, `make_spend()`, condition opcodes, signing modes, weight-proof carriers, and peer info for puzzle construction, signing, SPV sync, and tests.
- `chia.server` and discovery consume peer-info types for connection identity context, address-book bucketing, and RPC-facing peer data.
- `chia.farmer`, `chia.harvester`, `chia.plotting`, and `chia.timelord` consume proof/VDF helpers and plot-key derivation functions around signage points, VDF validation, and plot creation.

This module generally should not import upward into those consumers. Its dependency direction is toward `chia_rs`, `clvm`, `chiapos`, `chiavdf`, and low-level `chia.util` helpers.

## Persistence And Compatibility Notes

- `WeightProof`, `RecentChainData`, `ProofBlockHeader`, `UnfinishedHeaderBlock`, `MempoolSubmissionStatus`, and `FeeRate` are `Streamable` schemas. Existing DB rows, protocol payloads, and RPC fixtures may depend on their exact field order and integer widths.
- `MempoolInclusionStatus` values are represented as `uint8` inside some wallet records. Numeric stability matters more than enum member ordering aesthetics.
- `FeeRate.create()` rounds up with `math.ceil()`. This prevents underquoting when converting mojos over CLVM cost and mirrors protocol fee-estimate compatibility expectations.
- `Mojos` and `CLVMCost` are `NewType` wrappers around `uint64`; they add static clarity only. Runtime code still receives integers.

## Trust Boundaries

All serialized blocks, spend bundles, generators, conditions, peer addresses, proof bytes, VDF proofs, and weight proofs that enter these types from peers or RPC remain untrusted. `Streamable` parsing and dataclass construction only establish shape.

Validation authority lives elsewhere:

- spend correctness, conditions, signatures, and timelocks: Rust validation plus full-node mempool/consensus code;
- block generator ancestry, ref limits, cost limits, and canonical encoding: consensus/full-node validation;
- chain weight-proof validity: full-node and wallet weight-proof handlers;
- peer admission, rate limits, and address freshness: server/discovery;
- wallet ownership and puzzle-driver interpretation: wallet state and puzzle modules.

Do not add "convenient" validation shortcuts in this module unless they are pure helpers with the same semantics as the owning subsystem. Divergent local checks here can make callers trust a shape that the real authority later rejects.

## Fragility Hotspots

- High-risk edits: changing `ConditionOpcode` bytes, `SigningMode` strings, streamable field order/types, Rust alias imports, `Program` default flags, proof/VDF height gates, V1 prefix filtering, or peer bucketing bytes.
- Be careful with `prev_transaction_block_height` vs candidate `height` in proof-of-space logic. Hard-fork and phase-out gates intentionally use different notions of height in different places.
- Do not conflate `Program` and `SerializedProgram`: wallet construction often needs Python CLVM traversal, while full-node validation and generator paths expect serialized Rust-backed bytes.
- Do not treat `MempoolItem.to_spend_bundle()` as the original submitted bundle if `bundle_coin_spends` was transformed for dedup or fast-forward behavior; check full-node mempool semantics first.
- Replacing Rust-backed aliases with Python duplicates can break serialization equality, hashing, JSON conversion, or consensus validation even if attributes appear identical.
- Tests for this module should usually be consumer-driven: consensus tests for proof/generator changes, mempool tests for `MempoolItem` behavior, wallet tests for `Program`/`make_spend()`/signing changes, and server/discovery tests for `PeerInfo`.

## Source Pointers

For exact type definitions and helper behavior, read the owning files under `chia/types/`, especially `chia/types/blockchain_format/`, `chia/types/blockchain_format/proof_of_space.py`, `chia/types/condition_opcodes.py`, `chia/types/condition_with_args.py`, `chia/types/generator_types.py`, `chia/types/mempool_item.py`, and `chia/types/peer_info.py`. For proof-of-space behavior changes, also inspect `chia/_tests/core/custom_types/test_proof_of_space.py`.
