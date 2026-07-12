# Chia Protocols Module Context

Verified: 2026-07-12 against a5647a9327e5. If source contradicts this doc, trust source and update the doc.

`chia/protocols/` is the wire-contract layer for Chia services. It does not usually enforce behavior itself; it defines the immutable `Streamable` payloads, numeric message IDs, node roles, request/reply state machine, and capability/version declarations that `chia/server/` and API classes enforce at runtime. Treat edits here as network compatibility changes, not local refactors.

## When To Read This

Read this for P2P/wallet/farmer/harvester/timelord/solver message schemas, numeric message ids, node-type sender authorization, request/reply mappings, shared handshake fields, capabilities, and protocol versioning. For API stub/concrete metadata parity, read `apis.md`; for connection lifecycle and rate-limit enforcement, read `server.md`; for message side effects, read the receiving service context.

## Landmarks

| file                                                   | owns                                     |
| ------------------------------------------------------ | ---------------------------------------- |
| `chia/protocols/protocol_message_types.py`             | canonical numeric wire message IDs       |
| `chia/protocols/protocol_state_machine.py`             | valid reply/no-reply message maps        |
| `chia/protocols/protocol_message_type_to_node_type.py` | sender node-type authorization           |
| `chia/protocols/shared_protocol.py`                    | handshake fields, capabilities, version  |
| `chia/protocols/outbound_message.py`                   | Message framing, make_msg() id=None      |
| `chia/protocols/wallet_protocol.py`                    | wallet sync/subscription payload schemas |
| `chia/protocols/full_node_protocol.py`                 | P2P sync/block/tx payload schemas        |
| `chia/protocols/harvester_protocol.py`                 | farmer-harvester schemas, Plot.param bit |

## Implementation Authority

- `ProtocolMessageTypes` is the canonical numeric wire namespace. Values are serialized as `uint8`; renumbering or reusing an old value changes the network protocol even if Python names still look correct.
- Payload dataclasses are schema contracts only. Validation of peer type, rate limits, request/reply sequencing, list-size limits, consensus validity, spend validity, and subscription limits happens in server/API/full-node/wallet code after deserialization.
- `outbound_message.Message` is the framing payload inside the websocket protocol: message type, optional request id, raw bytes. `make_msg()` intentionally sets `id=None`; request ids are assigned later by `WSChiaConnection`.
- `ProtocolMessageTypeToNodeType` is the sender authorization table. `WSChiaConnection` checks the negotiated peer `NodeType` against it before calling an API handler, so a schema being importable does not mean every node may send it.
- `protocol_state_machine.VALID_REPLY_MESSAGE_MAP` is the response authority for `call_api()`. `ChiaServer.validate_broadcast_message_type()` also uses it to prevent broadcasting request/response messages as fire-and-forget announcements.
- `ApiMetadata.request()` is the runtime binding from message type to handler and payload class. Concrete service APIs handle inbound dispatch, while `chia/apis/*_stub.py` metadata controls outbound request eligibility and response decoding. By default it derives the protocol type from the method name; unusual compatibility cases must pass `request_type=` explicitly.

## Evolution Lockstep

- Adding or changing a P2P message is a multi-file compatibility operation: update the payload schema, `ProtocolMessageTypes`, `ProtocolMessageTypeToNodeType`, API implementation/stub decorators, reply map/no-reply set if applicable, rate limits if peer-driven, tests, and usually `shared_protocol.protocol_version`.
- Import-time checks that reply-required and no-reply classifications do not overlap. Tests separately require every `ProtocolMessageTypes` entry to have sender authorization and v1/v2 rate-limit coverage. Preserve both as static invariants.
- Reply handling has two independent representations: decorators record `reply_types` for stubs/API metadata, while `VALID_REPLY_MESSAGE_MAP` controls runtime response validation. Updating only one gives future agents and tests contradictory protocol knowledge.
- Stub metadata and concrete API metadata must move together. A response type may need a local stub entry even when the concrete handler lives on the remote peer, because `call_api()` looks up response metadata before deserializing.
- The old/new harvester signage-point transition is a live compatibility pattern: `NewSignagePointHarvester2` intentionally uses the same message ID as `new_signage_point_harvester`, with selection based on protocol version. Do not assume one message ID maps to exactly one Python payload shape forever. `NewSignagePointHarvester2` carries `peak_height` and `last_tx_height`; V2 gating (skip before `HARD_FORK2_HEIGHT`) and V1 phase-out are keyed on the transaction-block height (`last_tx_height`), not peak height.
- Comments saying "also change protocol_message_types.py and protocol version" are not documentation noise. They mark schema changes that can break peers or third-party services if not coordinated.

## Handshake And Capabilities

