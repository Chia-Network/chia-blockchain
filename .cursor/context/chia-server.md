# Chia Server Module Context

Verified: 2026-07-02 against 6526ab6f18. If source contradicts this doc, trust source and update the doc.

`chia/server/` is the network boundary where remote TLS peers become typed protocol calls on node APIs. Its core safety property is distributed across TLS identity, handshake/capability negotiation, per-peer message routing, rate limiting, peer admission, and address discovery. Do not reason about any one of these in isolation.

## When To Read This

Read this for P2P websocket connections, TLS identity, peer lifecycle, handshake/capability negotiation, rate limiting, peer discovery, bans, and address-manager behavior. For message schemas, read `chia-protocols.md`; for semantic acceptance of a message, read the receiving service context.

## Landmarks

| file                                | owns                                                  |
| ----------------------------------- | ----------------------------------------------------- |
| `chia/server/ws_connection.py`      | per-peer protocol, request/response, rate-limit state |
| `chia/server/server.py`             | connection admission, bans, TLS identity, broadcast   |
| `chia/server/rate_limits.py`        | v1/v2 per-message + aggregate accounting              |
| `chia/server/rate_limits_v3.py`     | in-flight-window v3 limiter                           |
| `chia/server/rate_limit_numbers.py` | rate-limit tables/constants                           |
| `chia/server/address_manager.py`    | peer address-book state machine                       |
| `chia/server/node_discovery.py`     | DNS/introducer discovery orchestration                |

## Implementation Authority

- `WSChiaConnection` is the per-peer protocol authority. It owns handshake-derived peer type/capabilities, request nonce allocation, pending-response matching, v2/v3 rate-limit state, API task lifetime, and raw websocket parsing.
- `ChiaServer` is the process-local connection authority. It owns TLS context selection, node identity, inbound/outbound admission, duplicate/self connection rejection, bans, broadcast validation, and connection shutdown callbacks.
- API classes own message semantics, but only after `ApiMetadata` has selected the handler, decoded the streamable payload, and `ProtocolMessageTypeToNodeType` has checked that the peer's negotiated `NodeType` is allowed to send that message.
- Peer discovery is advisory, not trusted. `FullNodeDiscovery` bounds and sanitizes peer lists before they reach `AddressManager`; `AddressManager` decides whether and when an address becomes tried/good.

## Handshake And Identity Contracts

- Peer identity is the SHA-256 fingerprint of the TLS certificate used on the websocket. `connection_added()` replaces an existing connection with the same peer id; host/port alone are not the identity boundary.
- Handshake ordering matters. Outbound peers send `handshake` first; inbound peers read first and then reply. If both sides negotiate `RATE_LIMITS_V3`, `configure_window_sizes` exchange must happen immediately before normal inbound/outbound/message-handler tasks start.
- `connection_type`, `peer_capabilities`, `peer_server_port`, `version`, and `protocol_version` are not valid until `perform_handshake()` completes. Any code path that calls `call_api()`, peer-type filtering, or discovery bookkeeping before that point is using uninitialized protocol state.
- Full nodes enforce hard-fork capability at inbound admission after handshake, using current peak height. This is an admission rule, not part of TLS authentication or generic protocol decoding.
- Capability parsing is permissive: unknown capability ids are ignored and duplicate/conflicting entries are normalized by parser rules. Do not assume the peer's raw capability list is canonical.

## Message Routing And Request State

- Requests and responses share an id space split by direction. This split is what prevents both peers from generating the same local request id under normal operation.
- `send_request()` registers `pending_requests` before enqueueing the message; inbound messages with matching ids are treated as responses, not API calls. Late responses to timed-out ids are discarded through `timed_out_requests` to avoid reusing an id while a stale response may still arrive.
- `call_api()` validates the response type against `protocol_state_machine.VALID_REPLY_MESSAGE_MAP` and bans on mismatches. Fire-and-forget broadcasts must not use request/response message types; `ChiaServer.validate_broadcast_message_type()` treats that as an internal protocol error and closes relevant peers.
- API handler dispatch has two separate gates: existence in the local API metadata and permission for the sender node type. Adding a protocol message requires updating the protocol enum, API metadata decorators, node-type sender map, and request/response state machine when replies are expected.
- `execute_task=True` handlers are intentionally not cancelled by normal connection close through `cancel_tasks()`. They also bypass the normal API timeout path. This flag is a lifecycle contract, not just a scheduling optimization.

## Rate Limiting Model

