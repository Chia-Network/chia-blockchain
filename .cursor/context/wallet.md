# Chia Wallet Module Context

Verified: 2026-07-12 against 24db9ad3901d. If source contradicts this doc, trust source and update the doc.

`chia/wallet/` is the SPV wallet, transaction-construction, subwallet, offer, and wallet-RPC boundary. Its safety properties are distributed across the wallet node's peer trust model, `WalletStateManager`'s state ownership, action-scope staging, SQLite stores, and CLVM puzzle-driver conventions. Do not treat any single wallet class as the source of truth without checking the surrounding persistence and sync path.

## When To Read This

Read this for wallet sync, key/derivation state, transaction construction, wallet RPC transaction endpoints, asset wallets, offers, signing, and wallet-owned persistence. For consensus acceptance or full-node mempool policy, read `consensus.md` or `full-node.md`.

## Landmarks

| file                                  | owns                                                |
| ------------------------------------- | --------------------------------------------------- |
| `chia/wallet/wallet_state_manager.py` | central wallet state, coin/tx records, side effects |
| `chia/wallet/wallet_node.py`          | SPV peer sync, trusted/untrusted proof validation   |
| `chia/wallet/wallet_action_scope.py`  | transaction side-effect staging boundary            |
| `chia/wallet/wallet.py`               | standard spend construction                         |
| `chia/wallet/wallet_rpc_api.py`       | tx endpoint gating, TXConfig autofill               |
| `chia/wallet/coin_selection.py`       | coin selection accounting/exclusions                |
| `chia/wallet/outer_puzzles.py`        | puzzle-driver registry for layered assets           |
| `chia/wallet/trade_manager.py`        | offer/trade lifecycle, interested subscriptions     |

## Implementation Authority

- `WalletStateManager` owns wallet identity, derivation state, coin records, transaction records, subwallet registry, interested coin/puzzle subscriptions, and side-effect application. Subwallet classes build wallet-specific spends, but state ownership and cross-wallet coordination remain centralized here.
- `WalletNode` is the peer-facing SPV coordinator. Full-node messages are typed protocol payloads, not chain authority; trusted peers bypass much of the proof machinery, while untrusted peers require weight-proof/header/Merkle validation before wallet state can be accepted.
- `WalletActionScope` is the transaction side-effect boundary. Spend builders stage transactions, signing responses, extra spends, singleton records, selected coins, and unused derivation records; persistence/signing/push behavior happens after the scope exits through `add_pending_transactions()`.
- Wallet RPC transaction endpoints are not thin method calls. `tx_endpoint()` gates sync/connectivity, autofills `TXConfig`, folds in extra conditions and absolute timelocks, rejects relative timelocks, opens the action scope, and then normalizes signing/push response metadata.
- Puzzle drivers in `outer_puzzles.py` are the registry authority for reconstructing and solving layered assets. `PuzzleInfo.type()` determines the driver; layer ordering and recursive `also` data are part of the asset contract.

## Mutation Ordering Contracts

- New transaction creation must preserve the action-scope lifecycle: select coins and derive puzzle hashes inside the scope, append staged `TransactionRecord`s, then let scope exit merge spends, sign, persist, subscribe to additions/removals, push if requested, and commit any unused derivation result only when `push=True`.
- `WalletActionConfig.adjust_for_side_effects()` feeds selected coin IDs back into `TXConfig.excluded_coin_ids`. Nested or multi-step spends rely on this to avoid selecting the same coin twice before any DB mutation exists.
- `WalletStateManager.lock` protects wallet state transitions that cross stores, network acks, and coin-state ingestion. Review changes that move DB writes, queue removal, or transaction-state updates outside this lock as ordering changes, not style edits.
- `WalletCoinStore` derives spent state from the stored spent height on insert. Rollback deletes coins confirmed after the target height and unspends coins spent after it; code that updates only one representation creates contradictory balance views.
- `WalletTransactionStore` has primary serialized transaction blobs plus side tables for condition-valid-times and in-memory unconfirmed caches. `rollback_to_block()` only deletes `transaction_record` rows above the target height and resets `tx_submitted`; it does not delete condition-valid-time rows or reload `unconfirmed_txs`. `WalletStateManager.reorg_rollback()` selectively re-adds certain transaction types afterward. Treat full three-representation synchronization as a review invariant, not a guarantee of the current rollback path.
- `WalletInterestedStore` is the durable counterpart to in-memory interested caches. Unknown CATs, non-HD subscriptions, trade coin interests, and retry state depend on store/cache consistency across restart and reorg.

## Sync And Peer Trust

- `NewPeakQueue` priority is semantic: coin-id subscriptions, puzzle-hash subscriptions, and coin-state updates are processed before `new_peak_wallet` because full nodes send relevant state before the corresponding peak. Reordering this queue can make otherwise valid updates look unverifiable.
- `finished_sync_up_to` is advanced only when long sync completes or when a peer already considered synced reports a peak. Rollback may lower it via the blockchain store; using it as "current network height" conflates local wallet validation progress with peer announcements.
- `synced_peers` is per-peer wallet-sync state, not a global proof of wallet freshness. Peer disconnect clears peer caches and synced status; trusted-peer disconnect also resets local-node synced state and may restart peer discovery.
- Trusted sync processes coin states and reorgs directly against local assumptions. Untrusted sync validates creation/spend proofs against additions/removals roots, header inclusion, wallet chain state, and cached race data that exists because coin-state updates can arrive before the validating peak.
- `CoinState(created_height=None)` is used for reorg/removal-from-chain semantics. Treating it as merely "unknown height" loses rollback meaning.
- `PeerRequestCache` is per-peer and height-sensitive. Cached validation or fetched headers must be cleared past fork height; race-cache entries are applied only when the later peak/backtrack path makes their height meaningful.

