# Networking & Peer Protocol — Deep Context

> Attach when touching `chia/server/`, `chia/protocols/`, connection handling,
> rate limiting, or peer discovery.

## File map

### `chia/server/`

| File                       | Lines | Role                                                 |
| -------------------------- | ----- | ---------------------------------------------------- |
| `server.py`                | ~900  | `ChiaServer`: connection management, message routing |
| `ws_connection.py`         | ~790  | `WSChiaConnection`: single peer connection           |
| `rate_limits.py`           | ~160  | `RateLimiter`: per-connection rate enforcement       |
| `rate_limit_numbers.py`    | ~200  | Rate limit values per message type                   |
| `chia_policy.py`           | ~370  | Custom asyncio event loop policy, connection limits  |
| `node_discovery.py`        | ~850  | `FullNodePeers`: peer discovery and management       |
| `address_manager.py`       | ~1050 | Address book for known peers                         |
| `address_manager_store.py` | ~15   | Address persistence                                  |
| `api_protocol.py`          | ~117  | `ApiProtocol`, `ApiMetadata`, `@request` decorator   |
| `capabilities.py`          | ~20   | Capability detection                                 |
| `introducer_peers.py`      | ~65   | Introducer peer handling                             |
| `resolve_peer_info.py`     | ~50   | DNS resolution                                       |
| `start_service.py`         | ~350  | Service lifecycle management                         |
| `signal_handlers.py`       | ~100  | Graceful shutdown                                    |
| `ssl_context.py`           | ~25   | TLS configuration                                    |
| `upnp.py`                  | ~100  | UPnP port forwarding                                 |

### `chia/protocols/`

| File                                    | Lines | Role                                            |
| --------------------------------------- | ----- | ----------------------------------------------- |
| `protocol_message_types.py`             | ~147  | `ProtocolMessageTypes` enum (109 message types) |
| `protocol_state_machine.py`             | ~88   | Valid request→response map, import-time check   |
| `protocol_message_type_to_node_type.py` | ~230  | Message type → allowed node type mapping        |
| `outbound_message.py`                   | ~25   | `Message`, `NodeType`, `make_msg()`             |
| `protocol_timing.py`                    | ~10   | Ban duration constants                          |
| `shared_protocol.py`                    | ~80   | `Handshake`, `Capability`, `protocol_version`   |
| `full_node_protocol.py`                 | ~217  | Full node ↔ full node message types            |
| `wallet_protocol.py`                    | ~400  | Wallet ↔ full node message types               |
| `farmer_protocol.py`                    | ~75   | Farmer ↔ full node message types               |
| `harvester_protocol.py`                 | ~190  | Farmer ↔ harvester message types               |
| `timelord_protocol.py`                  | ~80   | Full node ↔ timelord message types             |
| `solver_protocol.py`                    | ~15   | Solver protocol                                 |
| `pool_protocol.py`                      | ~110  | Pool protocol messages                          |
| `introducer_protocol.py`                | ~15   | Introducer protocol                             |
| `fee_estimate.py`                       | ~50   | Fee estimate messages                           |

---

## `WSChiaConnection` — Per-peer connection

**Location**: `server/ws_connection.py`

### Key properties

- WebSocket-based (aiohttp)
- Mutual TLS authentication
- `local_type: NodeType` — our node type
- `peer_node_id: bytes32` — peer identity
- `is_outbound: bool`
- `peer_capabilities: list[Capability]`

### Constants

- `LENGTH_BYTES = 4` — message length prefix (max ~4 GiB per message)
- `MAX_VERSION_STRING_BYTES = 128`
- `MAX_PENDING_COMPACT_VDFS = 100`

### Message flow

1. Receive raw bytes over WebSocket
2. Parse length prefix + `Message` (type + id + data)
3. Look up handler in `ApiMetadata.message_type_to_request`
4. Deserialize data via `Streamable.from_bytes()`
5. Call handler, send reply if expected

### Error handling & banning

- `ApiError` from handlers is converted to an `error` response (not an automatic ban)
- `ConsensusError` from handlers → close + ban for `CONSENSUS_ERROR_BAN_SECONDS`
- Other unhandled handler exceptions → close + ban for `API_EXCEPTION_BAN_SECONDS`
- Rate limit exceeded (for full node inbound peers) → close + ban for `RATE_LIMITER_BAN_SECONDS`
- Protocol response mismatch (`message_response_ok` failure) → `ban_peer_bad_protocol()` using `INTERNAL_PROTOCOL_ERROR_BAN_SECONDS`

### Protocol state machine validation

On receiving a reply, `message_response_ok()` checks that the response type is
valid for the original request type (defined in `VALID_REPLY_MESSAGE_MAP`).

---

## Rate limiting

**Location**: `server/rate_limits.py`, `server/rate_limit_numbers.py`

