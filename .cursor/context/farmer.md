# Chia Farmer Module Context

Verified: 2026-07-12 against a5647a9327e5. If source contradicts this doc, trust source and update the doc.

`chia/farmer/` is the block-production coordinator between the full node, harvesters, pool HTTP APIs, local keychain, plot-sync state, RPC clients, and optional solver services for v2 plots. It does not own chain consensus or plot lookup; its safety depends on forwarding only locally verified proof/signature material across these boundaries while keeping short-lived signage-point state coherent.

## When To Read This

Read this for farmer/full-node/harvester proof flow, pool partial submission, reward-target config, plot-sync receiver state, solver connection management, and farmer RPC. For local plot discovery or signatures, read `harvester.md` and `plotting.md`; for final block acceptance, read `full-node.md` and `consensus.md`.

## Landmarks

| file                            | owns                                                  |
| ------------------------------- | ----------------------------------------------------- |
| `chia/farmer/farmer.py`         | mutable service state, SP/proof/pool/plot-sync caches |
| `chia/farmer/farmer_api.py`     | SP/proof/signature/solver message routing             |
| `chia/farmer/farmer_rpc_api.py` | reward target, pool state, harvester plot RPC         |
| `chia/farmer/start_farmer.py`   | farmer Service construction                           |

## Implementation Authority

- `Farmer` is the mutable service state holder: keys, reward targets, signage-point caches, proof caches, harvester plot-sync receivers, pool state, pending solver requests, and RPC/event callbacks.
- `FarmerAPI` is the peer-protocol semantic layer. It receives full-node signage points, harvester proofs/signatures/plot-sync updates, and solver responses, then routes validated follow-up messages.
- The full node remains the authority for chain validity and unfinished-block construction. Farmer `DeclareProofOfSpace` and `SignedValues` messages are proposals/signatures, not accepted blocks.
- Harvesters are operator-controlled peers, but the farmer still verifies proof quality and aggregate signatures before forwarding. A harvester can affect local rewards/fees and pool partial submission, so its payloads are not blindly trusted.
- Pool servers are external HTTP services. Pool info, farmer records, difficulty, partial acknowledgement, and errors update local `pool_state`, but pool responses do not alter consensus facts.
- RPC is local management: reward target mutation, payout-instruction updates, harvester/plot inspection, signage-point inspection, pool login links, and solver connection control.

## Why This Is Tricky

Public farming docs describe the farmer as finding proofs and earning rewards, but the source-level role is narrower: it correlates transient proof material from harvesters, pool servers, solvers, and the full node. None of those inputs is durable truth by itself. The same proof can be used for network block proposals, pool partial accounting, UI farm-health metrics, and later signature requests, so cache keys and message routing carry more meaning than a local handler read suggests.

## Wrong Assumptions To Avoid

- Do not treat a farmer proof as an accepted block; full-node/consensus validation still decides acceptance.
- Do not treat pool partial success as chain state; it is external accounting by a pool server.
- Do not assume the farmer can recompute harvester-local signatures or plot metadata after the fact; it must preserve correlation to the original harvester/proof.
- Do not treat solver responses as independent proofs; farmer pending-request state is the correlation authority.

## Main Runtime Flow

Block production is a two-stage signature workflow:

- Full node sends `NewSignagePoint` to the farmer.
- Farmer caches it under `challenge_chain_sp`, builds per-pool `PoolDifficulty` hints, and sends the old or new signage-point harvester payload depending on peer protocol version.
- Harvester returns `NewProofOfSpace`.
- Farmer verifies the proof with `verify_and_get_quality_string()` using the SP challenge, peak height, and previous transaction block height.
- If the proof's required iterations are below the SP interval, farmer caches the proof and asks the originating harvester to sign challenge-chain and reward-chain SP values.
- `RespondSignatures` is processed into `DeclareProofOfSpace` and broadcast to full nodes.
- Full node may later request foliage signatures by quality string; farmer re-contacts the original harvester and returns `SignedValues`.

Pool partial submission is parallel to block-winning flow. For pool contract plots, the same proof is checked against the pool's current difficulty. If good enough, farmer requests a harvester plot signature over `PostPartialPayload`, adds its farmer/taproot/authentication signatures, posts `/partial`, and updates local accounting from the pool response.