## Transaction, Signing, And RPC Boundaries

- Standard wallet spend construction balances removals against additions plus fee unless explicitly using special internal paths such as negative change. Coin selection must account for confirmed wallet coins, pending removals, trade locks, current action-scope selected coins, and user-supplied min/max/exclusion config.
- `TransactionEndpointRequest.to_json_dict()` is intentionally banned for transport; callers must use `json_serialize_for_transport()` so tx config, timelocks, and extra conditions are not silently dropped.
- Signing can be local, absent, or supplemented by additional signing responses. Offline/remote signing flows pass unsigned spends plus hook/path/sum hints and expect responses to bind back to the intended spend bundle.
- `merge_spends` can rewrite transaction names and concentrate the aggregate spend bundle on one transaction record. Code that keys follow-up behavior by tx name must account for post-merge identity, not just pre-build records.
- `parse_timelock_info()` collapses duplicated timelock conditions with min/max rules, and transaction RPCs reject relative timelocks even though condition parsing can represent them.
- Mempool acks are accepted only when matching an in-flight send marker for that peer. Stale or unsolicited acks are ignored; failed trusted/untrusted paths differ when the peer reports syncing-related rejection.

## Assets, Singletons, And Puzzle Drivers

- CAT identity is the TAIL/limitations-program hash. CAT validity depends on ring accounting across the spend bundle and lineage proofs shaped as parent id, inner puzzle hash, and amount.
- DID, NFT, VC, and DataLayer-style singleton assets derive identity from the launcher coin name. Their puzzle hashes bind the singleton top layer, launcher id/hash, and current inner layer; lineage proofs must match the previous coin, previous inner puzzle hash, and previous amount, with eve/launch spends using special reduced forms.
- Ownership recognition is local. Hints and fetched parent spends can reveal candidate assets, but `puzzle_store` derivation records decide whether the inner puzzle belongs to this wallet.
- DID/NFT/VC handlers reconstruct current state from parent spends plus local stores. DID amount oddness, NFT singleton lineage, VC amount-one expectations, and VC proof hashes are cross-module assumptions used by spend builders and recognizers.
- Credential-restricted CAT and VC approval flows cross several authorities: CAT lineage, VC singleton lineage, DID ownership/announcements, proof hashes, and provider lists. Offer approval code has special-case assumptions around single VC/proof-checker shape.
- Driver recursion is layer-order sensitive: CAT/CR, singleton/metadata/ownership/transfer, and VC revocation/metadata/covenant layers must be reconstructed and solved in the same order they were matched.

## Offers And Trading State

- External offers enter as compressed/bech32 `Offer` values and are decompressed into spend bundles plus driver dictionaries. Requested payments are notarized from sorted offered coins; duplicate requested payments and missing requested-asset drivers are rejected at construction.
- `Offer.fees()` is accounting metadata, not a validation authority. Spend validity still comes from CLVM execution, announcement assertions, and wallet/full-node admission paths.
- `TradeStore` records are keyed by trade id and deduplicated by offer name. It also mirrors coin interests into side tables so accept/confirm/cancel tracking can react to wallet coin updates.
- Saving a trade registers non-offer additions/removals as interested coin ids. Removing or reclassifying trade side effects without updating interested subscriptions can make future wallet state look unrelated to the trade.

## Fragility Hotspots

- High-risk edits move work across action-scope exit, wallet-state locks, DB writer boundaries, or queue priority boundaries. These are behavioral contracts even when the code looks like plumbing.
- Store schemas carry compatibility baggage: some values are legacy serialized blobs, some columns store bytes while names imply text/hex, and request parsing accepts both old and new JSON shapes.
- Many asset recognizers and drivers depend on positional CLVM structure, dynamic `PuzzleInfo`/`Solver` fields, and `assert`-style invariants. Review parser changes with actual parent-spend and layer-order examples.
- Wallet sync tests often need to assert ordering effects rather than return values: state update before peak, trusted vs untrusted rollback, race-cache application, ack matching, and action-scope commit timing.
- Mutable defaults remain in some wallet APIs for historical reasons. Before assuming per-call isolation, check whether a list/dict is copied at the boundary or shared through the class/function default.

## Source Pointers

For coin-selection, sync, RPC, action-scope, puzzle-driver, and trade-manager behavior, read the files in the Landmarks table above. For persistence, timelock, and offer boundaries not landmarked, read `chia/wallet/wallet_transaction_store.py`, `chia/wallet/wallet_interested_store.py`, `chia/wallet/conditions.py`, `chia/wallet/trading/offer.py`, and `chia/wallet/trading/trade_store.py`.