- v1/v2 rate limiting is per-message plus aggregate non-transaction accounting over a time slot. Incoming messages always commit counters, even when they exceed limits; outgoing messages commit counters only if allowed to send.
- `Unlimited` means "no frequency limit, size limit only"; it relies on protocol state and unsolicited-response handling elsewhere. Treating an unlimited response type as generally safe removes an important implicit coupling.
- v3 rate limiting replaces v2 only for message types listed in `rate_limits_v3` and only when both peers advertise `RATE_LIMITS_V3`. It is in-flight-window based, not time-window based.
- v3 request messages with a finite `window_size` increment outbound `in_flight` when sent and decrement in `send_request()`'s `finally`. Inbound finite-window messages increment `receive_window` around `_api_call()` and decrement in its `finally`. These decrements are the leak-prevention invariant.
- v3 response/unlimited messages are allowed to carry the request nonce without being in `pending_requests`; this special case exists because responses reuse the peer's request id. Removing that distinction can misclassify legitimate responses or bypass the intended limiter path.
- Localhost and configured exempt networks are exempt from disconnect/ban consequences, but v3-supported messages still bypass v2 accounting when v3 is negotiated. Exemption changes enforcement, not protocol shape.

## Connection Lifecycle

- `close()` is idempotent but still calls the server close callback for already-closed connections. The callback performs ban insertion and removal from `all_connections`, so "already closed" must not mean "skip server cleanup."
- `ChiaServer.connection_closed()` refuses to ban localhost, trusted peers, and exempt networks even when a lower layer requested a ban. Audit ban behavior at the server callback, not at the call site that passed `ban_time`.
- `incoming_connection()` waits for `connection.wait_until_closed()` before returning the websocket response. Long-lived inbound requests therefore tie request lifetime to connection lifetime by design.
- `Service.manage()` shutdown order is intentional: release UPnP in the background, cancel reconnect loop, close peer connections, close RPC, await `ChiaServer`, then await RPC. Reordering can leave reconnect or RPC paths racing against closed peer state.
- `chia_policy.set_chia_policy()` mutates the process event-loop policy and wraps server creation with `PausableServer`. Connection limits are enforced at accept/pause level, separately from ChiaServer's node-type inbound slot limits.

## Peer Discovery And Address Book

- `FullNodeDiscovery` is the orchestrator; `AddressManager` is the state machine. Discovery decides when to query DNS/introducers, when to make normal versus feeler connections, and when to relay addresses. AddressManager decides table placement, collision handling, retries, and selection probability.
- Peer lists are bounded at response and ingestion boundaries before reaching address-manager state. Oversized host strings and invalid IPs are dropped before `IPAddress` construction.
- Received peer timestamps are normalized or penalized depending on source and validity. This avoids treating peer-supplied freshness as authoritative.
- Full-node address sharing is intentionally asymmetric for fingerprinting resistance: `request_peers()` serves peers only in the intended outbound-neighbour flow, and `neighbour_known_peers` suppresses re-relaying the same address to the same neighbour.
- `AddressManager` invariants depend on mutating matrices through `_set_new_matrix()` and `_set_tried_matrix()` so the sparse-position sets stay synchronized. Direct matrix writes can make selection loops believe entries exist where none do, or miss existing entries.
- Private subnets are rejected by default in `AddressManager` unless discovery explicitly enables private networks from introducer config. Do not add bypasses in discovery without checking this address-book policy.

## External Inputs And Persistence

- Websocket frames, streamable payloads, peer lists, DNS answers, introducer responses, configured peer hostnames, and the persisted peers file are all untrusted at this boundary.
- The peers file supports both the deprecated `PeerDataSerialization` migration path and the current binary `AddressManager.serialize_bytes()` format. Load failures fall back to a fresh address manager rather than aborting service startup.
- Public IP discovery in `ChiaServer.get_peer_info()` depends on external HTTPS services and returns `None` on failure. Callers must handle absence of self-advertisable peer info without degrading core connectivity.
- UPnP runs in a side thread and is best-effort. It should not be used as a readiness signal for peer networking.

## Fragility Hotspots

- Highest-risk edits: changing handshake task start order, changing request-id reuse rules, moving v3 window increments/decrements, broadening `Unlimited`, skipping response-type validation, or bypassing `ProtocolMessageTypeToNodeType`.
- Connection cleanup bugs often show up as stale `all_connections`, stuck `pending_requests`, leaked v3 `in_flight` windows, or reconnect loops that keep targeting already-connected peers under a different hostname.
- Peer discovery bugs often look non-deterministic because selection uses randomized bucket placement, Poisson feeler timing, per-network-group filtering, and collision testing. Tests should control randomness/time or assert invariants rather than exact peer order.
- AddressManager counts (`new_count`, `tried_count`, `ref_count`, matrix entries, used-position sets, `random_pos`) are a single consistency domain. Any helper that updates one must update all related structures under the lock exposed by the async public methods.

## Source Pointers

For exact websocket dispatch, peer-close behavior, rate-limit tables, and discovery/address-book rules, read the source files in `chia/server/` listed in the Landmarks table above.