### Two-tier system

**Per-message-type limits** (`RLSettings`):

- `frequency`: max count per 60 seconds
- `max_size`: max bytes per single message
- `max_total_size`: max cumulative bytes per 60 seconds (optional)
- `aggregate_limit`: whether to count against the global aggregate

**Aggregate limit** (across all non-tx message types):

- 1000 messages per minute
- 100 MB per minute

### Transaction messages exempt from aggregate

`new_transaction`, `request_transaction`, `respond_transaction`,
`send_transaction`, `transaction_ack` — these have their own per-type limits
and do NOT count against the aggregate.

### Key rate limits (v1)

| Message                   | Freq/min | Size   | Total/min |
| ------------------------- | -------- | ------ | --------- |
| `new_transaction`         | 5000     | 100 B  | 500 KB    |
| `respond_transaction`     | 5000     | 1 MB   | 20 MB     |
| `send_transaction`        | 5000     | 1 MB   | —         |
| `respond_blocks`          | 100      | 50 MB  | —         |
| `respond_proof_of_weight` | 5        | 400 MB | —         |
| `new_peak`                | 200      | 512 B  | —         |
| `request_block`           | 200      | 100 B  | —         |
| `request_blocks`          | 100      | 100 B  | —         |

### V2 rate limits

Activated when both peers have `Capability.RATE_LIMITS_V2`. Overrides/extends
v1 with additional message types (wallet sync, mempool updates, etc.).

### `Unlimited` message types

Some response messages use `Unlimited` instead of `RLSettings` — they have a
per-message size limit but no frequency limit and are exempt from aggregate.

---

## Protocol state machine

**Location**: `protocols/protocol_state_machine.py`

### `VALID_REPLY_MESSAGE_MAP`

Maps request types to valid response types. Examples:

- `request_block` → `[respond_block, reject_block]`
- `request_blocks` → `[respond_blocks, reject_blocks]`
- `send_transaction` → `[transaction_ack]`
- `request_puzzle_state` → `[respond_puzzle_state, reject_puzzle_state]`

### `NO_REPLY_EXPECTED`

Fire-and-forget messages: `new_peak`, `new_transaction`,
`new_unfinished_block`, `new_signage_point_or_end_of_sub_slot`,
`request_mempool_transactions`, `new_compact_vdf`, `coin_state_update`,
`mempool_items_added`, `mempool_items_removed`.

### Import-time check

`static_check_sent_message_response()` verifies NO_REPLY_EXPECTED and
VALID_REPLY_MESSAGE_MAP don't overlap. Runs at module import.

---

## `ApiProtocol` and `@request` decorator

**Location**: `server/api_protocol.py`

### Handler registration

Each API class (e.g., `FullNodeAPI`) has a class-level `ApiMetadata` that maps
`ProtocolMessageTypes` → `ApiRequest`.

The `@metadata.request()` decorator:

- Registers the handler for its message type
- Auto-deserializes `bytes` → `Streamable` subclass
- Optionally passes raw bytes and/or peer reference
- `execute_task=True` means handler runs as a separate asyncio task

### Key flags

- `peer_required=True` — handler receives `WSChiaConnection` as parameter
- `bytes_required=True` — handler receives raw bytes (for forwarding)
- `execute_task=True` — non-blocking execution

---

## Connection limits

**Location**: `server/chia_policy.py`

- Default `global_max_concurrent_connections = 250`
- `set_chia_policy(connection_limit)` sets effective limit to `connection_limit + 100`
- Custom event loop policy (`ChiaProactorEventLoop` on Windows,
  selector-based on Unix) enforces connection limits at the socket level

---

## Peer discovery

**Location**: `server/node_discovery.py`

### `FullNodePeers`

- Maintains address book of known peers
- Periodic peer exchange via `request_peers` / `respond_peers`
- Connects to introducer nodes for bootstrapping
- DNS seeder support
- Preference for outbound connections to maintain network topology

---

## Message type → node type mapping

**Location**: `protocols/protocol_message_type_to_node_type.py`

Maps each `ProtocolMessageTypes` to the set of `NodeType`s allowed to send it.
Used to reject messages from unexpected node types (e.g., a wallet trying to
send `new_peak` which is a full-node-only message).

---

## `Handshake` protocol

**Location**: `protocols/shared_protocol.py`

### Fields

- `network_id: str`
- `protocol_version: str`
- `software_version: str`
- `server_port: uint16`
- `node_type: NodeType`
- `capabilities: list[tuple[uint16, str]]`

### `Capability` enum

Key capabilities: `BASE`, `BLOCK_HEADERS`, `RATE_LIMITS_V2`,
`NONE_RESPONSE`, `MEMPOOL_UPDATES`. Used for feature negotiation.
