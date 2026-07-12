# Chia Pools Module Context

Verified: 2026-07-02 against 6526ab6f18. If source contradicts this doc, trust source and update the doc.

`chia/pools/` is the plot-NFT/pooling singleton adapter. It bridges wallet-owned singleton state, CLVM pool puzzles, farmer-facing pooling configuration, consensus reward coin shape, and the external pool HTTP protocol. The module is small, but it sits on several trust boundaries: wallet sync reconstructs state from on-chain coin spends, the farmer reads a YAML mirror rather than wallet DB state, and reward claiming depends on exact consensus coin IDs and puzzle hashes.

## When To Read This

Read this for plot NFT / pool singleton state, pool wallet transitions, farmer-facing pool config, pool reward claims, pool protocol payloads, and portable-plot ownership. For wallet action scopes and sync, also read `chia-wallet.md`; for farmer partial submission, read `chia-farmer.md`; for plot IDs and memos, read `chia-plotting.md`.

## Implementation Authority

- The blockchain is the authority for pool singleton history. `PoolWallet.get_current_state()` derives the current and last state-changing `PoolState` from `WalletPoolStore` coin spends, not from the YAML config or transient target fields.
- `PoolWallet` is the wallet-facing state machine. It creates the launcher spend, joins/leaves pools, submits the second leave transaction after the relative lock height, claims self-pooled rewards, and updates the farmer-facing config mirror.
- `pool_puzzles.py` is the CLVM boundary. It curries precompiled pool puzzle modules from `chia-puzzles-py`, constructs singleton and p2-singleton puzzles, builds travel/absorb `CoinSpend`s, and parses pool state out of launcher/travel solutions.
- `pool_wallet_info.py` defines streamable state contracts used by wallet RPC and by on-chain pool-state serialization. `PoolState` bytes are committed into launcher/travel solution extra data.
- `pool_config.py` is a side-channel to the farmer. `<chia root>/pooling/pooling_share_state.yaml`, guarded by `PoolingShareState.lock()`, mirrors launcher id, pool URL, payout instructions, target puzzle hash, p2-singleton puzzle hash, owner public key, and derivation index for farmer startup/update loops.
- The farmer and pool server are not authorities for singleton state. Farmer `pool_state` and remote pool `/pool_info`, `/farmer`, and `/partial` responses affect difficulty, payout registration, and partial accounting, but do not prove or mutate the wallet's on-chain state.

## Why This Is Tricky

Public pooling docs describe portable plots as being tied to a Plot NFT that can change pools. In source, that product goal is split across three authority layers: wallet singleton spends define the durable pool state, plot IDs bind plots to the singleton-derived puzzle hash, and the farmer YAML mirror tells the farmer where to submit partials. Pool servers smooth rewards through partial accounting, but they do not choose blocks or prove the wallet's singleton state.

## Wrong Assumptions To Avoid

- Do not treat farmer YAML as wallet truth; it is a mirror derived from wallet state transitions.
- Do not treat a pool server response as validation of singleton lineage or payout authority.
- Do not treat `target_state` as durable; it is pending local intent until matching chain state is observed.
- Do not change pool puzzle tree hashes or singleton parent-info shape as a wallet-only refactor.

## Core State Model

- `PoolState.state` has the live self-pooling, leaving-pool, and farming-to-pool modes. Self-pooling uses the waiting-room inner puzzle with the immediate-lock sentinel and no pool URL; farming-to-pool uses the member inner puzzle; leaving-pool uses the waiting-room inner puzzle with the pool's lock height.
- `target_puzzle_hash` means final payout destination, not the p2-singleton address where pool rewards are initially farmed. In self-pooling it is a local wallet puzzle hash; in farming-to-pool it is the pool's target puzzle hash.
- `launcher_id` is the singleton identity. `launcher_id_to_p2_puzzle_hash()` derives the pool-contract puzzle hash used by plots and reward coins from the singleton mod hash, launcher id, launcher puzzle hash, delayed escape parameters, and delayed puzzle hash.
- Pool singleton coins use the singleton amount invariant and are recognized by singleton lineage. Reward coins are separate pool reward outputs to the p2-singleton puzzle hash and are absorbed into the singleton chain when claimed.
- `PoolWalletInfo.target` is transient local intent, not chain state. It is cleared when a matching on-chain transition is observed; rollback may also rewrite config if the derived current state changes.