V2 plots add a solver hop. Harvester sends `PartialProofsData`; farmer stores pending request metadata keyed by `bytes(partial_proof)`, broadcasts `SolverInfo` to solver peers, receives `SolverResponse`, reconstructs a `ProofOfSpace`, and re-enters the normal `new_proof_of_space()` path. Solver responses for unknown or empty proofs are dropped.

## Mutable State Domains

- `sps`: maps `challenge_chain_sp` to one or more `NewSignagePoint` objects. Duplicates are ignored; entries are short-lived and drive both RPC display and proof validation.
- `proofs_of_space`: maps SP hash to `(plot_identifier, ProofOfSpace)` pairs used later when harvester signatures arrive.
- `quality_str_to_identifiers`: maps locally computed quality strings to `(plot_identifier, challenge_hash, sp_hash, harvester_node_id)` so full-node `RequestSignedValues` can target the same harvester/proof.
- `number_of_responses` and `cache_add_time`: low-tech bounded-memory controls. `_periodically_clear_cache_and_refresh_task()` removes SP/proof/quality/response state after roughly three sub-slot times.
- `pending_solver_requests`: maps partial proof bytes to original harvester data. This is a request correlation table, not a validated-proof cache.
- `plot_sync_receivers`: one `Receiver` per harvester peer. It owns plot lists, invalid/key-missing/duplicate paths, sync identifiers, and effective plot-size summaries used by RPC/UI.
- `pool_state`: keyed by `p2_singleton_puzzle_hash`, combining persisted `PoolingShareState`, remote pool difficulty/token data, partial counters, errors, and next update deadlines.
- `authentication_keys`, `all_root_sks`, `_private_keys`, and `pool_sks_map`: key-derived state. These are populated after keychain access succeeds and must be refreshed when pooling config changes.

## Key And Signature Contracts

- Farmer private keys are derived as farmer and pool keys from all root keys. Harvester handshake advertises farmer public keys and old-style pool public keys so harvesters can select plots.
- For plot signatures, the harvester provides the local-key share. Farmer finds the matching farmer private key, derives the aggregate plot public key, optionally adds the taproot share for pool-contract plots, aggregates signatures, and verifies before forwarding.
- Original self-pooled plots with `pool_public_key` require a local pool private key and a signed `PoolTarget`; pool-contract plots set `pool_target` and `pool_signature` to `None`.
- Pool authentication uses owner/authentication keys and current authentication tokens from `pool_protocol`. Login links, `/farmer`, and `/partial` requests are signed payloads tied to launcher/target data.
- CHIP-22 third-party harvester reward override handling forces source signature data and logs whether the harvester's fee-quality convention appears valid. This is a reward-routing convention, not a consensus permission check.

## Pool State And Persistence

- Pooling configuration lives in `<chia root>/pooling/pooling_share_state.yaml`, guarded by `PoolingShareState.lock()`. `Farmer.__init__()` performs migration from older `config.yaml` pool entries.
- `update_pool_state()` periodically rereads pooling config, refreshes keys, ensures per-pool state exists, fetches `/pool_info`, fetches `/farmer`, POSTs unknown farmers, PUTs payout/auth updates, and updates difficulty/points.
- Mainnet enforces HTTPS pool URLs. Non-mainnet and self-pooling (`pool_url == ""`) follow local accounting paths without remote pool submission.
- Pool counters are rolling time-window lists plus since-start totals. `strip_old_entries()` aging happens on signage-point handling and on stat increments; stale data can persist if the farmer stops receiving signage points.

## Protocol Compatibility

- `NewSignagePointHarvester` and `NewSignagePointHarvester2` intentionally share the same message ID. Farmer selects old/new payload shape based on the source-defined harvester protocol-version boundary.
- `NewSignagePointHarvester2` carries `peak_height` and `last_tx_height`, while the old payload carries `filter_prefix_bits`. Any change here is a live farmer-harvester compatibility change and must move with protocol enum/sender-map/stub/rate-limit/version tests.
- Source-signature fields in `RequestSignatures` are optional but meaningful. They carry full data corresponding to hashes when third-party harvester reward override/source verification is active.
- Farmer broadcasts only no-reply/proposal messages to full nodes except direct request/response use through `call_api()` for harvester signatures. Do not broadcast request/response message types outside the server state-machine rules.

