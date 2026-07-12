# Chia Wallet Tests Module Context

Verified: 2026-07-12 against a5647a9327e5. If source contradicts this doc, trust source and update the doc.

`chia/_tests/wallet/` is the main behavioral safety net for the wallet stack. It mixes fast unit tests for stores, puzzles, request types, and CLVM helpers with simulator-backed integration tests that exercise wallet sync, transaction construction, subwallet recognition, RPC endpoints, offers, and reorg handling. Treat it as a specification for wallet invariants, not just regression coverage.

## When To Read This

Read this for wallet tests, wallet fixture behavior, `wallet_environments`, wallet RPC tests, wallet store tests, asset-wallet tests, offer tests, and wallet-specific block-tool shortcuts. For source behavior, also read `wallet.md`.

## Test Harness Boundaries

- `chia/_tests/wallet/conftest.py` installs wallet-test-specific autouse patches. Unless a test is marked `standard_block_tools`, consensus-heavy block validation is shortcut and `WalletBlockTools` replaces normal `BlockTools` so wallet tests can focus on mempool acceptance, coin-state notification, and wallet DB updates.
- `wallet_environments` is the primary integration fixture. It creates one simulator full node plus N wallet services, connects each wallet to the full node, opens wallet/full-node RPC clients, optionally trusts the full node, farms initial rewards per environment, and returns a `WalletTestFramework`.
- `trusted_full_node` and `tx_config` are parametrized by default. Most `wallet_environments` tests run across trusted/untrusted sync and reuse/new-puzzle-hash modes unless the test explicitly pins `"trusted"` or `"reuse_puzhash"` in the indirect fixture params.
- `new_action_scope_wrapper()` enforces reuse-puzzle-hash behavior by comparing used derivation counts around every wallet action scope. Tests that intentionally create new puzzle hashes under reuse mode must use `WalletTestFramework.new_puzzle_hashes_allowed()`.
- `WalletBlockTools` generates structurally sufficient blocks with simplified proof/iteration fields, reward coins, transaction filters, additions/removals roots, and transaction generators. It is appropriate for wallet behavior; use `standard_block_tools` when the test depends on real consensus/header/weight-proof behavior.

## Wallet Test Framework Contract

- `WalletEnvironment` wraps a wallet service, RPC client, node API, peer server, state manager, main XCH wallet, and a local expected-balance map. Tests commonly set `wallet_aliases` such as `"xch"`, `"cat"`, `"nft"`, `"did"`, `"vc"`, or `"dl"` to make balance transitions readable.
- `WalletStateTransition` splits expected balance effects into `pre_block_*` and `post_block_*` updates. This models the wallet distinction between pending mempool state and confirmed chain state.
- `WalletTestFramework.process_pending_states()` is the main integration assertion path: wait for wallets to sync to the current peak, wait for pending transactions to enter and be marked in the mempool, apply/check pre-block balances, farm one transaction block, sync wallets to the new peak, apply/check post-block balances, verify previously pending transactions are confirmed, and re-check derivation reuse.
- Balance deltas support exact fields plus comparison keys like `"<#spendable_balance"` or `">=#pending_change"` for coin-selection-dependent values. Use this when a wallet guarantee is directional but the exact selected coins/change amount is not stable.
- New subwallet state must be initialized explicitly with `"init": True`; `"set_remainder": True` copies unspecified values from the live RPC balance. This is useful for secondary wallets but can hide unintended balance changes if overused.

## Behavioral Coverage Map

