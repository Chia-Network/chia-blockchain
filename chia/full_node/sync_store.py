import asyncio
import logging
from typing import Dict, List, Optional, Set, Tuple

from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.ints import uint32, uint128

log = logging.getLogger(__name__)


class SyncStore:
    # Whether or not we are syncing
    sync_mode: bool
    long_sync: bool
    peak_to_peer: Dict[bytes32, Set[bytes32]]  # Header hash : peer node id
    peer_to_peak: Dict[bytes32, Tuple[bytes32, uint32, uint128]]  # peer node id : [header_hash, height, weight]
    sync_target_header_hash: Optional[bytes32]  # Peak hash we are syncing towards
    sync_target_height: Optional[uint32]  # Peak height we are syncing towards
    peers_changed: asyncio.Event
    batch_syncing: Set[bytes32]  # Set of nodes which we are batch syncing from
    backtrack_syncing: Dict[bytes32, int]  # Set of nodes which we are backtrack syncing from, and how many threads

    @classmethod
    async def create(cls):
        self = cls()

        self.sync_mode = False
        self.long_sync = False
        self.sync_target_header_hash = None
        self.sync_target_height = None
        self.peak_fork_point = {}
        self.peak_to_peer = {}
        self.peer_to_peak = {}
        self.peers_changed = asyncio.Event()

        self.batch_syncing = set()
        self.backtrack_syncing = {}
        return self

    def set_peak_target(self, peak_hash: bytes32, target_height: uint32):
        self.sync_target_header_hash = peak_hash
        self.sync_target_height = target_height

    def get_sync_target_hash(self) -> Optional[bytes32]:
        return self.sync_target_header_hash

    def get_sync_target_height(self) -> Optional[uint32]:
        return self.sync_target_height

    def set_sync_mode(self, sync_mode: bool):
        self.sync_mode = sync_mode

    def get_sync_mode(self) -> bool:
        return self.sync_mode

    def set_long_sync(self, long_sync: bool):
        self.long_sync = long_sync

    def get_long_sync(self) -> bool:
        return self.long_sync

    def seen_header_hash(self, header_hash: bytes32) -> bool:
        return header_hash in self.peak_to_peer

    def peer_has_block(self, header_hash: bytes32, peer_id: bytes32, weight: uint128, height: uint32, new_peak: bool):
        """
        Adds a record that a certain peer has a block.
        """

        if header_hash == self.sync_target_header_hash:
            self.peers_changed.set()
        if header_hash in self.peak_to_peer:
            self.peak_to_peer[header_hash].add(peer_id)
        else:
            self.peak_to_peer[header_hash] = {peer_id}

        if new_peak:
            self.peer_to_peak[peer_id] = (header_hash, height, weight)

    def get_peers_that_have_peak(self, header_hashes: List[bytes32]) -> Set[bytes32]:
        """
        Returns: peer ids of peers that have at least one of the header hashes.
        """

        node_ids: Set[bytes32] = set()
        for header_hash in header_hashes:
            if header_hash in self.peak_to_peer:
                for node_id in self.peak_to_peer[header_hash]:
                    node_ids.add(node_id)
        return node_ids

    def get_peak_of_each_peer(self) -> Dict[bytes32, Tuple[bytes32, uint32, uint128]]:
        """
        Returns: dictionary of peer id to peak information.
        """

        ret = {}
        for peer_id, v in self.peer_to_peak.items():
            if v[0] not in self.peak_to_peer:
                continue
            ret[peer_id] = v
        return ret

    def get_heaviest_peak(self) -> Optional[Tuple[bytes32, uint32, uint128]]:
        """
        Returns: the header_hash, height, and weight of the heaviest block that one of our peers has notified
        us of.
        """

        if len(self.peer_to_peak) == 0:
            return None
        heaviest_peak_hash: Optional[bytes32] = None
        heaviest_peak_weight: uint128 = uint128(0)
        heaviest_peak_height: Optional[uint32] = None
        for peer_id, (peak_hash, height, weight) in self.peer_to_peak.items():
            if peak_hash not in self.peak_to_peer:
                continue
            if heaviest_peak_hash is None or weight > heaviest_peak_weight:
                heaviest_peak_hash = peak_hash
                heaviest_peak_weight = weight
                heaviest_peak_height = height
        assert heaviest_peak_hash is not None and heaviest_peak_weight is not None and heaviest_peak_height is not None
        return heaviest_peak_hash, heaviest_peak_height, heaviest_peak_weight

    async def clear_sync_info(self):
        """
        Clears the peak_to_peer info which can get quite large.
        """
        self.peak_to_peer = {}

    def peer_disconnected(self, node_id: bytes32):
        if node_id in self.peer_to_peak:
            del self.peer_to_peak[node_id]

        for peak, peers in self.peak_to_peer.items():
            if node_id in peers:
                self.peak_to_peer[peak].remove(node_id)
            assert node_id not in self.peak_to_peer[peak]
        self.peers_changed.set()
