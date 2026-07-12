# Chia Util Module Context

Verified: 2026-07-12 against a5647a9327e5. If source contradicts this doc, trust source and update the doc.

`chia/util/` is the shared infrastructure layer beneath consensus, networking,
wallet, daemon, data layer, simulator, and tests. It is not one cohesive product
feature; it is a collection of small primitives that become high impact because
other modules treat them as authority for serialization, SQLite access, key
storage, config persistence, async scheduling, cache bounds, and RPC formatting.

## When To Read This

Read this for shared serialization, SQLite transaction wrappers, keychain/keyring behavior, config/file persistence, async scheduling helpers, bounded caches, network/RPC adapters, and shared error types.

## Landmarks

| file                             | owns                                        |
| -------------------------------- | ------------------------------------------- |
| `chia/util/streamable.py`        | deterministic serialization, get_hash()     |
| `chia/util/db_wrapper.py`        | SQLite writer/reader transaction semantics  |
| `chia/util/keychain.py`          | mnemonic/public/private-key operations      |
| `chia/util/keyring_wrapper.py`   | keyring backend selection, passphrase cache |
| `chia/util/config.py`            | YAML config load/save hygiene               |
| `chia/util/priority_mutex.py`    | priority-ordered lock (block > tx)          |
| `chia/util/limited_semaphore.py` | bounded active+waiting DoS backpressure     |
| `chia/util/lru_cache.py`         | LRU/FIFO bounded cache primitives           |

## Implementation Authority

- `streamable.py` is the Python-side deterministic serialization authority for
  many protocol, wallet, consensus-adjacent, and RPC request/response types.
  It enforces `@streamable` + frozen dataclass + `Streamable` inheritance at
  class definition time, caches per-field parse/stream/convert functions, and
  defines `get_hash()` as `sha256(bytes(self))`. Any behavioral change here can
  alter wire format, JSON shape, object construction coercion, or consensus
  hashes for Python-defined streamables.
- `db_wrapper.py` is the SQLite transaction authority. Stores in full node,
  wallet, data layer, simulator, and tests rely on `DBWrapper2` to serialize
  writes through one writer connection, provide pooled query-only readers, allow
  same-task nested savepoints, and expose uncommitted writes to same-task readers.
  Bypassing it loses cancellation-safe cleanup and read/write consistency rules.
- `keychain.py`, `keyring_wrapper.py`, and `file_keyring.py` are the local key
  custody boundary. `Keychain` exposes mnemonic/public/private-key operations;
  `KeyringWrapper` selects and owns the singleton backend plus passphrase cache;
  `FileKeyring` persists encrypted key material and labels in `keyring.yaml`.
  Callers should not treat the file format or cached plaintext as a public API.
- `config.py`, `lock.py`, `files.py`, and `path.py` are the persistence hygiene
  layer for YAML config and local files. Config writes assume an acquired
  `Lockfile` and use temp-file replacement; path handling intentionally resolves
  relative paths under the Chia root.
- `network.py`, `ip_address.py`, `ws_message.py`, and `json_util.py` are adapters
  around `aiohttp`, DNS/IP parsing, daemon websocket payloads, and JSON
  serialization. They are low-level, but they sit on RPC/server trust boundaries.

## Serialization Contracts

- Streamable field order is dataclass field order. Reordering fields, changing
  type annotations, replacing sized ints/bytes with Python primitives, or adding
  non-default fields changes binary compatibility and possibly hash identity.
- `Streamable.parse()` constructs objects without normal `__init__()` or
  `__post_init__()` and sets parsed fields directly. Constructor calls run
  streamable post-init coercion, but parse paths trust the field parse functions.
  Validation that must apply to untrusted bytes belongs in the parse function or
  caller, not only in a dataclass `__post_init__`.
- Dicts serialize as lists of key/value tuples and reject duplicate keys on
  parse. Lists/bytes/strings use source-defined length prefixes. Optionals use a
  source-defined presence marker. BLS/sized-byte/Rust FFI types are delegated to their `parse`,
  `parse_rust`, `stream`, or `__bytes__` implementations.
- `from_bytes()` rejects trailing bytes. Code that wants partial parsing must
  use `parse()` deliberately and own the remaining stream.
- `list_limits` can truncate top-level list fields while still consuming the
  full serialized input; for Rust-backed objects `_apply_list_limits()` recurses
  through truncatable children. This is a defensive display/DoS feature, not a
  consensus validation substitute.
- JSON conversion emits byte-like values as `0x` hex strings and large/sized ints
  as Python ints unless an object supplies a JSON override. RPC callers depend on
  this stable shape for CLI/daemon/wallet interactions.

## SQLite And Transaction Semantics

- `DBWrapper2.managed()` is preferred over `create()`/`close()` because it uses an
  async exit stack and shields connection cleanup. Most new code should use the
  managed form unless integrating with legacy lifecycle code.
- The writer connection is the only write-capable connection. Reader connections
  are put into `pragma query_only` and pooled. `reader_no_transaction()` returns
  the writer connection when the current task already owns the writer so callers
  can read their own uncommitted changes.
