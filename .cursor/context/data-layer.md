# Chia Data Layer Module Context

Verified: 2026-07-12 against a5647a9327e5. If source contradicts this doc, trust source and update the doc.

`chia/data_layer/` implements Chia DataLayer: an off-chain key/value Merkle store whose committed roots are anchored by wallet-managed DataLayer singletons. The module is not just a local database. Correctness depends on alignment between local Merkle roots, wallet singleton history, static delta/full-tree files, mirror subscriptions, and optional downloader/uploader plugins.

## When To Read This

Read this for DataLayer store mutations, root publication, mirror sync, `.dat` file generation/validation, proof verification, DataLayer offers, subscriptions, and DataLayer RPC. For singleton wallet authority and offer signing, also read `wallet.md`; for RPC transport shape, read `rpc.md`.

## Implementation Authority

- `DataLayer` is the service coordinator. It owns lifecycle, wallet RPC access, periodic subscription management, file upload/download orchestration, and the RPC-facing mutation/read API. It does not own chain truth directly; it asks wallet RPC for DataLayer singleton state and updates.
- `DataStore` is the local Merkle/data persistence authority. It stores root generations/status in SQLite, stores Merkle blobs under `merkle_blobs_path`, stores or references key/value blobs under `key_value_blobs_path`, and delegates tree mutation/proof mechanics to `chia_rs.datalayer.MerkleBlob`.
- `DataLayerWallet` and `DataLayerStore` are wallet-side authorities for singleton launcher tracking, root history, mirror coins, lineage proofs, and offer solver data. The service reaches them mostly through wallet RPC request types, while wallet internals persist singleton records in the wallet DB.
- `DataLayerRpcApi` is mostly transport normalization: it converts JSON hex/optional pagination/request shapes into typed service calls. It is not the core invariant boundary, but bugs here can silently change legacy RPC semantics.
- `DataLayerServer` is a separate static-file HTTP process for serving `.dat` files from `server_files_location`; it does not validate store state beyond filename shape.
- S3/plugin support is an extension boundary. Plugins are HTTP services described by `PluginRemote` values and can handle upload/download decisions, but the service still validates downloaded data by inserting it through `DataStore`.

## Why This Is Tricky

Public DataLayer docs describe proving key/value inclusion without sharing the full dataset. Source-level correctness depends on two separate truths staying aligned: wallet singleton history publishes the root sequence, while local/mirrored files provide enough data to reconstruct those roots. Mirrors and plugins can improve availability, but they are never trust anchors; every downloaded file must rebuild the wallet-advertised root before becoming local committed state.

## Wrong Assumptions To Avoid

- Do not treat a local root as current chain truth until wallet confirmation status has been reconciled.
- Do not treat mirror URLs, plugins, or static file names as trusted data sources.
- Do not collapse `None`, omitted root fields, and empty-root sentinels across RPC/service/wallet boundaries.
- Do not treat offer creation as a pure read; it can stage local store mutations before proofs are generated.

## Store And Root Invariants

- A store id is the DataLayer singleton launcher id. Local roots and wallet singleton records must be interpreted against that id, not an arbitrary database namespace.
- Empty-tree roots use two representations: `DataStore` uses `node_hash=None`; RPC/wallet-chain paths often use `bytes32.zeros` via `DataLayer.none_bytes`. Code crossing this boundary must normalize intentionally.
- Root generations are contiguous per store. `DataStore._insert_root()` increments from the latest committed generation unless an explicit generation is supplied, and `_check_roots_are_incrementing()` treats missing generation numbers as corruption.
- Root status drives publication state: `COMMITTED` is local confirmed/canonical, `PENDING` is ready/submitted for chain publication, and `PENDING_BATCH` is an open local batch not yet publishable. Only one pending root is expected; multiple pending roots are an error.
- Most service reads call `_update_confirmation_status()` first. That method compares local generation with wallet `dl_latest_singleton(... only_confirmed=True)`, promotes matching pending roots to committed, shifts generations for already-confirmed roots, and clears stale pending rows. Moving reads/writes around this step changes consistency semantics.
- Local roots can temporarily be ahead of chain roots during batch updates or unconfirmed publication. Sync code treats this as expected and avoids rolling local state backward unless explicit rollback/unsubscribe paths are used.