## Concurrency And Lifecycle

- `Farmer.manage()` starts an initialization loop that waits for key setup before launching pool-state refresh and cache-clear tasks. Harvester handshake tasks wait for `started` so public keys are available.
- Shutdown sets `_shut_down`, awaits the two background tasks, closes keychain proxy, and clears `started`. Long-running pool HTTP calls and harvester RPC calls run on the service event loop.
- There is no broad lock around farmer mutable dictionaries. Handlers and background tasks rely on asyncio sequencing and short-lived mutation. Multi-step edits to related caches must preserve ordering and cleanup on exceptions.
- `on_connect()` creates plot-sync receivers for harvesters and sends handshake after key readiness. `on_disconnect()` removes the receiver and emits UI/RPC state changes.
- `connect_to_solver` RPC closes existing solver connections before opening the requested solver peer, so solver selection is effectively single-target from the management surface even though solve requests broadcast to all current solver connections.

## RPC Surface

- Signage-point RPC reads from transient `sps`/`proofs_of_space`; missing SPs are normal after cache expiry.
- Reward target RPC mutates `config.yaml` and in-memory encoded/decoded targets. Optional private-key search scans derived wallet addresses to report whether keys are present.
- Pool state RPC returns shallow copies of `pool_state` with live plot counts calculated from `plot_sync_receivers`.
- Harvester plot RPC pages/sorts/filter data from `Receiver`; sorting by optional key fields is intentionally rejected.
- State-change fanout targets wallet UI and metrics with specific event names. Changing event shape affects UI/metrics consumers even if RPC routes stay stable.

## Fragility Hotspots

- Quality-string correlation is the bridge between initial proof handling and later full-node signature requests. Evicting or overwriting it too early causes valid full-node requests to fail.
- `proofs_of_space[sp_hash]` is assumed present in `_process_respond_signatures()`. Handler ordering and cache expiry must ensure signature responses cannot outlive their proof entry.
- Pool partial accounting has many early returns. Failed paths should consistently emit `failed_partial` and increment the right counter; missing one makes UI/metrics diverge from actual pool submission behavior.
- Solver request correlation by `bytes(partial_proof)` can collide logically if the same partial proof is submitted from different harvesters/SP contexts before a response returns. Treat changes to this keying as correctness-sensitive.
- The farmer accepts and logs harvester reward-address overrides. Any change to override validation affects operator economics and third-party harvester compatibility.
- Network/API changes must preserve node-type sender authorization, protocol reply mapping, and old/new harvester version branching. Protocol classes alone are not the full contract.
- Background pool updates mutate `pool_state` while signage-point/proof handlers read difficulty/token fields. Keep `None` checks and update ordering explicit to avoid submitting partials with stale or missing pool parameters.

## Test Strategy

- Farmer-harvester tests should cover both old and new signage-point payload branches, duplicate SP handling, proof verification rejection, request-signatures routing to the original harvester, and cache-expiry behavior.
- Pool tests should exercise missing difficulty/token, not-good-enough partials, successful `/partial` difficulty update, `TOO_LATE`, `PROOF_NOT_GOOD_ENOUGH`, network failure, and self-pooling.
- Signature tests should assert aggregate key construction for pool-public-key plots and pool-contract/taproot plots, including reward override/source-data cases.
- Solver tests should cover unknown response, empty proof response, successful reconstruction into `NewProofOfSpace`, and cleanup of `pending_solver_requests`.
- RPC tests should verify event payloads, pagination/filter/sort behavior, reward-target persistence, payout-instruction update forcing the next farmer update sentinel, and solver reconnection behavior.

## Source Pointers

In-module files are in the Landmarks table above. Cross-module authorities:

- Pool config mirror and external pool protocol: `chia/pools/pool_config.py`, `chia/protocols/pool_protocol.py`.
- Harvester/solver wire contracts: `chia/protocols/harvester_protocol.py`, `chia/protocols/solver_protocol.py`.