- `writer()` and `writer_maybe_transaction()` are savepoint based. Nested writers
  are allowed only within the same asyncio task. Cross-task writes are serialized
  by `_lock`; same-task nested writes become nested savepoints.
- Savepoint cleanup is cancellation-sensitive. `_savepoint_ctx()` deliberately
  shields rollback/release and temporarily clears pending cancellation state when
  needed so orphan savepoints do not trap later writes in an
  invisible uncommitted transaction. Do not simplify this unless tests cover
  cancellation during `SAVEPOINT`, `ROLLBACK TO`, and `RELEASE`.
- Foreign-key enforcement can be temporarily changed only for an outer writer.
  Requesting delayed enforcement inside a nested writer raises
  `NestedForeignKeyDelayedRequestError`, because nested checks would be ambiguous.
- `reader()` starts `BEGIN DEFERRED` when needed and rolls back on exit even for
  read paths, protecting against accidental writes through a reader connection.
- `SQLITE_MAX_VARIABLE_NUMBER`, `SQLITE_INT_MAX`, and `host_parameter_limit` are
  cross-module batching constraints for large store queries and inserts.

## Keychain And Secret Storage

- Private key entries are stored as public key bytes plus entropy bytes; public
  only entries store only public key bytes. `KeyData` reconstructs and checks
  fingerprint/public/private-key consistency when secrets are included.
- Mnemonic handling follows BIP39-style entropy/checksum processing and accepts
  four-character word prefixes for ASCII seed phrases. Invalid ordering or
  unknown words raise before key derivation.
- The file keyring is always encrypted, even without a user master passphrase:
  absence of a user passphrase means the stable default passphrase is used. That
  constant is compatibility-sensitive; changing it strands existing passphrase-less
  keyrings unless a migration is provided.
- The file keyring's on-disk encryption format and the default (no-user-passphrase) passphrase are compatibility-sensitive: changing either strands existing keyrings without a migration. Exact KDF/cipher/file-layout details live in `chia/util/file_keyring.py`.
- `FileKeyring` maintains two caches: outer encrypted file content and decrypted
  key/label data. A watchdog observer plus `Lockfile` mark/reload external file
  modifications. Writes merge staged outer properties such as passphrase hints.
- `KeyringWrapper` caches the master passphrase and can persist it to macOS or
  Windows credential storage. On macOS headless access, `errSecInteractionNotAllowed`
  is warned and handled specially. Interactive prompting currently lives below
  some storage methods, so daemon/CLI call paths must account for possible prompts.
- Labels are unique across fingerprints, trimmed exactly, bounded by
  `MAX_LABEL_LENGTH`, and reject leading/trailing whitespace, tabs, and newlines.

## Concurrency And Scheduling Primitives

- `PriorityMutex` gives lower enum values first and explicitly rejects nested
  acquisition by the active task. `Blockchain` uses this to let block validation
  outrank transaction processing. Starvation/fairness behavior is priority-first
  within FIFO deques; changing queue ordering changes full-node latency semantics.
- `PriorityThreadPoolExecutor` is not a drop-in `ThreadPoolExecutor`. Work is
  ordered by `nice`, then FIFO sequence. Dedicated work is dual-posted to both a
  dedicated queue and the general queue so general threads can help while
  dedicated threads remain reserved. A shared `Future` and claim lock ensure only
  one thread runs each job.
- `AsyncPool` keeps a target number of async workers alive, logs and consumes
  worker exceptions in the supervisor loop, and shields teardown cancellation.
  `QueuedAsyncPool` adds job/result queues plus per-job started/done state and
  cancellation flags.
- `LimitedSemaphore` bounds both active and waiting requests. It raises
  `LimitedSemaphoreFullError` before enqueueing when no waiting slot is left;
  full-node request handlers use this as a DoS/backpressure signal.
- `task_referencer`, `safe_cancel_task`, `log_exceptions`, `task_timing`, and
  related helpers exist to make async lifecycle explicit. Fire-and-forget tasks
  should generally be referenced or awaited through these helpers to avoid silent
  GC/cancellation surprises.

## Cache And Bounded-State Semantics

- `LRUCache` is access-order LRU, but `LRUSet` and `LRUKeyedListCache` use FIFO
  key eviction despite the `LRU` prefix. Do not assume reads promote entries in
  the latter two structures.
- `LRUKeyedListCache` is a bounded dict-of-lists with per-key entry limits,
  total-entry accounting, optional monotonic-time TTL, and insertion-order-based
  expiry. Full-node future-object and peer-advertisement caches rely on these
  limits as resource controls, not just memory optimizations.
- `BlockCache` implements consensus blockchain interface protocols over an
  in-memory `BlockRecord` map plus height map and delegates MMR-root computation
  to an injected `MMRManagerProtocol`. It is used as an augmented or lightweight
  chain view; it must remain consistent between header hash, height, and MMR
  manager updates.

## Config, Filesystem, And Process Setup

