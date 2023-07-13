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
    _coin_subscriptions: Dict[bytes32, Set[bytes32]] = field(default_factory=dict, init=False)
    # Puzzle Hash : Set[Peer ID]
    _ph_subscriptions: Dict[bytes32, Set[bytes32]] = field(default_factory=dict, init=False)
    # Peer ID: Set[Coin ids]
    _peer_coin_ids: Dict[bytes32, Set[bytes32]] = field(default_factory=dict, init=False)
    # Peer ID: Set[puzzle_hash]
    _peer_puzzle_hash: Dict[bytes32, Set[bytes32]] = field(default_factory=dict, init=False)
    # Peer ID: subscription count
    _peer_sub_counter: Dict[bytes32, int] = field(default_factory=dict, init=False)

    def has_ph_subscription(self, ph: bytes32) -> bool:
        return ph in self._ph_subscriptions

    def has_coin_subscription(self, coin_id: bytes32) -> bool:
        return coin_id in self._coin_subscriptions

    def add_ph_subscriptions(self, peer_id: bytes32, phs: List[bytes32], max_items: int) -> Set[bytes32]:
        """
        returns the puzzle hashes that were actually subscribed to. These may be
        fewer than requested in case:
        * there are duplicate puzzle_hashes
        * some puzzle hashes are already subscribed to
        * the max_items limit is exceeded
        """

        puzzle_hash_peers = self._peer_puzzle_hash.setdefault(peer_id, set())
        existing_sub_count = self._peer_sub_counter.setdefault(peer_id, 0)

        ret: Set[bytes32] = set()

        # if we've reached the limit on number of subscriptions, just bail
        if existing_sub_count >= max_items:
            log.info(
                "peer_id: %s reached max number of puzzle-hash subscriptions. "
                "Not all its coin states will be reported",
                peer_id,
            )
            return ret

        # decrement this counter as we go, to know if we've hit the limit of
        # number of subscriptions
        subscriptions_left = max_items - existing_sub_count

        for ph in phs:
            ph_sub = self._ph_subscriptions.setdefault(ph, set())
            if peer_id in ph_sub:
                continue

            ret.add(ph)
            ph_sub.add(peer_id)
            puzzle_hash_peers.add(ph)
            self._peer_sub_counter[peer_id] += 1
            subscriptions_left -= 1

            if subscriptions_left == 0:
                log.info(
                    "peer_id: %s reached max number of puzzle-hash subscriptions. "
                    "Not all its coin states will be reported",
                    peer_id,
                )
                break
        return ret

    def add_coin_subscriptions(self, peer_id: bytes32, coin_ids: List[bytes32], max_items: int) -> None:
        coin_id_peers = self._peer_coin_ids.setdefault(peer_id, set())
        existing_sub_count = self._peer_sub_counter.setdefault(peer_id, 0)

        # if we've reached the limit on number of subscriptions, just bail
        if existing_sub_count >= max_items:
            log.info(
                "peer_id: %s reached max number of coin subscriptions. Not all its coin states will be reported",
                peer_id,
            )
            return

        # decrement this counter as we go, to know if we've hit the limit of
        # number of subscriptions
        subscriptions_left = max_items - existing_sub_count

        for coin_id in coin_ids:
            coin_sub = self._coin_subscriptions.setdefault(coin_id, set())
            if peer_id in coin_sub:
                continue

            coin_sub.add(peer_id)
            coin_id_peers.add(coin_id)
            self._peer_sub_counter[peer_id] += 1
            subscriptions_left -= 1

            if subscriptions_left == 0:
                log.info(
                    "peer_id: %s reached max number of coin subscriptions. Not all its coin states will be reported",
                    peer_id,
                )
                break

    def remove_peer(self, peer_id: bytes32) -> None:
        counter = 0
        puzzle_hashes = self._peer_puzzle_hash.get(peer_id)
        if puzzle_hashes is not None:
            for ph in puzzle_hashes:
                subs = self._ph_subscriptions[ph]
                subs.remove(peer_id)
                counter += 1
                if subs == set():
                    self._ph_subscriptions.pop(ph)
            self._peer_puzzle_hash.pop(peer_id)

        coin_ids = self._peer_coin_ids.get(peer_id)
        if coin_ids is not None:
            for coin_id in coin_ids:
                subs = self._coin_subscriptions[coin_id]
                subs.remove(peer_id)
                counter += 1
                if subs == set():
                    self._coin_subscriptions.pop(coin_id)
            self._peer_coin_ids.pop(peer_id)

        if peer_id in self._peer_sub_counter:
            num_subs = self._peer_sub_counter.pop(peer_id)
            assert num_subs == counter

    def peers_for_coin_id(self, coin_id: bytes32) -> Set[bytes32]:
        return self._coin_subscriptions.get(coin_id, set())

    def peers_for_puzzle_hash(self, puzzle_hash: bytes32) -> Set[bytes32]:
        return self._ph_subscriptions.get(puzzle_hash, set())