- `shared_protocol.Handshake` establishes `network_id`, protocol version, software version, server port, node type, and capabilities. `WSChiaConnection` owns the ordering: outbound sends first, inbound replies, then normal tasks start.
- Protocol versions are keyed by local/remote `NodeType`, not by a single global version. Farmer/harvester compatibility checks are stricter because those protocols carry third-party/operator integrations.
- Capability parsing is permissive in `chia/server/capabilities.py`: unknown values are ignored, and duplicate/conflicting entries collapse according to parser rules. Do not treat the raw capability list as authoritative.
- `RATE_LIMITS_V3` has an ordering contract beyond simple negotiation. If both peers advertise it, `configure_window_sizes` must be exchanged immediately after handshake, and settings must remain non-empty and bounded.
- `ConfigureWindowSizes` uses protocol message numeric values in its settings list. It is therefore coupled to `ProtocolMessageTypes` and `chia/server/rate_limits_v3.py`; changing message IDs or adding v3-limited messages needs both sides updated.

## Trust Boundaries And Validation Assumptions

- All inbound protocol payload bytes are untrusted. `Streamable.from_bytes()` gives typed structure, not semantic trust. Hashes, heights, weights, VDFs, blocks, spend bundles, peer lists, fee estimates, and wallet subscription requests must still be validated by the receiving subsystem.
- Full-node sync messages (`new_peak`, weight proofs, blocks, unfinished blocks, signage point/EOS messages) are advertisements or data carriers. Consensus code decides validity; protocol schemas intentionally allow hostile but well-formed objects.
- Wallet protocol fields that look like history anchors (`height`, `header_hash`, `previous_height`, `fork_height`, `peak_hash`) are peer-supplied until the full node checks them against canonical chain state or detects reorg conditions.
- Transaction fee/cost data in `NewTransaction` is only a fetch/priority/accountability hint. The mempool pipeline recomputes spend validity, cost, and fees from the `SpendBundle`.
- Peer-list response messages (`RespondPeers`, `RespondPeersIntroducer`) cross an address-discovery trust boundary. Size, timestamp, address validity, and relay policy are server/discovery responsibilities, not schema guarantees.

## Request/Response Semantics

- A message requiring a reply must be sent through request paths with a nonce, not broadcast. Broadcast validation treats such messages as internal protocol errors and closes affected peers.
- A response type may be legal only for a specific request. `respond_block`, `reject_block`, `respond_blocks`, `reject_blocks`, wallet reject variants, and subscription responses are not interchangeable just because the payload shapes look related.
- `error` is a special response path returned from API handlers for `ApiError` on sufficiently new protocol versions. It is allowed from all node types and bypasses normal typed response decoding by returning `shared_protocol.Error`.
- `none_response` is currently mapped to no senders and the capability is disabled/commented out. Do not build new behavior on it without re-enabling the capability path and updating reply semantics.
- Late responses are routed by request id in `WSChiaConnection`, not by message type. Schema changes that alter which messages carry responses must preserve request-id expectations.

## Schema-Specific Gotchas

- Optional fields often encode protocol phase rather than convenience: `foliage_hash` distinguishes unfinished-block variants, wallet `previous_height` controls incremental sync/reorg behavior, and farmer/harvester source-data fields gate third-party signature workflows.
- Some list fields are adversarial resource surfaces. Limits are frequently applied by API decorators (`list_limits`) or rate-limit tables rather than by the dataclass itself. Adding a list to a message without a receiver-side limit changes DoS exposure.
- `wallet_protocol.CoinState` and `RespondToPhUpdates` are Rust-backed aliases kept in this module so network protocol tests still cover them. Do not replace them with local Python duplicates unless the Rust serialization contract changes too.
- `harvester_protocol.Plot.param()` encodes a backward-compatibility hack: the high bit of `Plot.size` distinguishes v2 plot strength from v1 k-size. Consumers rely on this bit-level interpretation.
- `fee_estimate` preserves a v1 wire type by converting `FeeRateV2` with `ceil()` into integer mojos per CLVM cost. Rounding direction is part of the compatibility contract; changing it can underquote fees.
- `pool_protocol` is not websocket P2P despite living under `protocols/`. It defines signed HTTP payloads/responses for pool endpoints. Authentication token helpers depend on local wall-clock minutes and should be evaluated as pool API compatibility, not peer-message routing.

## Test And Audit Strategy

- For protocol edits, test more than serialization round trips. Verify sender-map coverage, state-machine reply validity, API/stub decorator registration, rate-limit table coverage, and old/new protocol-version behavior where compatibility is claimed.
- Existing protocol tests are spread across server, wallet sync, farmer/harvester, plot sync, rate limits, mempool fee protocol, and network protocol data. A failing consumer test may be the real protocol regression signal even when `chia/protocols/` tests pass.
- High-risk changes include numeric message ID edits, adding messages without sender mappings, changing default capabilities, changing the reply/no-reply classification, adding unbounded list fields, and broadening which node type may send wallet/full-node/farmer messages.
- When auditing behavior, start from the message's receiving API handler and server gates. The protocol class tells what can be deserialized; it does not tell when the message is accepted, whether it is trusted, or which side effects follow.

## Source Pointers

For exact message ids, sender maps, reply/no-reply maps, handshake fields, and capabilities, read the files in the Landmarks table above. For API stub metadata and outbound call shape, read `apis.md`, `chia/server/api_protocol.py`, and the relevant `chia/apis/*_stub.py`. For rate-limit compatibility, read `chia/server/rate_limit_numbers.py` and `chia/server/rate_limits_v3.py`.
