# Chia Daemon Module Context

Verified: 2026-07-02 against 6526ab6f18. If source contradicts this doc, trust source and update the doc.

`chia/daemon/` is the local process-control and keychain RPC boundary. It is not
part of the peer wire protocol: clients and node services connect to a local TLS
websocket, exchange JSON envelopes from `chia.util.ws_message`, and either ask
the daemon to perform privileged local work or ask it to relay messages to a
registered service websocket.

## When To Read This

Read this for local daemon websocket routing, service start/stop supervision, keychain proxying, plotter process management, daemon message envelopes, and GUI/service event fanout. For service-specific RPC endpoint semantics, read `chia-rpc.md` plus the concrete service context.

## Implementation Authority

- `WebSocketServer` is the daemon authority. It owns the TLS websocket listener,
  service registration table, daemon command dispatch, child-process table,
  plotting queue, keyring status notifications, and shutdown coordination.
- `DaemonProxy` is the generic client-side request/response adapter. It owns
  request-id waiters and the listener task that turns daemon responses back into
  per-request events.
- `KeychainServer` is the remote keychain authority behind daemon commands. It
  maps request `kc_user`/`kc_service` pairs to cached `Keychain` instances and
  normalizes keychain exceptions into daemon JSON errors.
- `KeychainProxy` is a compatibility layer over local or remote keychain access.
  In local mode it directly calls a `Keychain`; in remote mode it reconnects to
  the daemon and reconstructs returned private keys from returned entropy.
- Process launching and killing are local OS authority. `launch_service()`,
  `launch_plotter()`, `kill_processes()`, and `windows_signal.kill()` are the
  points where daemon commands become child processes, PID files, signals, and
  plotter log files.

## Why This Is Tricky

Public RPC docs show the daemon as a websocket route for service commands. In source, the daemon is also the local privilege concentrator: it can expose keychain operations, launch or kill services, mutate plotter queue state, and relay GUI/service messages by registered service name. That makes message envelope compatibility and registration cleanup security-relevant even though this is not P2P traffic.

## Wrong Assumptions To Avoid

- Do not apply peer-protocol sender maps, binary streamable framing, or P2P rate limits to daemon messages.
- Do not treat service registration as harmless metadata; registered names become routing authorities for local clients.
- Do not route arbitrary user-supplied command lines through service launch paths.
- Do not normalize keychain errors without checking CLI, GUI, daemon proxy, and remote keychain compatibility.

## Wire And Routing Contracts

- Daemon messages are JSON dictionaries with `command`, `ack`, `data`,
  `request_id`, `destination`, and `origin`. `format_response()` flips
  origin/destination, preserves the request id, and sets `ack=True`.
- `destination != "daemon"` is pure service forwarding. The daemon does not
  interpret the command or payload if the destination is registered; it serializes
  the original message and sends it to all websockets registered under that
  destination.
- `register_service` adds the current websocket to `connections[service]`.
  Multiple registrations of the same websocket for the same service collapse
  through the set; one websocket may register for multiple services and
  `remove_connection()` must remove it from all of them.
- There is no peer-style protocol enum, streamable binary framing, node-type map,
  or rate limiter here. The primary gate is mutual TLS using daemon private
  certs plus local config (`self_hostname`, `daemon_port`,
  `daemon_max_message_size`, `daemon_heartbeat`).
- Malformed JSON or unexpected message shape is caught around `handle_message()`
  and returned as a daemon error response to the sender. Debug logging must pass
  through `redact_sensitive_data()` before recording message contents.

## TLS, Startup, And Shutdown

- The daemon server uses `ssl_context_for_server()` with client certificates
  required. The daemon has a default minimum TLS policy plus a daemon-local
  compatibility escape hatch for internal daemon connections only.
- `async_run_daemon()` runs `chia_init()`, initializes daemon logging, acquires
  `daemon_launch_lock_path(root_path)`, creates `WebSocketServer`, installs async
  signal handlers, and waits on `shutdown_event`.
- `stop()` cancels ping/status tasks, kills every tracked service process, clears
  `services`, and sets `shutdown_event`. `exit()` closes the `WebServer` and must
  await `await_closed()` because `WebServer.close()` only schedules cleanup.
- `DaemonProxy.start()` creates its listener task after connecting and then
  sleeps briefly before returning. `_get()` registers the waiter before sending
  and has a source-defined response timeout.

## Keychain And Secret Handling

- Keychain commands are intercepted before normal daemon command dispatch by
  membership in `keychain_commands`. Adding a keychain RPC requires updating this
  list, `KeychainServer.handle_command()`, and usually `KeychainProxy`.