- Config loading retries YAML reads even though a lock should prevent partial
  reads. Missing config exits the process by default, so library-style callers
  must pass `exit_on_error=False` if they need exceptions instead.
- `lock_and_load_config()` holds the config lock only around load. `save_config()`
  assumes the caller already acquired that lock. Code that loads, mutates, and
  saves config should keep the lock over the whole read-modify-write sequence.
- CLI overrides are generated from flattened config keys and skip list values.
  Nested config path syntax uses dots for CLI override flattening and colons for
  `traverse_dict()`, so these are not interchangeable.
- `process_config_start_method()` validates configured multiprocessing start
  methods and logs the selected method. Full-node and wallet process-pool code
  depends on this to avoid invalid platform choices.
- `write_file_async()` fsyncs temp-file contents, moves into place with retries,
  chmods the final path, and cleans up temp files. It does not fsync the parent
  directory; callers needing crash-proof directory-entry durability would need a
  stronger primitive.

## Network, RPC, And Trust Helpers

- `WebServer.create()` wraps `aiohttp.web.Application`/`AppRunner`/`TCPSite` and
  records the actual ephemeral listen port after start. The current branch is
  sensitive to aiohttp site/server creation behavior; preserve the invariant that
  an ephemeral port request resolves to the selected bound IPv4/IPv6 port from runner addresses.
- `close()` schedules cleanup in a referenced task; callers must call
  `await_closed()` to observe shutdown completion. Treating `close()` as already
  awaited can leak server resources in tests or service shutdown.
- `is_trusted_peer()` trusts localhost unless in testing mode, explicit node-id
  entries, or configured CIDRs. This helper feeds server/RPC behavior, so changes
  affect ban/exemption and privileged-connection paths.
- DNS resolution prefers IPv4 by default but can prefer IPv6. Host strings that
  are already IP addresses skip DNS. `parse_host_port()` uses URL parsing to
  support IPv6 bracket syntax and rejects missing host or port.
- `ws_message.py` defines daemon-style websocket envelopes. `request_id` is a
  random `bytes32` hex string; `format_response()` swaps origin/destination and
  marks `ack=True`.

## Error Surface

- `Err` is a shared negative/positive enum across consensus, protocol, mempool,
  and API errors. The sign historically groups temporary versus permanent
  categories, but ban/disconnect policy is decided at each handling site, not by
  the sign alone: `INVALID_PROTOCOL_MESSAGE = -4` is negative yet explicitly
  bans. Renumbering or reclassifying values changes behavior and
  wire/user-visible diagnostics.
- `ValidationError`, `ConsensusError`, `ProtocolError`, and `ApiError` all carry
  an `Err` code but are handled by different subsystems. Do not collapse them
  without auditing ban logic, RPC error formatting, and validation call sites.
- Keychain exceptions are intentionally granular because CLI/daemon UX needs to
  distinguish locked keyring, bad passphrase, duplicate fingerprint/label,
  missing secrets, unsupported file version, and OS credential-store failures.

## Fragility Hotspots

- Changing `streamable` parse/stream/coercion behavior without checking protocol,
  wallet request, consensus-adjacent, and test fixtures. The blast radius is much
  larger than `chia/util/streamable.py`.
- Simplifying `DBWrapper2` cancellation shields, nested savepoint behavior,
  same-task writer reads, or reader pooling. These are transaction correctness
  contracts for persistent stores.
- Treating cache bounds and limited semaphores as arbitrary tuning constants.
  Several callers use them as peer-driven resource-exposure limits.
- Moving keyring prompts or passphrase caching without checking daemon and CLI
  call paths. Some storage methods can currently prompt indirectly.
- Adding inline imports to avoid cycles in keychain/keyring code without
  documenting the cycle. This area already has a few local imports caused by
  circular dependencies; new ones should be a last resort.
- Editing config read-modify-write flows without keeping the file lock across
  the full mutation. Atomic writes protect file replacement, not logical lost
  updates between processes.

## Test And Audit Strategy

- `chia/_tests/core/util/test_streamable.py` covers decorator, binary, JSON,
  list-limit, enum, and type-conversion behavior for streamables.
- `chia/_tests/core/test_db_validation.py`, `chia/_tests/core/test_db_conversion.py`,
  store tests under `chia/_tests/core/full_node/stores/`, wallet RPC tests, and
  data-layer tests exercise `DBWrapper2` under realistic store usage.
- `chia/_tests/util/test_lru_cache.py` documents bounded keyed-list cache
  semantics.
- `chia/_tests/core/full_node/test_full_node_api_rate_hardening.py` and full-node
  tests exercise `LimitedSemaphore` behavior under request pressure.
- Keychain behavior is spread across command, daemon, simulator, and wallet
  tests because key storage is a shared local environment dependency.

## Source Pointers

For exact infrastructure behavior, read the owning utility in `chia/util/` rather than copied notes; the highest-impact primitives are listed in the Landmarks table above. Related non-landmarked files: `chia/util/file_keyring.py` (encrypted key file format) and `chia/util/errors.py` (`Err` enum).