## Lifecycle Flows

- Creating a pool wallet selects standard-wallet coins, creates a singleton launcher coin, asserts the launcher announcement from the standard-wallet spend, stages the launcher spend as an extra spend, and returns the p2-singleton puzzle hash plus launcher id. The actual `PoolWallet` object is created later when wallet sync sees and spends the launcher on chain.
- Wallet sync discovers pool wallets by detecting a singleton launcher child, fetching the launcher spend, parsing a `PoolState` from its solution extra data, creating `PoolWallet`, recording the launcher spend in `WalletPoolStore`, tracking the first singleton coin, and subscribing to its coin id.
- Subsequent singleton transitions are applied when a tracked singleton coin is spent. `apply_state_transition()` only accepts spends whose coin name matches the current tip coin, appends the spend, follows the new singleton coin, subscribes to its coin id, and updates the YAML mirror.
- Switching from `FARMING_TO_POOL` to another final state is a two-transaction flow: first travel to `LEAVING_POOL`, then after `last_transition_height + relative_lock_height` plus a small reorg buffer, `new_peak()` submits the final travel to `SELF_POOLING` or a new pool.
- Switching from `SELF_POOLING` or mature `LEAVING_POOL` to `FARMING_TO_POOL` is one travel transaction. Switching directly between pools charges for two transitions because it first enters `LEAVING_POOL`.
- Claiming self-pooled rewards scans this pool wallet's unspent reward coins, filters to known farming rewards, builds repeated absorb spends that advance the singleton tip while consuming p2-singleton reward coins, optionally adds a standard-wallet fee spend tied by a coin announcement, and records an outgoing transaction paying the absorbed amount to the current target puzzle hash.

## CLVM And Consensus Coupling

- Pool puzzle construction must match the precompiled modules exactly: `POOL_MEMBER_INNERPUZ`, `POOL_WAITINGROOM_INNERPUZ`, `P2_SINGLETON_OR_DELAYED_PUZHASH`, and the wallet singleton top layer. Tree hashes are part of live plot contracts and reward addresses.
- `pool_state_to_inner_puzzle()` maps `SELF_POOLING` and `LEAVING_POOL` to the waiting-room puzzle, and `FARMING_TO_POOL` to the member puzzle whose escape puzzle hash is the corresponding waiting-room puzzle hash.
- `create_travel_spend()` and `create_absorb_spend()` reconstruct singleton parent info differently for eve spends versus later spends. Parent-info shape must stay aligned with singleton top-layer expectations.
- `solution_to_pool_state()` distinguishes launcher spends, member travel spends, waiting-room travel spends, and absorb spends by positional CLVM solution shape. Parser changes are high risk because malformed or unexpected spends can make wallet state reconstruction skip or misclassify transitions.
- Absorb spends reconstruct reward coins using `pool_parent_id(height, genesis_challenge)` and `calculate_pool_reward(height)`. This is intentionally tied to consensus coinbase rules; changing reward schedule or parent-id logic without updating absorb tests can strand claimable rewards.
- `PoolWallet.claim_pool_rewards()` maps wallet farming reward transaction records back to block heights, then uses those heights to build reward coin spends. If reward detection or transaction-record height derivation changes in wallet code, pool reward claims can break even when pool puzzles are untouched.

## Persistence And Configuration

- `WalletPoolStore` stores ordered `(height, CoinSpend)` transitions per wallet id in SQLite. New transitions must not go backward in height and must extend the previous spend's coin name through parent linkage; duplicate identical spends are ignored.
- Rollback deletes pool transitions above the rollback height. If the launcher spend itself rolls back, `PoolWallet.rewind()` asks `WalletStateManager` to remove the whole pool wallet; otherwise it refreshes the YAML mirror when derived state changed.
- `PoolingShareState.acquire()` rewrites the entire YAML list on context exit unless `read_only=True`. Callers that only inspect state should use read-only acquisition to avoid unnecessary file churn and accidental persistence of mutated objects.
- `PoolingShareState.add()` is keyed by `p2_singleton_puzzle_hash`, not launcher id. Duplicate p2-singleton entries are rejected, and migration from old `config.yaml["pool"]["pool_list"]` clears the old list after copying missing entries.
- `PoolWallet.update_pool_config()` creates missing YAML entries and preserves existing payout instructions when present. Empty payout instructions are filled with a newly derived puzzle hash, so config updates can consume derivation state through the action scope.