- `KeychainServer.run_request()` uses streamable JSON conversion for newer
  typed request/response classes (`get_key`, `get_keys`, public-key and label
  operations). Older commands are hand-parsed dictionaries and have more varied
  error shapes.
- Public-key responses intentionally override `to_json_dict()` to expose only
  `fingerprint`, `public_key`, and `label`; do not reuse private-key response
  shapes for public-only APIs.
- Remote private-key reads return public key hex plus entropy hex. The proxy
  rebuilds the mnemonic and private key and verifies the derived G1 matches the
  returned public key before handing it to callers.
- Passphrase operations mutate global keyring cache/state and notify
  `wallet_ui` via queued `keyring_status_changed` messages. `unlock_keyring()`
  may also run `check_keys()` once when the daemon was started with
  `--wait-for-unlock`.

## Service And Plotter Process Model

- `start_service` accepts only names validated by `validate_service()`. A service
  is considered running if the daemon has a live tracked process or a registered
  websocket for that service, which supports services started outside the daemon.
- Child processes inherit a copied environment with `CHIA_ROOT` set to the
  daemon root. Frozen builds map service names to packaged executables; source
  runs use `shutil.which()` or the raw service name.
- PID files live under `root_path / "run"` and are best-effort. On kill, the PID
  file is renamed to `.pid-killed` when possible; failure to write or rename PID
  files is intentionally non-fatal.
- Plotting is a special daemon-managed pseudo-service named `chia_plotter`.
  `plots_queue` is in-memory state; plotter subscribers receive full queue state
  on registration and incremental `state_changed`/`log_changed` messages later.
- Plotter command construction is per-plotter (`chiapos`, `bladebit`, `madmax`)
  and mutates command args before launch by appending `-D` so child plotters use
  the daemon for keychain access.
- Serial plotting is coordinated by queue name and `PlotState`: only one
  non-parallel `RUNNING` item per queue should exist. Completion is detected by
  tailing the plotter log for plotter-specific final words, not by only waiting
  on process exit.

## Fragility Hotspots

- Broadening service forwarding or registration is security-sensitive because
  registered service names become routing authorities for all local daemon
  clients.
- Changing response envelope fields breaks `DaemonProxy._get()` and GUI/RPC
  clients that key off `request_id`, `origin`, `destination`, and `ack`.
- Keychain error compatibility is uneven but tested. Normalizing errors is useful
  only if CLI, GUI, daemon tests, and `KeychainProxy.handle_error()` are updated
  together.
- Be careful with task lifetime: ping, state-change delivery, daemon-proxy
  listeners, keychain reconnect loops, and plotter tasks are deliberately
  referenced via `create_referenced_task()` or cancelled via `cancel_task_safe()`.
- `KeychainProxy.close()` awaits the reconnect task after setting `shut_down`.
  Any change to reconnect-loop exit conditions can make shutdown hang.
- Plotter queue state and service process state are updated from async tasks
  without an explicit lock. Keep state transitions small and preserve ordering of
  SUBMITTED -> RUNNING -> FINISHED/REMOVING notifications.
- `launch_service()` splits `service_command` on spaces. Today daemon-controlled
  service names are allowlisted and the only appended option is the testing flag;
  do not start passing arbitrary user-supplied command lines through this path.
- Windows process groups and signal mapping are special-cased. Changes to
  creation flags or `windows_signal.kill()` need Windows-specific validation.

## Test And Audit Strategy

- `chia/_tests/core/daemon/test_daemon.py` covers daemon command responses,
  passthrough routing to a full node, keychain RPCs, passphrase status events,
  plotting queue transitions, logging redaction, bad JSON, and plotter options.
- `chia/_tests/core/daemon/test_daemon_register.py` covers multi-service
  registration and connection cleanup semantics.
- `chia/_tests/core/daemon/test_keychain_proxy.py` covers local-vs-remote
  `KeychainProxy` behavior, private/public key reconstruction, and error mapping.
- `chia/_tests/core/test_daemon_rpc.py` is the minimal daemon client smoke test.
- `chia/_tests/cmds/test_daemon.py` anchors CLI daemon startup, keyring unlock
  flow, and daemon launcher behavior.

## Source Pointers

- Daemon websocket server and process control: `chia/daemon/server.py`.
- Client/proxy adapters: `chia/daemon/client.py`, `chia/daemon/keychain_proxy.py`.
- Remote keychain command handling: `chia/daemon/keychain_server.py`.
- Plotter process queue: `chia/daemon/server.py`, `chia/plotters/`.
- Message envelope helpers: `chia/util/ws_message.py`.
