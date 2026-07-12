# Chia RPC Module Context

Verified: 2026-07-12 against a5647a9327e5. If source contradicts this doc, trust source and update the doc.

`chia/rpc/` is the local operator/API boundary for Chia services. It is separate from the peer protocol: service-specific RPC APIs expose HTTP POST routes and daemon websocket commands, while this module supplies the shared server wrapper, client base class, typed marshalling helper, and structured error normalization.

## When To Read This

Read this for shared RPC server/client transport, daemon websocket registration, common routes, typed request marshalling, structured error shape, state-change fanout, and local/admin API behavior. For endpoint side effects, read the concrete service context and RPC API class.

## Implementation Authority

- `RpcServer` is the shared transport authority. It owns HTTPS route registration, daemon websocket registration/reconnect, state-change fanout to the daemon/UI, common service routes, and lifecycle coordination with `WebServer`, `ClientSession`, and the daemon websocket.
- Concrete `*RpcApi` classes own service semantics. They provide `service_name`, `service`, `get_routes()`, and `_state_changed()`; endpoint validation and side effects belong there, not in `RpcServer`.
- `RpcServiceProtocol` is the service adapter contract. The service supplies its `ChiaServer`, connection summaries, outbound peer connection hook, state-change callback registration, and optional lifecycle management.
- `RpcClient` is only the common client for shared routes. Service-specific clients such as full-node, wallet, and data-layer clients extend the same HTTP/JSON convention for larger endpoint surfaces.
- `rpc_errors.py` is the compatibility bridge between legacy `"error"` strings and machine-readable `"structuredError"` payloads. Callers still depend on both shapes.

## Why This Is Tricky

Public RPC docs present HTTP and websocket access as one API surface. In source, this package is mostly transport and compatibility glue: it should preserve request/response envelopes, daemon registration, common admin routes, and error normalization while leaving business semantics in concrete service RPC APIs. A change that looks like common JSON cleanup can break CLI clients, GUI websocket consumers, service shutdown order, or language clients that depend on legacy response fields.

## Wrong Assumptions To Avoid

- Do not treat RPC as P2P. It is a local/admin surface protected by private TLS in normal service mode.
- Do not put endpoint business validation into `RpcServer`; concrete RPC APIs own service semantics.
- Do not assume HTTP and daemon websocket failures have identical response shape.
- Do not assume `marshal()` covers every typed or CLVM-streamable request path.

## Transport And Lifecycle

- RPC HTTP routes are POST-only and are registered from `rpc_api.get_routes()` plus `RpcServer._routes`. Route names include their leading slash on the server; `RpcClient` method names intentionally match common route names without the slash.
- `start_rpc_server()` creates TLS contexts from the private daemon certs/CA, installs the service state-change callback, starts the HTTPS server, and optionally starts the daemon websocket loop.
- RPC startup is nested inside `Service.manage()` after the node service and peer server start. Shutdown closes peer connections first, then closes RPC, awaits the peer server, and finally awaits RPC cleanup. Do not make RPC shutdown depend on peer-server state still being live.
- `RpcServer.close()` is a shutdown signal plus webserver close; `await_closed()` is responsible for closing the daemon websocket, client session, webserver, and daemon reconnect task.
- The daemon connection loop re-creates `ClientSession` and websocket on each reconnect attempt, registers the service with the daemon, handles daemon-originated commands until the websocket closes, then sleeps for the configured retry delay unless shut down.
- `daemon_heartbeat` and `max_message_size` apply only to the daemon websocket. HTTP request body size is controlled by `max_request_body_size`, with service startup able to override the default.

## Request And Response Contracts

- HTTP handlers call `await request.json()` before endpoint dispatch. Malformed JSON/body parsing errors are outside the endpoint `try` block in `wrap_http_handler()` and therefore can surface as HTTP-level failures rather than normalized RPC error objects.
- Endpoint handlers may return `None` or a dict. `wrap_http_handler()` and websocket `safe_handle()` insert `"success": True` when absent; handlers that need failure semantics must return/raise explicitly.
- HTTP endpoint exceptions produce `{success: false, error, traceback, structuredError}`. Websocket endpoint exceptions produce `{success: false, error, structuredError}` and intentionally omit traceback from the response.
- `RpcClient.fetch()` treats transport-level HTTP errors via `raise_for_status()` and application-level failures via `ResponseFailureError`, preserving the full response dict for CLI and tests.
- Websocket daemon commands are selected by `command`, ignored when `ack` is true, respond to `"ping"` with `pong()`, then resolve first against common `RpcServer` methods and then concrete `rpc_api` methods. Unknown commands become structured failure responses when the incoming JSON parsed successfully.
- State-change notifications are push-only daemon websocket messages. `_state_changed()` may add service-specific payloads, and common connection changes additionally trigger a synthetic `get_connections` update for `wallet_ui`.

