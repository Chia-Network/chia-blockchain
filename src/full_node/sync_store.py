import asyncio
import logging
from typing import Dict, List, Optional, Tuple, Set

from src.types.sized_bytes import bytes32
from src.util.ints import uint32, uint128

log = logging.getLogger(__name__)


class SyncStore:
    # Whether or not we are syncing
    sync_mode: bool
    peak_to_peer: Dict[bytes32, List[bytes32]]  # Header hash : peer node id
    peer_to_peak: Dict[bytes32, Tuple[bytes32, uint32, uint128]]  # peer node id : [header_hash, height, weight]
    sync_hash_target: Optional[bytes32]  # Peak hash we are syncing towards
    sync_height_target: Optional[uint32]  # Peak height we are syncing towards
    peers_changed: asyncio.Event
    batch_syncing: Set[bytes32]  # Set of nodes which we are batch syncing from

    @classmethod
    async def create(cls):
        self = cls()

        self.sync_mode = False
        self.sync_hash_target = None
        self.sync_height_target = None
        self.peak_fork_point = {}
        self.peak_to_peer = {}
        self.peer_to_peak = {}
        self.peers_changed = asyncio.Event()

        self.batch_syncing = set()
        return self

    def set_peak_target(self, peak_hash: bytes32, target_sub_height: uint32):
        self.sync_hash_target = peak_hash
        self.sync_height_target = target_sub_height

    def get_sync_target_hash(self) -> Optional[bytes32]:
        return self.sync_hash_target

    def get_sync_target_height(self) -> Optional[bytes32]:
        return self.sync_height_target

    def set_sync_mode(self, sync_mode: bool):
        self.sync_mode = sync_mode

    def get_sync_mode(self) -> bool:
        return self.sync_mode

    def add_peak_peer(self, peak_hash: bytes32, peer_id: bytes32, weight: uint128, sub_height: uint32):
        if peak_hash == self.sync_hash_target:
            self.peers_changed.set()
        if peak_hash in self.peak_to_peer:
            self.peak_to_peer[peak_hash].append(peer_id)
        else:
            self.peak_to_peer[peak_hash] = [peer_id]
        self.set_peer_peak(peer_id, sub_height, weight, peak_hash)

    def set_peer_peak(self, peer_id: bytes32, sub_height: uint32, weight: uint128, peak_hash: bytes32):
        self.peer_to_peak[peer_id] = (peak_hash, sub_height, weight)

    def get_peak_peers(self, header_hash) -> List[bytes32]:
        if header_hash in self.peak_to_peer:
            return self.peak_to_peer[header_hash]
        else:
            return []

    def get_peer_peaks(self, current_peers: List[bytes32]) -> Dict[bytes32, Tuple[bytes32, uint32, uint128]]:
        ret = {}
        for peer_id, v in self.peer_to_peak.items():
            if v[0] not in self.peak_to_peer:
                # log.info(f"get_peer_peaks filter {v[0]} not in self.peak_to_peer {self.peak_to_peer}")
                continue
            if peer_id in current_peers:
                ret[peer_id] = v
        return ret

    def get_heaviest_peak(self, current_peers: List[bytes32]) -> Optional[Tuple[bytes32, uint32, uint128]]:
        if len(self.get_peer_peaks(current_peers)) == 0:
            return None
        heaviest_peak_hash: Optional[bytes32] = None
        heaviest_peak_weight: uint128 = uint128(0)
        heaviest_peak_height: Optional[uint32] = None
        for peer_id, (peak_hash, sub_height, weight) in self.peer_to_peak.items():
            if peak_hash not in self.peak_to_peer:
                # log.info(f"get_heaviest_peak filter {peak_hash} not in self.peak_to_peer {self.peak_to_peer}")
                continue
            if peer_id in current_peers:
                if heaviest_peak_hash is None or weight > heaviest_peak_weight:
                    heaviest_peak_hash = peak_hash
                    heaviest_peak_weight = weight
                    heaviest_peak_height = sub_height
        assert heaviest_peak_hash is not None and heaviest_peak_weight is not None and heaviest_peak_height is not None
        return heaviest_peak_hash, heaviest_peak_height, heaviest_peak_weight

    async def clear_sync_info(self):
        self.peak_to_peer = {}
