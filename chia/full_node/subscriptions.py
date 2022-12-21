from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

from chia.types.blockchain_format.sized_bytes import bytes32


def _get_or_add_set(c: Dict[bytes32, Set[bytes32]], key: bytes32) -> Set[bytes32]:
    ret: Optional[Set[bytes32]] = c.get(key)
    if ret is not None:
        return ret

    ret2: Set[bytes32] = set()
    c[key] = ret2
    return ret2


# The PeerSubscriptions class is essentially a multi-index container. It can be
# indexed by peer_id, coin_id and puzzle_hash.
@dataclass
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

    def has_ph_sub(self, ph: bytes32) -> bool:
        return ph in self._ph_subscriptions

    def has_coin_sub(self, coin_id: bytes32) -> bool:
        return coin_id in self._coin_subscriptions

    def add_ph_subscriptions(self, peer_id: bytes32, phs: List[bytes32], max_items: int) -> None:
        puzzle_hash_peers = _get_or_add_set(self._peer_puzzle_hash, peer_id)

        existing_sub_count = self._peer_sub_counter.get(peer_id)
        if existing_sub_count is None:
            self._peer_sub_counter[peer_id] = 0
            existing_sub_count = 0

        # if we've reached the limit on number of subscriptions, just bail
        if existing_sub_count >= max_items:
            return

        # decrement this counter as we go, to know if we've hit the limit of
        # number of subscriptions
        subscriptions_left = max_items - existing_sub_count

        for ph in phs:
            ph_sub: Optional[Set[bytes32]] = self._ph_subscriptions.get(ph)
            if ph_sub is None:
                ph_sub = set()
                self._ph_subscriptions[ph] = ph_sub
            elif peer_id in ph_sub:
                continue

            ph_sub.add(peer_id)
            puzzle_hash_peers.add(ph)
            self._peer_sub_counter[peer_id] += 1
            subscriptions_left -= 1

            if subscriptions_left == 0:
                break

    def add_coin_subscriptions(self, peer_id: bytes32, coin_ids: List[bytes32], max_items: int) -> None:

        coin_id_peers = _get_or_add_set(self._peer_coin_ids, peer_id)

        existing_sub_count = self._peer_sub_counter.get(peer_id)
        if existing_sub_count is None:
            self._peer_sub_counter[peer_id] = 0
            existing_sub_count = 0

        # if we've reached the limit on number of subscriptions, just bail
        if existing_sub_count >= max_items:
            return

        # decrement this counter as we go, to know if we've hit the limit of
        # number of subscriptions
        subscriptions_left = max_items - existing_sub_count

        for coin_id in coin_ids:
            coin_sub: Optional[Set[bytes32]] = self._coin_subscriptions.get(coin_id)
            if coin_sub is None:
                coin_sub = set()
                self._coin_subscriptions[coin_id] = coin_sub
            elif peer_id in coin_sub:
                continue

            coin_sub.add(peer_id)
            coin_id_peers.add(coin_id)
            self._peer_sub_counter[peer_id] += 1
            subscriptions_left -= 1

            if subscriptions_left == 0:
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
