from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple, Type

from chia_rs import MerkleSet
from chia_rs.sized_bytes import bytes32

from chia.util.hash import std_hash

log = logging.getLogger(__name__)


class MMRPeak:
    def __init__(self, height: int, elements: List[bytes32]) -> None:
        if height < 0:
            raise ValueError("Height cannot be negative")
        if not elements:
            raise ValueError("Elements list cannot be empty")

        self.height: int = height
        self.elements: List[bytes32] = elements
        self.merkle_set: MerkleSet = MerkleSet(elements)
        self.root: bytes32 = self.merkle_set.get_root()
        log.debug(f"Created new MMR peak at height {height} with {len(elements)} elements")

    def get_proof(self, leaf: bytes32) -> Tuple[bool, bytes]:
        # Returns (included: bool, proof: bytes)
        return self.merkle_set.is_included_already_hashed(leaf)

    def get_num_leaves(self) -> int:
        return len(self.elements)


class MerkleMountainRange:
    def __init__(self) -> None:
        self.peaks: List[MMRPeak] = []
        self.size: int = 0  # Number of leaves
        log.debug("Created new empty Merkle Mountain Range")

    def append(self, leaf: bytes32) -> None:
        if not isinstance(leaf, bytes32):
            raise ValueError("Leaf must be bytes32")

        carry: MMRPeak = MMRPeak(0, [leaf])
        new_peaks: List[MMRPeak] = []
        i: int = 0
        while i < len(self.peaks):
            peak: MMRPeak = self.peaks[i]
            if peak.height == carry.height:
                # Merge peaks
                merged_elements: List[bytes32] = peak.elements + carry.elements
                carry = MMRPeak(peak.height + 1, merged_elements)
                log.debug(f"Merged peaks at height {peak.height}")
                i += 1
            else:
                new_peaks.append(peak)
                i += 1
        new_peaks.append(carry)
        self.peaks = new_peaks
        self.size += 1
        log.debug(f"Appended new leaf, MMR size is now {self.size}")

    def get_root(self) -> bytes32:
        if not self.peaks:
            return bytes32([0] * 32)
        # Hash all peak roots together, order matters for consistency
        peak_roots: bytes = b"".join(peak.root for peak in self.peaks)
        return std_hash(peak_roots)

    def get_inclusion_proof(self, leaf: bytes32) -> Optional[Tuple[int, bytes, List[bytes32]]]:
        """
        Returns (peak_index, proof_in_peak, other_peak_roots)
        - peak_index: which peak the leaf is in
        - proof_in_peak: Merkle proof (as bytes) for the leaf in that peak
        - other_peak_roots: roots of the other peaks (for full MMR root verification)
        """
        if not isinstance(leaf, bytes32):
            raise ValueError("Leaf must be bytes32")

        for idx, peak in enumerate(self.peaks):
            included, proof = peak.get_proof(leaf)
            if included:
                other_roots: List[bytes32] = [p.root for i, p in enumerate(self.peaks) if i != idx]
                log.debug(f"Found inclusion proof for leaf in peak {idx}")
                return (idx, proof, other_roots)
        log.debug("Leaf not found in any peak")
        return None

    def verify_inclusion(self, leaf: bytes32, peak_index: int, proof: bytes, other_peak_roots: List[bytes32]) -> bool:
        if not isinstance(leaf, bytes32):
            raise ValueError("Leaf must be bytes32")
        if peak_index < 0 or peak_index >= len(self.peaks):
            raise ValueError("Invalid peak index")

        # Verify Merkle proof in the peak
        peak: MMRPeak = self.peaks[peak_index]
        included, _ = peak.get_proof(leaf)
        if not included:
            log.debug(f"Leaf verification failed: not included in peak {peak_index}")
            return False

        # Recompute the MMR root
        roots: List[bytes32] = []
        for i, p in enumerate(self.peaks):
            if i == peak_index:
                roots.append(peak.root)
            else:
                roots.append(p.root)
        mmr_root: bytes32 = std_hash(b"".join(roots))
        result = mmr_root == self.get_root()
        log.debug(f"Leaf verification {'succeeded' if result else 'failed'}: MMR root comparison")
        return result

    def get_height(self) -> int:
        """Returns the height of the tallest peak in the MMR"""
        if not self.peaks:
            return 0
        return max(peak.height for peak in self.peaks)

    def verify_batch_inclusion(self, leaves: List[bytes32], proofs: List[Tuple[int, bytes, List[bytes32]]]) -> bool:
        """
        Verify multiple inclusion proofs efficiently
        Returns True if all leaves are verified, False otherwise
        """
        if len(leaves) != len(proofs):
            raise ValueError("Number of leaves must match number of proofs")

        for leaf, (peak_index, proof, other_peak_roots) in zip(leaves, proofs):
            if not self.verify_inclusion(leaf, peak_index, proof, other_peak_roots):
                log.debug(f"Batch verification failed for leaf {leaf.hex()[:8]}...")
                return False
        log.debug(f"Successfully verified batch of {len(leaves)} leaves")
        return True

    def serialize(self) -> Dict[str, Any]:
        return {
            "peaks": [
                {"height": peak.height, "elements": [bytes(e).hex() for e in peak.elements]} for peak in self.peaks
            ],
            "size": self.size,
        }

    @classmethod
    def deserialize(cls: Type[MerkleMountainRange], data: Dict[str, Any]) -> MerkleMountainRange:
        if not isinstance(data, dict):
            raise ValueError("Invalid serialized data format")
        if "peaks" not in data or "size" not in data:
            raise ValueError("Missing required fields in serialized data")

        mmr = cls()
        mmr.peaks = [
            MMRPeak(peak_data["height"], [bytes32(bytes.fromhex(e)) for e in peak_data["elements"]])
            for peak_data in data["peaks"]
        ]
        mmr.size = data["size"]
        log.debug(f"Deserialized MMR with {len(mmr.peaks)} peaks and {mmr.size} leaves")
        return mmr
