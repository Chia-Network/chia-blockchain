from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Set

from chia_rs import Coin

from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.spend_bundle_conditions import SpendBundleConditions
from chia.util.ints import uint64

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class SubscriptionSet:
    _subscriptions_for_peer: Dict[bytes32, Set[bytes32]] = field(default_factory=dict, init=False)
    _peers_for_subscription: Dict[bytes32, Set[bytes32]] = field(default_factory=dict, init=False)

    def add_subscription(self, peer_id: bytes32, item: bytes32) -> bool:
        peers = self._peers_for_subscription.setdefault(item, set())

        if peer_id in peers:
            return False

        subscriptions = self._subscriptions_for_peer.setdefault(peer_id, set())
        subscriptions.add(item)
        peers.add(peer_id)

        return True

    def remove_subscription(self, peer_id: bytes32, item: bytes32) -> bool:
        subscriptions = self._subscriptions_for_peer.get(peer_id)

        if subscriptions is None or item not in subscriptions:
            return False

        peers = self._peers_for_subscription[item]
        peers.remove(peer_id)
        subscriptions.remove(item)

        if len(subscriptions) == 0:
            self._subscriptions_for_peer.pop(peer_id)

        if len(peers) == 0:
            self._peers_for_subscription.pop(item)

        return True

    def has_subscription(self, item: bytes32) -> bool:
        return item in self._peers_for_subscription

    def count_subscriptions(self, peer_id: bytes32) -> int:
        return len(self._subscriptions_for_peer.get(peer_id, {}))

    def remove_peer(self, peer_id: bytes32) -> None:
        for item in self._subscriptions_for_peer.pop(peer_id, {}):
            self._peers_for_subscription[item].remove(peer_id)

            if len(self._peers_for_subscription[item]) == 0:
                self._peers_for_subscription.pop(item)

    def subscriptions(self, peer_id: bytes32) -> Set[bytes32]:
        return self._subscriptions_for_peer.get(peer_id, set())

    def peers(self, item: bytes32) -> Set[bytes32]:
        return self._peers_for_subscription.get(item, set())

    def total_count(self) -> int:
        return len(self._peers_for_subscription)