## Common Routes And Peer Coupling

- Common routes are operational helpers: network info, active peer connections, open/close peer connection, stop node, route discovery, version, health, and log level management.
- `get_connections()` crosses into `ChiaServer` through the concrete service. Returned connection data includes peer node id bytes; clients convert `node_id` hex strings back to bytes.
- `open_connection()` resolves hostnames with the configured IPv6 preference and delegates to `ChiaServer.start_client()` with the service's `on_connect` callback when present.
- `close_connection()` closes all matching peer connections for a node id. The server connection layer remains the authority for cleanup, bans, and peer lifecycle side effects.
- `set_log_level()` mutates global/service logging configuration at runtime. Tests rely on `reset_log_level()` restoring the configured service log level.

## Marshalling And Compatibility

- `marshal()` adapts typed `Streamable` request/response endpoints to normal RPC dict endpoints. It derives the request class from the endpoint's `request` type hint and asserts it is a `Streamable`.
- Default marshalling uses `from_json_dict()` and `to_json_dict()`. Requests carrying the CLVM-streamable JSON CHIP use CLVM streamable JSON serialization, optionally with a named translation layer.
- The shared translation registry maps known CHIP translation names to translation layers. Unknown translation names raise before endpoint logic runs and are normalized by the transport wrapper.
- The helper assumes a single `request` argument and a `Streamable` response. Endpoints with custom dict semantics, multi-object responses, action-scope wrappers, or legacy shape compatibility should keep explicit dict handling in the concrete RPC API.
- Wallet RPC also performs CLVM-streamable JSON handling in transaction wrappers. Do not assume `marshal()` is the only CLVM-streamable JSON path in the RPC system.

## Structured Error Semantics

- Prefer raising `RpcError` for intentional endpoint failures that need stable machine-readable codes or structured data. `RpcError.simple()` is the concise path when the legacy and structured messages can match.
- Non-`RpcError` exceptions are mapped by type: validation, timestamp, consensus, protocol, util `ApiError`, and assertion errors receive specific codes; everything else becomes `UNKNOWN`.
- `structured_error_from_exception()` imports consensus/protocol error classes lazily. Keep new imports there deliberate to avoid broad import-time coupling from the low-level RPC package into heavy subsystems.
- The legacy `"error"` string remains compatibility surface for existing CLI/client code. Changing it can break callers even if `"structuredError"` is richer.
- Values placed in `RpcError.data` must be JSON-serializable. The transport wrapper does not sanitize arbitrary objects before `obj_to_response()`.

## Test And Audit Strategy

- Shared RPC changes should run focused tests under `chia/_tests/rpc/` plus any service-specific RPC tests for affected semantics. Use `tools/pytest`, not bare `pytest`.
- For common route changes, preserve the invariant that `RpcClient` method names match `RpcServer._routes` entries without the leading slash.
- For response-shape changes, test both HTTP and daemon websocket paths; they intentionally differ on traceback exposure.
- For marshalling changes, test normal streamable JSON and CLVM-streamable requests. Data-layer and wallet RPC are the important service-specific consumers.
- For lifecycle changes, reason with `Service.manage()` shutdown order and daemon reconnect behavior. Leaks usually appear as unclosed aiohttp sessions, a reconnect task that never exits, or websocket state-change sends after shutdown.

## Fragility Hotspots

- Highest-risk edits: changing automatic `"success"` insertion, changing common route names, broadening `RpcClient.fetch()` failure behavior, altering daemon websocket command routing, or making RPC lifecycle assumptions about peer-server availability.
- Error compatibility is easy to break: HTTP includes traceback in failure responses, websocket failures do not, and `ResponseFailureError` preserves the full JSON body.
- The RPC boundary is semi-trusted local/admin surface protected by private TLS in normal service mode, not an untrusted P2P path. Do not move peer protocol rate-limiting or node-type authorization assumptions into this layer.
- Route discovery returns every shared and service-specific route. Adding sensitive operational endpoints should be evaluated as local admin API exposure even when not reachable through the P2P protocol.
- `marshal()` depends on runtime type hints. Missing or future-deferred annotations that cannot resolve will fail at decoration/call setup rather than inside endpoint business logic.

## Source Pointers

- Shared server lifecycle and common routes: `chia/rpc/rpc_server.py`.
- Common client behavior: `chia/rpc/rpc_client.py`.
- Typed marshalling and CLVM streamable handling: `chia/rpc/util.py`.
- Structured errors: `chia/rpc/rpc_errors.py`.
- Daemon websocket envelope/routing: `chia/util/ws_message.py`, `chia/daemon/server.py`.