- Core XCH wallet tests exercise reward accounting, standard transaction creation, reuse-address behavior, clawback flows, fee estimation, signing, wallet DB path selection, and no-server edge cases. They usually construct spends in `WalletStateManager.new_action_scope(..., push=True)` and verify lifecycle with `process_pending_states()`.
- `test_wallet_state_manager.py`, `test_wallet_node.py`, and sync suites cover sync-mode locking, key derivation, peer trust behavior, short/long sync, backtracking, stale or bad peer data, transaction ack/retry caches, balance computation, puzzle-hash subscriptions, coin-state validation, and reorg recovery.
- `sync/test_wallet_sync.py` is marked `standard_block_tools` because it tests wallet/full-node protocol details that depend on real block/header/additions/removals behavior, request caps, weight proof fork points, and validation failures.
- `simple_sync/test_simple_sync_protocol.py` and `test_new_wallet_protocol.py` focus on wallet protocol subscriptions: puzzle hash, coin id, hint, mempool item updates, request limits, reorg responses, capability gating, and sync-by-state behavior.
- RPC tests in `rpc/` are broad endpoint integration tests, not just serialization checks. They cover send/push/create transaction paths, balance/farmed amount, coin queries and filters, CAT/DID/NFT/offer endpoints, notification RPCs, signing endpoints, resync flags, split/combine coin commands, and remote wallet RPC validation.
- CAT, NFT, DID, VC, DataLayer, remote wallet, clawback, and offer suites encode asset-specific lifecycle invariants: launcher/eve spends, singleton lineage, hints, metadata, DID ownership, VC proofs/revocation, CR-CAT approval, mirror handling, offer cancellation/conflict states, and reorg survival.
- Store tests (`wallet_coin_store`, `transaction_store`, `puzzle_store`, `wallet_interested_store`, `trade_store`, singleton/NFT/key-val stores) are persistence-contract tests. They matter for rollback, filtering, total-count caching, legacy migrations, unconfirmed caches, and restart behavior.
- Puzzle/CLVM/unit suites (`singleton`, CAT/NFT/VC lifecycle fast tests, outer puzzle tests, conditions, signer protocol, taproot, bech32m, CLVM streamable/casts) are deterministic low-level guards and often run without simulator services.

## Editing Guidance

- Prefer `wallet_environments` for user-visible wallet behavior, subwallet transactions, RPC flows, and balance lifecycle assertions. Prefer smaller store/unit fixtures when the behavior under test is local persistence, parsing, puzzle construction, or pure CLVM.
- When a test creates wallet transactions, keep the lifecycle explicit: action scope, staged transactions, mempool entry, block confirmation, wallet sync, then store/balance assertions. Avoid final-only checks that can pass while pending-state behavior regresses.
- Do not replace `process_pending_states()` with raw sleeps or one-off balance polling unless the framework cannot model the scenario. If it cannot, document the missing lifecycle step in the test.
- Be careful with fixture parametrization. A test that is only meaningful in trusted mode, untrusted mode, reuse mode, or fresh-derivation mode should pin that mode in the indirect fixture params; otherwise it silently multiplies runtime and may assert the wrong invariant.
- Use `standard_block_tools` for tests that inspect consensus-valid block structure, weight proof/header behavior, BIP158 filters, additions/removals proofs, or request-header protocol details. The default wallet block patches intentionally bypass much of that.
- Reorg tests should assert both wallet-visible state and durable stores. Many wallet bugs only appear when interested coin IDs, race caches, unconfirmed transactions, singleton records, or remote/interested stores are rolled back and then reprocessed.
- For asset tests, assert identity through the asset's authority: CAT TAIL hash, singleton launcher id, NFT/DID/VC lineage, DataLayer launcher/root records, or offer/trade id. Wallet id/order alone is too weak.

## Fragility Hotspots

- The autouse patches are part of the test architecture. Changing them alters the meaning and runtime of nearly every wallet integration test.
- `reuse_puzhash` failures usually indicate a transaction path derived a fresh address outside the intended action-scope/config boundary.
- Balance assertions are intentionally stateful. After a negative-path `process_pending_states()` raises, tests may need to restore local expected balances before continuing.
- Trusted and untrusted sync paths intentionally diverge. If a test covers peer validation, stale proofs, rollback, or state-from-peer behavior, run or pin the mode that exercises the relevant branch.
- RPC tests often share helpers and fixtures from CAT/store tests. Moving helpers can create import cycles or make supposedly endpoint-level tests depend on broader asset setup.

## Source Pointers

- Wallet test fixtures and framework: `chia/_tests/wallet/conftest.py`, `chia/_tests/environments/wallet.py`.
- Shared wallet source context: `chia/wallet/wallet_node.py`, `chia/wallet/wallet_state_manager.py`, `chia/wallet/wallet_rpc_api.py`.
