# Chia APIs Module Context

Verified: 2026-07-12 against 24db9ad3901d. If source contradicts this doc, trust source and update the doc.

`chia/apis/` is the protocol metadata surface for service APIs. The classes are non-functional `Protocol` stubs, but their `ApiMetadata` decorators are runtime-relevant: outbound `WSChiaConnection.call_api()` uses remote stub metadata to decide whether a request can be sent, and local stub metadata to decode typed responses.

## When To Read This

Read this when changing `chia/apis/*_stub.py`, `stub_protocol_registry.py`, API decorator metadata, request/reply declarations, or protocol-visible method names. For message schemas and numeric IDs, read `protocols.md`; for connection lifecycle and dispatch enforcement, read `server.md`.

## Implementation Authority

- Stub decorators must mirror the concrete service API decorators for protocol-visible behavior. Drift can reject valid outbound calls or decode a valid response with the wrong local handler metadata.
- The decorator derives the message type from the method name unless `request_type=` is set. Method names are therefore wire-contract inputs when no explicit request type is provided.
- The first non-`self`/`peer` type hint is treated as the streamable payload class. Signature shape controls deserialization.
- `peer_required`, `bytes_required`, and `execute_task` affect handler invocation, raw-byte preservation, and timeout behavior; they are not documentation-only flags.
- `reply_types` on stubs are metadata for callable APIs, but runtime response validity is still controlled by `chia/protocols/protocol_state_machine.py`.
- Sender authorization is separate. Allowed inbound node types are enforced by `ProtocolMessageTypeToNodeType`, not by stub presence.

## Change Guidance

- Adding a protocol method usually requires lockstep updates across payload class, `ProtocolMessageTypes`, sender map, state-machine reply/no-reply map, concrete API decorator, matching stub decorators, rate limits, and protocol tests.
- Prefer `request_type=` when compatibility requires a Python method name that differs from the enum name.
- Response-only messages still need local stub entries when they can be returned from `call_api()`, because the caller looks up response message metadata before deserializing.
- When adding list-bearing payloads, check the concrete API/decorator path for `list_limits=` needs instead of relying on streamable types to bound adversarial input.
- Do not infer consensus, wallet, farmer/harvester, timelord, solver, or DataLayer semantics from stubs. They declare wire-call shape only; validation and side effects live in concrete APIs and downstream services.

## Source Pointers

For metadata machinery and runtime dispatch, read `chia/server/api_protocol.py` and `chia/server/ws_connection.py`. For stub registration, read `chia/apis/stub_protocol_registry.py`. For exact message IDs, sender authorization, and request/reply validity, read `chia/protocols/protocol_message_types.py`, `chia/protocols/protocol_message_type_to_node_type.py`, and `chia/protocols/protocol_state_machine.py`. For concrete behavior, read the matching service API under `chia/full_node/`, `chia/wallet/`, `chia/farmer/`, `chia/harvester/`, `chia/timelord/`, `chia/introducer/`, or `chia/solver/`.