## Data And File Model

- Key/value data is represented as terminal leaves. Hashing is domain-separated: `key_hash(key) = sha256(0x01 || key)`, `leaf_hash(key, value) = sha256(0x02 || key_hash || value_hash)`, and internal nodes use `sha256(0x02 || left || right)`.
- `MerkleBlob` is the operational tree format. `DataStore` keeps recent blobs in an LRU cache, writes Merkle blobs by store/root hash, and stores larger key/value blobs as zstd-compressed files while keeping smaller blobs inline in the `ids` table.
- Delta/full-tree files are length-prefixed streams of `SerializedNode` records. Full files contain the tree for a root; delta files omit nodes already present in the previous generation by using `DeltaFileCache`.
- File names are part of the protocol and may be grouped by store id. `download_data.is_filename_valid()` rejects names that do not round-trip through the generator.
- Downloaded files are not trusted because they came from a mirror/plugin. `insert_from_delta_file()` feeds them into `DataStore.insert_into_data_store_from_file()`, which reconstructs missing nodes, builds a Merkle blob for the wallet-advertised root, inserts that root as committed, and reloads the blob as a correctness check.
- `maximum_full_file_count` controls how many recent full-tree files are retained/generated. Older full files are pruned, but delta continuity still matters for peers syncing generation by generation.

## Mutation Lifecycle

- Creating a store calls wallet RPC `create_new_dl(... push=True)` and then creates the local tree at the returned launcher id. The chain singleton and local empty root are created through separate systems and can fail independently.
- `batch_update()` mutates local `DataStore` first, then optionally publishes the pending root through wallet RPC. If `submit_on_chain=False`, the root is stored as `PENDING_BATCH` and must later be submitted.
- `batch_insert()` verifies the store is owned by the DataLayer wallet before mutating. This ownership check is the main guard preventing arbitrary local roots from being published for non-owned singletons.
- `submit_pending_root()` converts an open `PENDING_BATCH` root to `PENDING` and publishes it. `_get_publishable_root_hash()` rejects already-confirmed roots and still-open batches.
- Multistore updates stage one update per store id, then call wallet RPC `dl_update_multiple()` with `LauncherRootPair`s. Duplicate store ids in one multistore request are rejected before publishing.
- `DataStore.insert_batch()` handles duplicate-key/change-list semantics and optional autoinsert reference placement. It continues an existing `PENDING_BATCH` only when it is exactly one generation after the committed root; otherwise pending state is an internal error.

## Sync And Subscription Loop

- `periodically_manage_data()` is the background control loop. Each cycle tracks wallet subscriptions, pseudo-subscribes owned stores so files are generated even without explicit subscriptions, optionally auto-subscribes local stores, then runs bounded concurrent `update_subscription()` jobs.
- `update_subscription()` performs four ordered steps: sync subscription URLs from wallet mirrors, fetch/validate remote data, upload local files for owned/current data, then prune old full files. Reordering these affects mirror discovery and file availability.
- Wallet reachability failures are intentionally non-fatal. Subscription tracking stops early if the wallet RPC connection is unavailable and retries next cycle; per-subscription failures are logged without killing the loop.
- `fetch_and_validate()` uses wallet singleton history as the target generation/root sequence, randomizes eligible server URLs, tries plugin-specific or plain HTTP delta downloads, and marks mirror/server failures with backoff in the subscriptions table.
- Unsubscribe is queued and processed only after fetch jobs complete while holding `subscription_lock`, avoiding races between deletion of local subscription/data and active download/update work.
- Owned stores are treated as local publication sources even when they have no external mirror URLs. Subscribed stores are treated as replication targets whose chain roots are verified through wallet state.