## External Pool Protocol Boundary

- `POOL_PROTOCOL_VERSION` gates wallet-created states: a state with a newer version is rejected and requires upgrading the wallet.
- Farmer pool registration signs `PostFarmerPayload` / `PutFarmerPayload` with the owner key and derives/uses an authentication key for `AuthenticationPayload` and partial submissions. The wallet stores only owner public key and payout/config data; private key lookup stays in farmer/keychain code.
- Mainnet farmer update enforces HTTPS pool URLs. Self-pooling is represented to the farmer by `pool_url == ""`, which skips remote pool updates and partial submission while keeping local plot-NFT accounting.
- Pool servers can redirect `/pool_info` via permanent redirects, update difficulty, request payout/auth updates, or reject partials. These responses affect farmer runtime state but should not be treated as validation of `PoolState` or singleton lineage.

## Fragility Hotspots

- Do not use `target_state` as durable truth. It is local pending intent and is reset after matching on-chain state or rollback; the spend history is the durable source.
- Unconfirmed transaction gates are intentional. Join/self-pool/claim operations reject when this pool wallet has unconfirmed transactions to avoid overlapping singleton-tip spends.
- The leave flow depends on wallet `new_peak()` being called and on `finished_sync_up_to()` height comparisons. Changes to wallet sync height semantics can delay or prematurely submit second-stage travel transactions.
- Assertions are common around CLVM shape, singleton additions, and reward heights. Some indicate internal invariants rather than user input validation; converting them to recoverable paths can hide state corruption if not paired with explicit rejection semantics.
- The farmer-facing YAML mirror can diverge from wallet DB state if updates are skipped, interrupted, or run with stale action-scope derivations. Review any change that moves `update_pool_config()` out of state-transition, create, or rollback paths.
- Pool reward claim batching is bounded. Larger batches risk oversized spend bundles; smaller batches leave rewards claimable but unclaimed.

## Test Strategy

- Creation tests should cover both self-pooling and farming-to-pool initial states, launcher announcement linkage, returned launcher id/p2-singleton hash, and later wallet creation from the confirmed launcher spend.
- State transition tests should cover self-to-pool, pool-to-self two-stage leave, pool-to-pool two-stage switch, immature `LEAVING_POOL` rejection, duplicate/old transition rejection, and clearing `target_state` when the target lands on chain.
- Reorg tests should cover rollback before launcher creation, rollback after one or more singleton transitions, YAML mirror refresh, interested coin-id resubscription, and unconfirmed transaction behavior after rollback.
- Puzzle tests should assert tree hashes and spend solutions for member, waiting-room, p2-singleton, travel, and absorb paths against known vectors or existing CLVM behavior.
- Reward claim tests should cover no rewards, non-farming coins ignored, fee/no-fee absorb, batching limit, correct `pool_parent_id`/`calculate_pool_reward` height use, and announcement coupling with fee spends.
- Farmer integration tests should verify YAML migration/acquire behavior, self-pooling skip path, HTTPS enforcement on mainnet, `/pool_info` redirect handling, payout-instruction updates, missing auth key handling, and partial submission difficulty updates.

## Source Pointers

- Wallet pool state machine: `chia/pools/pool_wallet.py`, `chia/pools/pool_wallet_info.py`.
- Pool CLVM and singleton puzzle helpers: `chia/pools/pool_puzzles.py`.
- Farmer config mirror: `chia/pools/pool_config.py`.
- Pool HTTP protocol payloads: `chia/protocols/pool_protocol.py`.
- Pool reward coin helpers: `chia/consensus/coinbase.py`.
