from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Set

from chia.types.blockchain_format.sized_bytes import bytes32

log = logging.getLogger(__name__)


# The PeerSubscriptions class is essentially a multi-index container. It can be
# indexed by peer_id, coin_id and puzzle_hash.
@dataclass(frozen=True)
class PeerSubscriptions:
    # TODO: use NewType all over to describe these various uses of the same types
    # Puzzle Hash : Set[Peer ID]
    _coin_id_subscriptions: Dict[bytes32, Set[bytes32]] = field(default_factory=dict, init=False)
    # Puzzle Hash : Set[Peer ID]
    _puzzle_hash_subscriptions: Dict[bytes32, Set[bytes32]] = field(default_factory=dict, init=False)
    # Peer ID: Set[Coin ids]
    _peer_coin_ids: Dict[bytes32, Set[bytes32]] = field(default_factory=dict, init=False)
    # Peer ID: Set[puzzle_hash]
    _peer_puzzle_hashes: Dict[bytes32, Set[bytes32]] = field(default_factory=dict, init=False)
    # Peer ID: subscription count
    _peer_subscription_counter: Dict[bytes32, int] = field(default_factory=dict, init=False)

    def has_puzzle_hash_subscription(self, puzzle_hash: bytes32) -> bool:
        return puzzle_hash in self._puzzle_hash_subscriptions

    def has_coin_id_subscription(self, coin_id: bytes32) -> bool:
        return coin_id in self._coin_id_subscriptions

    def add_puzzle_hash_subscriptions(self, peer_id: bytes32, puzzle_hashes: List[bytes32], max_items: int) -> None:
        peer_puzzle_hashes = self._peer_puzzle_hashes.setdefault(peer_id, set())
        existing_subscription_count = self._peer_subscription_counter.setdefault(peer_id, 0)

        # if we've reached the limit on number of subscriptions, just bail
        if existing_subscription_count >= max_items:
            log.info(
                "peer_id: %s reached max number of puzzle-hash subscriptions. "
                "Not all its coin states will be reported",
                peer_id,
            )
            return

        # decrement this counter as we go, to know if we've hit the limit of
        # number of subscriptions
        subscriptions_left = max_items - existing_subscription_count

        for puzzle_hash in puzzle_hashes:
            puzzle_hash_subscriptions = self._puzzle_hash_subscriptions.setdefault(puzzle_hash, set())
            if peer_id in puzzle_hash_subscriptions:
                continue

            puzzle_hash_subscriptions.add(peer_id)
            peer_puzzle_hashes.add(puzzle_hash)
            self._peer_subscription_counter[peer_id] += 1
            subscriptions_left -= 1

            if subscriptions_left == 0:
                log.info(
                    "peer_id: %s reached max number of puzzle-hash subscriptions. "
                    "Not all its coin states will be reported",
                    peer_id,
                )
                break

    def add_coin_id_subscriptions(self, peer_id: bytes32, coin_ids: List[bytes32], max_items: int) -> None:
        peer_coin_ids = self._peer_coin_ids.setdefault(peer_id, set())
        existing_subscription_count = self._peer_subscription_counter.setdefault(peer_id, 0)

        # if we've reached the limit on number of subscriptions, just bail
        if existing_subscription_count >= max_items:
            log.info(
                "peer_id: %s reached max number of coin subscriptions. Not all its coin states will be reported",
                peer_id,
            )
            return

        # decrement this counter as we go, to know if we've hit the limit of
        # number of subscriptions
        subscriptions_left = max_items - existing_subscription_count

        for coin_id in coin_ids:
            coin_id_subscriptions = self._coin_id_subscriptions.setdefault(coin_id, set())
            if peer_id in coin_id_subscriptions:
                continue

            coin_id_subscriptions.add(peer_id)
            peer_coin_ids.add(coin_id)
            self._peer_subscription_counter[peer_id] += 1
            subscriptions_left -= 1

            if subscriptions_left == 0:
                log.info(
                    "peer_id: %s reached max number of coin subscriptions. Not all its coin states will be reported",
                    peer_id,
                )
                break

    def remove_peer(self, peer_id: bytes32) -> None:

        removed_subscriptions = 0
        puzzle_hashes = self._peer_puzzle_hashes.get(peer_id)
        if puzzle_hashes is not None:
            for puzzle_hash in puzzle_hashes:
                subscriptions = self._puzzle_hash_subscriptions[puzzle_hash]
                subscriptions.remove(peer_id)
                removed_subscriptions += 1
                if subscriptions == set():
                    self._puzzle_hash_subscriptions.pop(puzzle_hash)
            self._peer_puzzle_hashes.pop(peer_id)

        coin_ids = self._peer_coin_ids.get(peer_id)
        if coin_ids is not None:
            for coin_id in coin_ids:
                subscriptions = self._coin_id_subscriptions[coin_id]
                subscriptions.remove(peer_id)
                removed_subscriptions += 1
                if subscriptions == set():
                    self._coin_id_subscriptions.pop(coin_id)
            self._peer_coin_ids.pop(peer_id)

        if peer_id in self._peer_subscription_counter:
            peer_subscription_count = self._peer_subscription_counter.pop(peer_id)
            assert peer_subscription_count == removed_subscriptions

    def peers_for_coin_id(self, coin_id: bytes32) -> Set[bytes32]:
        return self._coin_id_subscriptions.get(coin_id, set())

    def peers_for_puzzle_hash(self, puzzle_hash: bytes32) -> Set[bytes32]:
        return self._puzzle_hash_subscriptions.get(puzzle_hash, set())