## Proofs, Offers, And Singleton Coupling

- Inclusion proofs are rooted in DataLayer Merkle roots, but proof verification also binds those roots to the DataLayer singleton puzzle hash. `dl_verify_proof_internal()` reconstructs the host full puzzle from `inner_puzzle_hash`, proof root, and store id, then verifies `ProofOfInclusion.valid()`.
- `verify_proof()` checks wallet coin state for the proof coin id and reports `current_root` by testing whether that singleton coin is unspent. Historical proofs can verify successfully while not being current.
- Offer construction mutates/uses local stores to produce the maker/taker inclusion sets and solver dependencies. `process_offered_stores()` may stage local inserts before generating proofs, so offer creation is a local data mutation path, not a pure read.
- `make_offer()` verifies the constructed `TradingOffer` summary against local `StoreProofs` before returning. `take_offer()` verifies maker proofs, builds `proofs_of_inclusion` solver data, and then calls wallet RPC outside the data-store transaction because wallet failures may happen after chain submission.
- Non-secure offer cancellation asks wallet RPC for the offer, derives affected store ids from the DataLayer offer summary, then clears pending roots for those stores after cancellation.

## RPC And Compatibility Notes

- RPC request fields mix legacy names (`id`, `root_hash`, `changelist`) with streamable request/response classes for newer offer/proof paths. Preserve wire shapes unless deliberately changing public RPC behavior.
- `root_hash` omission means "latest local committed root" via `Unspecified`; explicit empty-root sentinels can mean the empty tree. `None`, omitted, and `bytes32.zeros` are not interchangeable across RPC, service, and wallet layers.
- Pagination is byte-size based over key/value blob lengths, not item-count based. Oversized single items raise rather than splitting.
- `DataLayerRpcClient` is a thin convenience wrapper and does not cover every server-side nuance; do not infer server behavior solely from client helper argument types.
- Static file serving validates filenames but uses direct synchronous file reads in the request handler. It assumes files are already written under `server_files_location` by the service or plugin.

## Fragility Hotspots

- High-risk edits move work across DB writer transactions, `_update_confirmation_status()`, pending-root status changes, or wallet RPC calls. These boundaries encode publication and rollback assumptions.
- File-system writes for Merkle blobs, key/value blobs, and `.dat` files have TODOs around locking. Concurrent service/plugin/server access should be treated as a real consistency concern.
- Empty-root normalization is subtle and historically uneven. Audit any change touching `bytes32.zeros`, `None`, `Root.node_hash`, or proof roots with both empty and non-empty stores.
- Plugin and mirror URLs are external trust inputs. Downloaded data must continue to be verified against wallet-advertised roots, and file path/name validation must stay strict.
- DataLayer wallet code depends on singleton CLVM structure, odd singleton amounts, lineage proofs, and offer solver field names. Changes in wallet puzzle drivers or offer summaries can break this module without direct edits here.
- Tests for this module should cover lifecycle/order effects: pending batch to publish, confirmation promotion, wallet-unreachable sync retry, delta-file validation failure, grouped vs ungrouped filenames, unsubscribe retention, historical proof verification, and offer-created local mutations.

## Source Pointers

- Service coordination and RPC-facing behavior: `chia/data_layer/data_layer.py`, `chia/data_layer/data_layer_rpc_api.py`.
- Local Merkle/data persistence: `chia/data_layer/data_store.py`.
- Static file validation/download/upload: `chia/data_layer/download_data.py`, `chia/data_layer/data_layer_server.py`, `chia/data_layer/s3_plugin_service.py`.
- Wallet singleton authority: `chia/data_layer/data_layer_wallet.py`, `chia/data_layer/dl_wallet_store.py`.
- Offer/proof request contracts: `chia/data_layer/data_layer_util.py`, `chia/protocols/wallet_protocol.py`.
