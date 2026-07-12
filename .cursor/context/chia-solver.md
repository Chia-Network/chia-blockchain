# Chia Solver Module Context

Verified: 2026-07-02 against 6526ab6f18. If source contradicts this doc, trust source and update the doc.

`chia/solver/` is a small service boundary for v2 plot solving. It receives `SolverInfo` messages from farmers, turns Rust-backed `PartialProof` fragments into full proof bytes via `chia_rs.solve_proof()`, and returns `SolverResponse` messages that the farmer folds back into normal proof-of-space processing. It is not a chain, plot, key, or farmer-state authority.

## When To Read This

Read this for V2 partial-proof solving, solver peer admission, farmer `connect_to_solver`, solver protocol payloads, and farmer response correlation. For plot lookup and partial-proof production, read `chia-harvester.md` and `chia-plotting.md`; for final proof handling, read `chia-farmer.md`.

## Implementation Authority

- `Solver` owns only process-local runtime state: root/config, service lifecycle flags, a `ThreadPoolExecutor`, consensus constants, and the attached `ChiaServer`.
- `SolverAPI` is the peer API. Its only semantic endpoint is `solve`, registered for `ProtocolMessageTypes.solve` and expected to reply with `solution_response`.
- `SolverRpcApi` is local observability only. It exposes `get_state` with `started`; it does not configure peers, submit work, or expose proof data.
- Farmer remains the coordinator. It validates signage-point context, tracks `pending_solver_requests`, broadcasts solve requests to solver peers, reconstructs `ProofOfSpace`, and then re-enters `new_proof_of_space()`.
- Harvester remains the plot authority. V2 harvesters supply partial proofs plus plot metadata; the solver never opens plot files or verifies plot ownership.
- Full node and consensus remain the final acceptance authority. A solver-produced proof is still just proposed proof material until the farmer/full node/consensus path verifies and uses it.

## Why This Is Tricky

Public farmer RPC docs present the solver as turning V2 partial proofs into full proofs. The important source-level motivation is separation of concerns: harvesters keep local plot/prover ownership, farmers keep signage-point and harvester correlation, solvers perform the expensive proof expansion, and full-node/consensus still validate the final proof. That makes solver throughput and response handling a farmer hot path even though the solver service itself is intentionally small.

## Wrong Assumptions To Avoid

- Do not make solver own plot files, farmer keys, pool state, or signage-point validity.
- Do not treat a solver response as matched by websocket request id; farmer handles it as an inbound protocol message.
- Do not assume no response is harmless; farmer pending state and cache cleanup decide how long unresolved partial proofs remain.
- Do not add large solver payloads without revisiting protocol and rate-limit ownership in `chia/protocols/` and `chia/server/`.

## Main Runtime Flow

- Harvester finds v2 partial proofs for a signage point and sends `PartialProofsData` to farmer.
- Farmer rejects the data if the `sp_hash` is not in its short-lived signage-point cache.
- For each partial proof, farmer stores pending request metadata keyed by `bytes(partial_proof)`: original `PartialProofsData` and originating harvester peer.
- Farmer broadcasts `ProtocolMessageTypes.solve` with `SolverInfo(partial_proof, plot_id, strength, plot_size)` to all current solver connections.
- Solver receives `solve`, checks `solver.started`, calls `solve_proof(partial_proof, plot_id, strength, size, constants.TESTNET)`, and returns `SolverResponse(partial_proof, proof)` if a proof is produced.
- Farmer accepts `solution_response` only if the `partial_proof` matches a pending request, drops empty proofs, reconstructs a v2 `ProofOfSpace`, and calls `new_proof_of_space()` with the original harvester peer.

The request correlation key is the serialized partial proof only. If identical partial proofs can appear concurrently from different harvester/signage contexts, later requests overwrite earlier metadata. Treat changes to this keying as farmer/solver correctness-sensitive.

## Network And Protocol Contract

