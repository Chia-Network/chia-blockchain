from __future__ import annotations

import asyncio
import logging
from collections import OrderedDict as orderedDict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, OrderedDict, Set

import typing_extensions

from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.ints import uint32, uint128

log = logging.getLogger(__name__)


@dataclass
class Peak:
    header_hash: bytes32
    height: uint32
    weight: uint128


@typing_extensions.final
@dataclass
class SyncStore:
    # Whether or not we are syncing
    sync_mode: bool = False
    long_sync: bool = False
    # Header hash : peer node id
    peak_to_peer: OrderedDict[bytes32, Set[bytes32]] = field(default_factory=orderedDict)
    # peer node id : Peak
    peer_to_peak: Dict[bytes32, Peak] = field(default_factory=dict)
    # Peak we are syncing towards
    target_peak: Optional[Peak] = None
    peers_changed: asyncio.Event = field(default_factory=asyncio.Event)
    # Set of nodes which we are batch syncing from
    batch_syncing: Set[bytes32] = field(default_factory=set)
    # Set of nodes which we are backtrack syncing from, and how many threads
    backtrack_syncing: Dict[bytes32, int] = field(default_factory=dict)

    def set_sync_mode(self, sync_mode: bool) -> None:
        self.sync_mode = sync_mode

    def get_sync_mode(self) -> bool:
        return self.sync_mode

    def set_long_sync(self, long_sync: bool) -> None:
        self.long_sync = long_sync

    def get_long_sync(self) -> bool:
        return self.long_sync

    def seen_header_hash(self, header_hash: bytes32) -> bool:
        return header_hash in self.peak_to_peer

    def peer_has_block(
        self, header_hash: bytes32, peer_id: bytes32, weight: uint128, height: uint32, new_peak: bool
    ) -> None:
        """
        Adds a record that a certain peer has a block.
        """

        if self.target_peak is not None and header_hash == self.target_peak.header_hash:
            self.peers_changed.set()
        if header_hash in self.peak_to_peer:
            self.peak_to_peer[header_hash].add(peer_id)
        else:
            self.peak_to_peer[header_hash] = {peer_id}
            if len(self.peak_to_peer) > 256:  # nice power of two
                item = self.peak_to_peer.popitem(last=False)  # Remove the oldest entry
                # sync target hash is used throughout the sync process and should not be deleted.
                if self.target_peak is not None and item[0] == self.target_peak.header_hash:
                    self.peak_to_peer[item[0]] = item[1]  # Put it back in if it was the sync target
                    self.peak_to_peer.popitem(last=False)  # Remove the oldest entry again
        if new_peak:
            self.peer_to_peak[peer_id] = Peak(header_hash, height, weight)

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

    def get_peak_of_each_peer(self) -> Dict[bytes32, Peak]:
        """
        Returns: dictionary of peer id to peak information.
        """

        ret = {}
        for peer_id, peak in self.peer_to_peak.items():
            if peak.header_hash not in self.peak_to_peer:
                continue
            ret[peer_id] = peak
        return ret

    def get_heaviest_peak(self) -> Optional[Peak]:
        """
        Returns: the header_hash, height, and weight of the heaviest block that one of our peers has notified
        us of.
        """

        if len(self.peer_to_peak) == 0:
            return None
        heaviest_peak: Optional[Peak] = None
        for peak in self.peer_to_peak.values():
            if peak.header_hash not in self.peak_to_peer:
                continue
            if heaviest_peak is None or peak.weight > heaviest_peak.weight:
                heaviest_peak = peak
        assert heaviest_peak is not None
        return heaviest_peak

    async def clear_sync_info(self) -> None:
        """
        Clears the peak_to_peer info which can get quite large.
        """
        self.peak_to_peer = orderedDict()

    def peer_disconnected(self, node_id: bytes32) -> None:
        if node_id in self.peer_to_peak:
            del self.peer_to_peak[node_id]

        for peak, peers in self.peak_to_peer.items():
            if node_id in peers:
                self.peak_to_peer[peak].remove(node_id)
            assert node_id not in self.peak_to_peer[peak]
        self.peers_changed.set()
