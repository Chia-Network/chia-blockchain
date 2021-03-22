import random
import time
from typing import Dict, List, Optional

from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.peer_info import PeerInfo
from chia.util.ints import uint64


class IntroducerPeers:
    """
    Has the list of known full node peers that are already connected or may be
    connected to, and the time that they were last added.
    """

    def __init__(self):
        self._peers: List[PeerInfo] = []
        self.time_added: Dict[bytes32, uint64] = {}

    def add(self, peer: Optional[PeerInfo]) -> bool:
        if peer is None or not peer.port:
            return False
        if peer not in self._peers:
            self._peers.append(peer)
        self.time_added[peer.get_hash()] = uint64(int(time.time()))
        return True

    def remove(self, peer: Optional[PeerInfo]) -> bool:
        if peer is None or not peer.port:
            return False
        try:
            self._peers.remove(peer)
            return True
        except ValueError:
            return False

    def get_peers(self, max_peers: int = 0, randomize: bool = False, recent_threshold=9999999) -> List[PeerInfo]:
        target_peers = [
            peer for peer in self._peers if time.time() - self.time_added[peer.get_hash()] < recent_threshold
        ]
        if not max_peers or max_peers > len(target_peers):
            max_peers = len(target_peers)
        if randomize:
            random.shuffle(target_peers)
        return target_peers[:max_peers]