- `NodeType.SOLVER` has its own protocol version and normal shared capabilities.
- Sender authorization is asymmetric: farmers may send `solve`; solvers may send `solution_response`.
- `SolverAPI.solve()` advertises `solution_response` as a reply type, but the farmer sends `solve` through broadcast rather than request-id `call_api()` matching. This means the solver response is handled as an inbound message, not as request-id state-machine matching.
- `solve` and `solution_response` are expected to remain small, rate-limited payloads. Do not add large fields to these schemas without updating rate-limit assumptions.
- `SolverInfo` and `SolverResponse` are `Streamable` wire contracts backed by `PartialProof`, `bytes32`, `uint8`, and raw `bytes`. Schema edits require the usual protocol lockstep: message types, sender map, API/stub metadata, rate limits, compatibility tests, and protocol version considerations.

## Lifecycle, Config, And Peer Admission

- `start_solver.create_solver_service()` follows the standard Chia service composition: load selected-network constants, build `Solver`, `SolverAPI`, optional RPC, then wrap in `Service` as `NodeType.SOLVER`.
- Solver peer and RPC ports are configured through the solver/farmer config. Farmer config defaults to a local solver peer.
- Solver config defaults to `trusted_peers_only: True`; `on_connect()` accepts trusted peers and rejects untrusted peers unless that flag is disabled.
- `num_threads` controls the solver executor size. The current `solve()` implementation calls `solve_proof()` synchronously from the API handler rather than scheduling work on the executor, so changing solver throughput or blocking behavior requires checking API task latency and event-loop impact.
- Shutdown sets `_shut_down`, marks service shutdown through `manage()`, and shuts down the executor with `wait=True`.

## Cross-Module Coupling

- `chia/farmer/` is the only meaningful runtime consumer. Farmer RPC also exposes `connect_to_solver`, which closes existing solver connections before opening a requested solver peer.
- `chia/harvester/` drives solver demand indirectly by emitting v2 `PartialProofsData`; v1 plots bypass the solver entirely and return full proofs directly.
- `chia/protocols/` owns `SolverInfo`, `SolverResponse`, message IDs, sender authorization, and shared protocol versioning.
- `chia/server/` owns TLS identity, handshake-derived node type, rate limits, peer filtering, broadcast validation, and API dispatch. Solver code should not bypass these gates.
- `chia_rs` owns the actual proof-solving algorithm. Python solver behavior is mostly orchestration, error handling, and boundary enforcement around `solve_proof()`.

## Fragility Hotspots

- `constants.TESTNET` is passed into `solve_proof()`. Any network/fork behavior change needs confirmation that this flag is the intended Rust API input for mainnet and testnet configurations.
- The solver logs partial proof fragments and plot IDs. Avoid raising log volume or including sensitive local metadata in hot signage-point paths.
- Returning `None` from `SolverAPI.solve()` silently produces no response to the farmer. Farmer-side pending requests are only cleaned up on send failure or matching response; absence of a response can leave entries until surrounding farmer cache cleanup handles related state.
- Because farmer broadcasts to all solvers, multiple solvers may race to answer the same partial proof. The first matching response pops the pending request; later valid responses are logged as unknown and dropped.
- `SolverRpcApi._state_changed()` returns no websocket events. UI/daemon expectations should treat solver RPC as polling-only unless event support is added deliberately.

## Test Strategy

- Solver unit/service tests should cover readiness gating, successful `SolverResponse` construction, `solve_proof()` failure returning no message, and service shutdown of executor resources.
- Farmer/solver integration tests should cover pending request insertion, unknown response drop, empty proof cleanup, successful reconstruction into `NewProofOfSpace`, solver send exceptions, and multiple solver responses for one partial proof.
- Protocol tests should cover serialization of solver messages and static sender-map/reply metadata invariants when schemas or message IDs change.
- Lifecycle/RPC tests should verify default/configured solver peer connection, trusted-peer admission, `get_state`, and reconnect behavior through farmer `connect_to_solver`.

## Source Pointers

- Solver service/API/RPC: `chia/solver/solver.py`, `chia/solver/solver_api.py`, `chia/solver/solver_rpc_api.py`, `chia/solver/start_solver.py`.
- Farmer-side request correlation: `chia/farmer/farmer.py`, `chia/farmer/farmer_api.py`.
- Harvester partial-proof production: `chia/harvester/harvester_api.py`, `chia/plotting/prover.py`.
- Wire contracts and sender authorization: `chia/protocols/solver_protocol.py`, `chia/protocols/protocol_message_types.py`, `chia/protocols/protocol_state_machine.py`.
- Proof expansion implementation boundary: `chia_rs.solve_proof`.
