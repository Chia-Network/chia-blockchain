# Chia Introducer Module Context

Verified: 2026-07-02 against 6526ab6f18. If source contradicts this doc, trust source and update the doc.

`chia/introducer/` is a small bootstrap service whose job is to help wallets,
farmers, and full nodes discover full-node peers. It is not an address-book
authority and does not validate blockchain state. Treat every address it
learns, vets, or returns as advisory until the receiving node's discovery and
connection logic accepts it.

## When To Read This

Read this for introducer peer collection, TCP vetting, DNS fallback, introducer request/response protocol behavior, and bootstrap service startup. For receiver-side peer ingestion and address-manager policy, also read `chia-server.md`.

## Implementation Authority

- `Introducer` owns service-local configuration and the background vetting loop:
  `max_peers_to_send`, `recent_peer_threshold`, `default_port`, DNS fallback
  servers, and the resolver used for DNS seeder lookups.
- `IntroducerAPI` owns the single P2P handler,
  `request_peers_introducer`, and is responsible for filtering the server's
  introducer peer set down to vetted peers before returning
  `RespondPeersIntroducer`.
- `ChiaServer`, not `Introducer`, owns the in-memory peer set. It creates
  `IntroducerPeers` only when the local node type is `INTRODUCER`, and it adds a
  peer only after a successful inbound handshake whose negotiated peer type is
  `FULL_NODE`.
- `IntroducerPeers` is a volatile set, not durable storage. Entries are keyed by
  `(host, port)` through `VettedPeer.__hash__`/`__eq__`, carry local vetting
  counters, and disappear on process restart.
- `FullNodeDiscovery` / wallet discovery own ingestion of introducer responses.
  Introducer-returned timestamps are normalized, invalid hosts are
  dropped, wrong-network default ports are filtered, and addresses enter the
  "new" table as untrusted candidates.

## Peer Collection And Vetting

- The introducer learns candidates passively from inbound full-node
  connections. A peer that never connects to the introducer as a full node is
  not eligible to be returned from the in-memory peer set.
- Vetting is a TCP reachability check only: the service periodically samples
  recent peers, opens a raw TCP connection to `host:port` with a configured
  timeout, then closes it. It does not perform a Chia handshake or verify node
  type during vetting.
- Positive `vetted` values mean consecutive successful reachability checks;
  negative values mean consecutive failures. Successful peers are rechecked
  after the configured interval; failed peers are not retried until the
  configured cooldown passes and are removed after repeated failures.
- `recent_peer_threshold` gates what can be served. The API asks
  `IntroducerPeers` for recently added peers using this threshold, while the
  vetting loop samples a wider window than the DNS publication threshold so older
  candidates can be refreshed before aging out of responses.
- API responses deliberately skip the requesting peer's own `(host, port)`.
  Keep that exclusion when changing response construction; returning a client
  to itself wastes bootstrap attempts and can amplify duplicate/self-connection
  churn.

## DNS Fallback Semantics

- DNS fallback is used only when the vetted in-memory response has fewer than
  `max_peers_to_send` peers. The introducer queries one randomly chosen DNS
  seeder for both `A` and `AAAA` records and wraps each IP with the configured
  `default_full_node_port`.
- If `introducer.dns_servers` is omitted or empty on mainnet, startup injects
  `dns-introducer.chia.net`. Other networks depend on explicit config.
- DNS answers are returned with normalized timestamps, the same trust level as
  introducer peers on the receiving side. Do not treat DNS fallback as stronger
  evidence than the local vetting set.
- `get_peers_from_dns()` currently lets resolver exceptions propagate to the API
  handler. A failing DNS query can therefore fail the request instead of
  returning the partial vetted peer list unless callers add explicit handling.

## Wire Protocol Contracts

- The introducer protocol has exactly one request/reply pair:
  `request_peers_introducer` -> `respond_peers_introducer`.
- Sender authorization is asymmetric. `WALLET`, `FARMER`, and `FULL_NODE` may
  send `request_peers_introducer`; only `INTRODUCER` may send
  `respond_peers_introducer`.
- Runtime response validation depends on
  `protocol_state_machine.VALID_REPLY_MESSAGE_MAP`; protocol evolution must keep
  payload dataclasses, message IDs, sender map, API/stub decorators,
  rate limits, and reply map in sync.
- Rate limits are small for requests and bounded for responses. Exact values
  belong in the rate-limit source tables.
- Clients use introducer connections as short-lived bootstrap links. Full nodes
  send the request from `FullNodeDiscovery._introducer_client()`, ingest returned
  peers with `is_full_node=False`, and close the introducer peer after handling
  the response. Wallets follow the same close-after-response pattern.

## Startup And Service Shape

- `start_introducer.create_introducer_service()` builds a normal
  `Service[Introducer, IntroducerAPI, FullNodeRpcApi]` with
  `NodeType.INTRODUCER`. The RPC type alias is shared with full node service
  plumbing; this module does not define a dedicated introducer RPC surface.
- The service uses public SSL paths from the full-node certificate config and
  normal ChiaServer handshake/rate-limit machinery. Introducer-specific behavior
  starts only after the connection has passed the generic server admission path.
- `Introducer.server` is a non-null property that raises `RuntimeError` before
  `set_server()` has run. Code that needs to tolerate pre-service wiring should
  inspect `_server` or be structured to run only after service setup, rather
  than comparing `introducer.server is None`.
- `Introducer.manage()` starts the vetting task and cancels it on shutdown. The
  task uses `_shut_down` checks plus cancellation; edits should preserve both so
  service teardown does not wait on long sleeps or stuck DNS/TCP work.
- `on_connect()` and state-change callbacks are intentionally no-ops today. The
  meaningful connect side effect is in `ChiaServer.incoming_connection()`, which
  adds inbound full nodes to `server.introducer_peers`.

## Fragility Hotspots

- Do not broaden which peer types can populate `IntroducerPeers` without a clear
  reason. Letting wallets/farmers/self-reported peers seed the introducer would
  weaken bootstrap quality and make Sybil address injection easier.
- Keep introducer outputs bounded by `max_peers_to_send` and receiver-side peer
  ingestion limits. Peer-list payloads are adversarial resource surfaces even
  though `RespondPeersIntroducer` is a simple streamable list.
- Avoid treating `vetted` as proof of a valid Chia full node. It only proves a
  recent TCP accept on that address; receiving nodes must still connect,
  handshake, check network ID, and apply address-manager policy.
- DNS failure behavior and partial-response behavior are worth testing around
  because the current API awaits DNS after collecting vetted peers. A resolver
  exception can prevent otherwise usable vetted peers from being sent.
- Tests that exercise discovery should control DNS and async convergence. Existing
  harnesses commonly disable introducer DNS in setup and use fake resolvers for
  fallback behavior.

## Source Pointers

- Introducer service state and vetting: `chia/introducer/introducer.py`.
- Peer request/reply handling: `chia/introducer/introducer_api.py`.
- Service startup and wiring: `chia/introducer/start_introducer.py`, `chia/introducer/introducer_service.py`.
