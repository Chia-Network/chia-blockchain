# Chia Seeder Module Context

Verified: 2026-07-02 against 6526ab6f18. If source contradicts this doc, trust source and update the doc.

`chia/seeder/` is two cooperating services over one SQLite database: a crawler
that joins the Chia P2P network as a minimal full node to discover reachable
peers, and an authoritative DNS server that serves the crawler's reliable-peer
set. It is bootstrap infrastructure, not a consensus or identity authority.
Every peer address it records or returns remains advisory until a receiving
full node performs normal DNS/introducer ingestion, connection, handshake,
network-id checks, and address-manager policy.

## When To Read This

Read this for crawler peer discovery, crawler DB scoring/persistence, DNS seed responses, seeder RPC observability, and bootstrap-peer publication behavior. For generic P2P connection policy, also read `chia-server.md` and `chia-protocols.md`.

## Implementation Authority

- `Crawler` owns P2P crawling state, the background crawl loop, peer-gossip
  ingestion, version/height/TLS observations, and the in-memory caches that are
  periodically flushed to `CrawlStore`.
- `CrawlerAPI` is a deliberately stubby full-node API surface. It registers many
  full-node and wallet message handlers so generic `ChiaServer` protocol
  dispatch accepts expected traffic, but only `new_peak` mutates crawler state.
  The crawler actively calls `FullNodeAPI.request_peers`; it does not serve
  peers or blockchain data to remote nodes.
- `CrawlStore` is the persistence and scoring boundary. It owns the `peer_records`,
  `peer_reliability`, and `good_peers` tables plus mirrored in-memory maps.
  `good_peers` is the crawler-to-DNS handoff table.
- `DNSServer` owns DNS protocol behavior and does not crawl. It periodically
  reloads `good_peers`, merges configured `static_peers`, splits them into IPv4
  and IPv6 lists, and rotates answers through round-robin pointers under a lock.
- Generic `Service` / `ChiaServer` still own TLS identity, handshakes, node-type
  checks, rate limits, request/response validation, bans, connection lifetime,
  daemon/RPC wiring, and shutdown ordering for the crawler side.

## Service Shape

- `start_crawler.create_full_node_crawler_service()` builds a normal
  `Service[Crawler, CrawlerAPI, CrawlerRpcApi]` with `NodeType.FULL_NODE`,
  `service_name="full_node"`, and the seeder service config. This is why the
  crawler can connect to full nodes and use full-node protocol messages without
  a separate crawler node type.
- The crawler advertises `seeder.port` but connects discovered candidates on
  `seeder.other_peers_port`. The crawl loop ignores records whose stored port is
  not `other_peers_port`, so changing that config changes crawl eligibility.
- `Crawler.manage()` lowers `server.config["peer_connect_timeout"]` from
  `seeder.peer_connect_timeout`, opens the SQLite DB, bootstraps configured
  hosts, and starts the crawl task unless `start_crawler_loop=False`.
- The DNS service is independent of `Service` and uses low-level asyncio UDP and
  TCP protocols. It binds wildcard UDP/TCP sockets with platform-specific IPv4
  handling.
- Both crawler and DNS default to the same `crawler_db_path`; running only one
  side is valid but DNS will wait/retry until reliable peers or static peers are
  available.

## Crawl Data Flow

- Bootstrap peers are inserted as unresolved host/IP strings with placeholder
  version/timestamp state and no reachability evidence.
- Each crawl batch asks `CrawlStore.get_peers_to_crawl(...)` for peers whose
  reliability ban/ignore windows expired and whose last try/connect time is old
  enough. IPv6 records use a shorter retry delta than IPv4, and recently selected
  records are temporarily suppressed.
- The crawler opens a bounded number of concurrent outbound client tasks. On connect it
  records the peer's short Chia version, requests `RespondPeers`, waits briefly
  for a qualifying `new_peak`, then closes the connection.
- `new_peak` is the crawler's reachability signal. A peer is marked connected
  only when its peer IP parses as an IP address and the announced height is at
  least `seeder.minimum_height`; TLS version is also recorded. If no qualifying
  peak arrives, the attempt is scored as a failure.
- `RespondPeers` entries update `best_timestamp_per_peer` and create new
  candidates only when their advertised timestamp is within the source-defined
  freshness horizon. That horizon also gates version reporting and RPC-visible
  `best_timestamp_per_peer` data.
- After each batch the crawler writes peer records, rewrites `good_peers` from
  current reliability scores, prunes records older than `crawler.prune_peer_days`
  by `best_timestamp`, clears temporary caches, clears `server.banned_peers`, and
  emits a `crawl_batch_completed` state change.