@dataclass(frozen=True)
class PeerSubscriptions:
    _puzzle_subscriptions: SubscriptionSet = field(default_factory=SubscriptionSet)
    _coin_subscriptions: SubscriptionSet = field(default_factory=SubscriptionSet)

    def has_puzzle_subscription(self, puzzle_hash: bytes32) -> bool:
        return self._puzzle_subscriptions.has_subscription(puzzle_hash)

    def has_coin_subscription(self, coin_id: bytes32) -> bool:
        return self._coin_subscriptions.has_subscription(coin_id)

    def peer_subscription_count(self, peer_id: bytes32) -> int:
        puzzle_subscriptions = self._puzzle_subscriptions.count_subscriptions(peer_id)
        coin_subscriptions = self._coin_subscriptions.count_subscriptions(peer_id)
        return puzzle_subscriptions + coin_subscriptions

    def add_puzzle_subscriptions(self, peer_id: bytes32, puzzle_hashes: List[bytes32], max_items: int) -> Set[bytes32]:
        """
        Adds subscriptions until max_items is reached. Filters out duplicates and returns all additions.
        """

        subscription_count = self.peer_subscription_count(peer_id)
        added: Set[bytes32] = set()

        def limit_reached() -> Set[bytes32]:
            log.info(
                "Peer %s attempted to exceed the subscription limit while adding puzzle subscriptions.",
                peer_id,
            )
            return added

        # If the subscription limit is reached, bail.
        if subscription_count >= max_items:
            return limit_reached()

        # Decrement this counter to know if we've hit the subscription limit.
        subscriptions_left = max_items - subscription_count

        for puzzle_hash in puzzle_hashes:
            if not self._puzzle_subscriptions.add_subscription(peer_id, puzzle_hash):
                continue

            subscriptions_left -= 1
            added.add(puzzle_hash)

            if subscriptions_left == 0:
                return limit_reached()

        return added

    def add_coin_subscriptions(self, peer_id: bytes32, coin_ids: List[bytes32], max_items: int) -> Set[bytes32]:
        """
        Adds subscriptions until max_items is reached. Filters out duplicates and returns all additions.
        """

        subscription_count = self.peer_subscription_count(peer_id)
        added: Set[bytes32] = set()

        def limit_reached() -> Set[bytes32]:
            log.info(
                "Peer %s attempted to exceed the subscription limit while adding coin subscriptions.",
                peer_id,
            )
            return added

        # If the subscription limit is reached, bail.
        if subscription_count >= max_items:
            return limit_reached()

        # Decrement this counter to know if we've hit the subscription limit.
        subscriptions_left = max_items - subscription_count

        for coin_id in coin_ids:
            if not self._coin_subscriptions.add_subscription(peer_id, coin_id):
                continue

            subscriptions_left -= 1
            added.add(coin_id)

            if subscriptions_left == 0:
                return limit_reached()

        return added

    def remove_puzzle_subscriptions(self, peer_id: bytes32, puzzle_hashes: List[bytes32]) -> Set[bytes32]:
        """
        Removes subscriptions. Filters out duplicates and returns all removals.
        """

        removed: Set[bytes32] = set()

        for puzzle_hash in puzzle_hashes:
            if not self._puzzle_subscriptions.remove_subscription(peer_id, puzzle_hash):
                continue

            removed.add(puzzle_hash)

        return removed

    def remove_coin_subscriptions(self, peer_id: bytes32, coin_ids: List[bytes32]) -> Set[bytes32]:
        """
        Removes subscriptions. Filters out duplicates and returns all removals.
        """

        removed: Set[bytes32] = set()

        for coin_id in coin_ids:
            if not self._coin_subscriptions.remove_subscription(peer_id, coin_id):
                continue

            removed.add(coin_id)

        return removed

    def clear_puzzle_subscriptions(self, peer_id: bytes32) -> None:
        self._puzzle_subscriptions.remove_peer(peer_id)

    def clear_coin_subscriptions(self, peer_id: bytes32) -> None:
        self._coin_subscriptions.remove_peer(peer_id)

    def remove_peer(self, peer_id: bytes32) -> None:
        self._puzzle_subscriptions.remove_peer(peer_id)
        self._coin_subscriptions.remove_peer(peer_id)

    def coin_subscriptions(self, peer_id: bytes32) -> Set[bytes32]:
        return self._coin_subscriptions.subscriptions(peer_id)

    def puzzle_subscriptions(self, peer_id: bytes32) -> Set[bytes32]:
        return self._puzzle_subscriptions.subscriptions(peer_id)

    def peers_for_coin_id(self, coin_id: bytes32) -> Set[bytes32]:
        return self._coin_subscriptions.peers(coin_id)

    def peers_for_puzzle_hash(self, puzzle_hash: bytes32) -> Set[bytes32]:
        return self._puzzle_subscriptions.peers(puzzle_hash)

    def coin_subscription_count(self) -> int:
        return self._coin_subscriptions.total_count()

    def puzzle_subscription_count(self) -> int:
        return self._puzzle_subscriptions.total_count()


def peers_for_spend_bundle(
    peer_subscriptions: PeerSubscriptions, conds: SpendBundleConditions, hints_for_removals: Set[bytes32]
) -> Set[bytes32]:
    """
    Returns a list of peer ids that are subscribed to any of the created or
    spent coins, puzzle hashes, or hints in the spend bundle. To avoid repeated
    lookups, `hints_for_removals` should be a set of all puzzle hashes that are being removed.
    """

    coin_ids: Set[bytes32] = set()
    puzzle_hashes: Set[bytes32] = hints_for_removals.copy()

    for spend in conds.spends:
        coin_ids.add(bytes32(spend.coin_id))
        puzzle_hashes.add(bytes32(spend.puzzle_hash))

        for puzzle_hash, amount, memo in spend.create_coin:
            coin_ids.add(Coin(spend.coin_id, puzzle_hash, uint64(amount)).name())
            puzzle_hashes.add(bytes32(puzzle_hash))

            if memo is not None and len(memo) == 32:
                puzzle_hashes.add(bytes32(memo))

    peers: Set[bytes32] = set()

    for coin_id in coin_ids:
        peers |= peer_subscriptions.peers_for_coin_id(coin_id)

    for puzzle_hash in puzzle_hashes:
        peers |= peer_subscriptions.peers_for_puzzle_hash(puzzle_hash)

    return peers
