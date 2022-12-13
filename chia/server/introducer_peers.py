from __future__ import annotations

import random
import time
from dataclasses import dataclass
from typing import List, Optional, Set

from chia.types.peer_info import PeerInfo
from chia.util.ints import uint16, uint64


@dataclass(frozen=False)
class VettedPeer:
    host: str
    port: uint16

    # 0 means we have not attempted to vet this peer yet
    # a negative number means we have failed that many vetting attempts in a row
    # a positive number means we have successfully vetted the peer this many
    # times in a row
    vetted: int = 0
    # the timestamp of the last *successful* vetting of this peer
    vetted_timestamp: uint64 = uint64(0)
    # the last time we attempted to vet this peer, or 0 if we haven't tried yet
    # we set this regardless of whether the vetting is successful or not
    last_attempt: uint64 = uint64(0)
    time_added: uint64 = uint64(0)

    def __eq__(self, rhs: object) -> bool:
        return self.host == rhs.host and self.port == rhs.port  # type: ignore[no-any-return, attr-defined]

    def __hash__(self) -> int:
        return hash((self.host, self.port))


class IntroducerPeers:
    """
    Has the list of known full node peers that are already connected or may be
    connected to, and the time that they were last added.
    """

    def __init__(self) -> None:
        self._peers: Set[VettedPeer] = set()

    def add(self, peer: Optional[PeerInfo]) -> bool:
        if peer is None or not peer.port:
            return False

        p = VettedPeer(peer.host, peer.port)
        p.time_added = uint64(int(time.time()))

        if p in self._peers:
            return True

        self._peers.add(p)
        return True

    def remove(self, peer: Optional[VettedPeer]) -> bool:
        if peer is None or not peer.port:
            return False
        try:
            self._peers.remove(peer)
            return True
        except ValueError:
            return False

    def get_peers(
        self, max_peers: int = 0, randomize: bool = False, recent_threshold: float = 9999999
    ) -> List[VettedPeer]:
        target_peers = [peer for peer in self._peers if time.time() - float(peer.time_added) < recent_threshold]
        if not max_peers or max_peers > len(target_peers):
            max_peers = len(target_peers)
        if randomize:
            return random.sample(target_peers, max_peers)
        else:
            return target_peers[:max_peers]