## Reliability And Persistence Semantics

- `PeerReliability` maintains exponentially decayed success signals over several
  source-defined windows. A peer can be reliable with a small early sample or
  with progressively lower reliability thresholds over longer windows.
- Failures update ignore/ban windows only when the peer is not currently
  reliable. The worst long-window failure cases can be ignored or banned for
  source-defined durations.
- `PeerRecord` is streamable but mutable in practice through `object.__setattr__`
  in `update_version()`. Do not assume frozen dataclass immutability protects
  record state inside `CrawlStore`.
- `CrawlStore.add_peer(save_db=False)` updates only memory. Durable writes happen
  through `Crawler.save_to_db()`, which calls `load_to_db()` and
  `load_reliable_peers_to_db()` with retry-on-exception behavior.
- The schema has migration quirks: `tls_version` is added with `ALTER TABLE` and
  duplicate-column errors are ignored. Treat persisted crawler DBs as long-lived
  operational state, not throwaway cache, when changing columns or insert order.
- `good_peers` stores only IP strings. DNS output does not include ports; clients
  receiving DNS answers use their own network default port logic.

## DNS Semantics

- `DNSServer.dns_response()` answers only the configured domain and subdomains.
  Requests outside that zone return `REFUSED`; unknown names inside the zone
  return `NXDOMAIN`; valid answers always include NS and SOA authority records.
- `static_peers` are merged into each refresh. Literal IPs are accepted directly;
  hostnames are resolved for both `A` and `AAAA` with a source-defined lifetime
  when the async resolver is available.
- Peer answer rotation is round-robin per address family, not random per query.
  `CrawlStore.get_good_peers()` shuffles DB results before DNS loads them, then
  DNS pointer state controls fairness between refreshes.
- Exact response limits, EDNS0 handling, and truncation behavior live in `chia/seeder/dns_server.py`.

## RPC And Observability

- `CrawlerRpcApi` exposes `/get_peer_counts` and `/get_ips_after_timestamp`.
  Counts are derived from in-memory five-day crawler caches, not directly from
  SQLite, so they reflect the running crawler's latest processed batch.
- `get_ips_after_timestamp` sorts IP strings lexicographically after timestamp
  filtering and supports `offset`/`limit`. It requires an `after` timestamp.
- State-change websocket payloads are emitted only for `crawl_batch_completed`
  and `loaded_initial_peers`; missing change data is replaced with
  `/get_peer_counts` output.
- The crawler's log summary deliberately reports both gossiped recent addresses
  and reachable recent handshakes. Keep those concepts separate: a peer can be
  seen in `RespondPeers` without being reachable or DNS-eligible.

## Fragility Hotspots

- Highest-risk edits are changes that mark peers reliable from weaker evidence,
  broaden `CrawlerAPI` into serving full-node data, remove `minimum_height` or
  IP validation from `new_peak`, or let unbounded peer lists flow into memory or
  DNS responses.
- The crawler treats peer-gossiped timestamps as freshness hints. Keep the
  five-day filter and pruning behavior explicit; stale or future-biased gossip
  should not become DNS output without fresh reachability evidence.
- The crawler currently clears `server.banned_peers` after each batch. Changes to
  ban handling need to account for crawler-specific connection churn without
  weakening generic `ChiaServer` behavior elsewhere.
- DNS tests cover TCP/UDP, IPv4/IPv6 listeners, A/AAAA/ANY/NS/SOA responses,
  static IPs, static hostname resolution, DB-driven peer loading, and error
  cases. Some broad DNS query/error-condition tests are skipped as flaky, so
  changes in protocol parsing or truncation need focused fresh verification.
- Crawler tests assert loop startup controls, handling of unknown protocol
  messages, `new_peak` reachability effects, DB-to-good-peer promotion, pruning,
  and RPC pagination. Use `tools/pytest` and async `time_out_assert` patterns
  for behavior that depends on service convergence.

## Source Pointers

- Crawler service state and peer scoring: `chia/seeder/crawler.py`, `chia/seeder/crawl_store.py`, `chia/seeder/peer_record.py`.
- Crawler peer API and RPC: `chia/seeder/crawler_api.py`, `chia/seeder/crawler_rpc_api.py`.
- DNS server behavior: `chia/seeder/dns_server.py`.
- Service startup: `chia/seeder/start_crawler.py`, `chia/seeder/crawler_service.py`.
