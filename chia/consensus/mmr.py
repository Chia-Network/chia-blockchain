from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import List, Optional, Tuple

from chia_rs import MerkleSet
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint64

from chia.types.blockchain_format.classgroup import ClassgroupElement
from chia.types.blockchain_format.vdf import VDFInfo
from chia.util.hash import std_hash
from chia.util.streamable import Streamable, streamable

log = logging.getLogger(__name__)


@streamable
@dataclass(frozen=True)
class VDFProofMmr(Streamable):
    """
    Represents a VDFInfo and ClassgroupElement pair in an MMR
    """

    vdf_info: VDFInfo
    classgroup_element: ClassgroupElement

    def get_hash(self) -> bytes32:
        """
        Combines the VDFInfo and ClassgroupElement into a single hash for the MMR
        """
        # Serialize VDFInfo components
        challenge_bytes = bytes(self.vdf_info.challenge)  # 32 bytes
        iters_bytes = self.vdf_info.number_of_iterations.to_bytes(8, "big", signed=False)  # 8 bytes
        output_bytes = bytes(self.vdf_info.output.data)  # 100 bytes

        # Serialize ClassgroupElement
        element_bytes = bytes(self.classgroup_element.data)  # 100 bytes

        # Combine all components and hash them
        combined = challenge_bytes + iters_bytes + output_bytes + element_bytes
        return std_hash(combined)


@streamable
@dataclass(frozen=True)
class MMRPeak(Streamable):
    """
    Represents a peak in the Merkle Mountain Range.
    Note: merkle_set is not stored as part of the streamable data,
    it is reconstructed from elements when needed.
    """

    height: uint64  # Height of this peak in the mountain range
    elements: List[bytes32]  # Elements stored in this peak
    root: bytes32  # Cached root hash of this peak

    @classmethod
    def create(cls, height: int, elements: List[bytes32]) -> MMRPeak:
        """Create a new MMRPeak with the given height and elements"""
        if height < 0:
            raise ValueError("Height cannot be negative")
        if not elements:
            raise ValueError("Elements list cannot be empty")

        merkle_set = MerkleSet(elements)
        root = merkle_set.get_root()

        return cls(uint64(height), elements, root)

    def get_merkle_set(self) -> MerkleSet:
        """Get a MerkleSet for this peak's elements"""
        return MerkleSet(self.elements)

    def get_proof(self, leaf: bytes32) -> Tuple[bool, bytes]:
        """Get inclusion proof for a leaf"""
        merkle_set = self.get_merkle_set()
        return merkle_set.is_included_already_hashed(leaf)

    def get_num_leaves(self) -> int:
        """Get number of leaves in this peak"""
        return len(self.elements)


@streamable
@dataclass(frozen=True)
class MerkleMountainRange(Streamable):
    peaks: List[MMRPeak]
    size: uint64  # Number of leaves

    @classmethod
    def create(cls) -> MerkleMountainRange:
        return cls([], uint64(0))

    def append(self, leaf: bytes32) -> None:
        if not isinstance(leaf, bytes32):
            raise ValueError("Leaf must be bytes32")

        peaks = list(self.peaks)
        carry: MMRPeak = MMRPeak.create(uint64(0), [leaf])
        peaks.append(carry)

        # Repeatedly merge from right to left as long as there are adjacent peaks of the same height
        while len(peaks) >= 2 and peaks[-1].height == peaks[-2].height:
            merged_elements = peaks[-2].elements + peaks[-1].elements
            merged_peak = MMRPeak.create(uint64(peaks[-1].height + 1), merged_elements)
            peaks = peaks[:-2] + [merged_peak]

        object.__setattr__(self, "peaks", peaks)
        object.__setattr__(self, "size", self.size + 1)
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
        """Verify inclusion proof for a leaf"""
        if peak_index < 0 or peak_index >= len(self.peaks):
            raise ValueError("Invalid peak index")

        # Verify the proof in the specified peak
        peak = self.peaks[peak_index]
        merkle_set = peak.get_merkle_set()
        included, actual_proof = merkle_set.is_included_already_hashed(leaf)
        if not included or actual_proof != proof:
            return False

        # Verify other peak roots match
        expected_other_roots = [p.root for i, p in enumerate(self.peaks) if i != peak_index]
        if other_peak_roots != expected_other_roots:
            return False

        return True

    def verify_batch_inclusion(self, leaves: List[bytes32], proofs: List[Tuple[int, bytes, List[bytes32]]]) -> bool:
        """
        Verify multiple inclusion proofs efficiently
        Returns True if all leaves are verified, False otherwise
        """
        if len(leaves) != len(proofs):
            raise ValueError("Number of leaves must match number of proofs")

        for leaf, (peak_index, proof_bytes, other_peaks) in zip(leaves, proofs):
            if not self.verify_inclusion(leaf, peak_index, proof_bytes, other_peaks):
                return False

        return True

    def get_height(self) -> int:
        """Returns the height of the tallest peak in the MMR"""
        if not self.peaks:
            return 0
        # Find the maximum height among all peaks
        return max(peak.height for peak in self.peaks)

    def __bytes__(self) -> bytes:
        """Serialize the MMR to bytes for streamable support"""
        # Format: [size (8 bytes)][num_peaks (4 bytes)][peak_data...]
        # For each peak: [height (4 bytes)][num_elements (4 bytes)][elements...]
        result = self.size.to_bytes(8, "big")
        result += len(self.peaks).to_bytes(4, "big")

        for peak in self.peaks:
            result += peak.height.to_bytes(4, "big")
            result += len(peak.elements).to_bytes(4, "big")
            for element in peak.elements:
                result += bytes(element)

        return result

    @classmethod
    def from_bytes(cls, data: bytes) -> MerkleMountainRange:
        """Deserialize the MMR from bytes for streamable support"""
        if len(data) < 12:  # Minimum size: size(8) + num_peaks(4)
            raise ValueError("Data too short")

        size = uint64(int.from_bytes(data[0:8], "big"))
        num_peaks = int.from_bytes(data[8:12], "big")

        pos = 12
        peaks = []
        for _ in range(num_peaks):
            if pos + 8 > len(data):
                raise ValueError("Data too short")

            height = int.from_bytes(data[pos : pos + 4], "big")
            num_elements = int.from_bytes(data[pos + 4 : pos + 8], "big")
            pos += 8

            if pos + 32 * num_elements > len(data):
                raise ValueError("Data too short")

            elements = []
            for _ in range(num_elements):
                elements.append(bytes32(data[pos : pos + 32]))
                pos += 32

            peaks.append(MMRPeak.create(height, elements))

        return cls(peaks, size)

    def copy(self) -> MerkleMountainRange:
        # Copy peaks (preserve height and root, duplicate elements list)
        new_peaks = [MMRPeak(peak.height, list(peak.elements), peak.root) for peak in self.peaks]
        # Return a new MerkleMountainRange with copied peaks and same size
        return MerkleMountainRange(new_peaks, uint64(self.size))
