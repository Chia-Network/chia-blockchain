from __future__ import annotations

import logging

from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint32

from chia.util.hash import std_hash
from chia.util.streamable import Streamable

log = logging.getLogger(__name__)


# ------------------------------------------------------------------------------
# MMR position/height utilities
# ------------------------------------------------------------------------------


def get_height(flat_index: int) -> int:
    """
    Calculate the height of a node in a flat MMR array.

    Algorithm:
    1. Convert to 1-based index `x`.
    2. If `x` is a perfect peak (binary "all ones", 2^n - 1), return its height.
    3. Otherwise, subtract the node count of the left sibling subtree (2^k - 1) and repeat.
       - k is the index of the Most Significant Bit (MSB) of x.

    Returns: Height of the node (0 for leaves, 1+ for internal nodes)
    """
    x = flat_index + 1  # Work with 1-based for easier math

    while True:
        # Check if x is "all ones" (1, 3, 7, 15...) -> Peak of perfect binary tree
        if (x & (x + 1)) == 0:
            return x.bit_length() - 1

        # Not a peak, subtract left sibling mountain node count.
        # k = x.bit_length() - 1
        msb_val = 1 << (x.bit_length() - 1)

        # A perfect binary tree with this MSB has (2^k - 1) nodes
        subtree_node_count = msb_val - 1

        # Jump left past the entire left sibling subtree
        x -= subtree_node_count


def get_peak_positions(node_count: int) -> list[int]:
    """
    Identify the indices of the mountain peaks in a flat MMR array.

    An MMR consists of multiple perfect binary trees (mountains) of decreasing heights,
    arranged left to right.

    Args:
        node_count: Total number of nodes in the MMR array

    Algorithm:
    1. Start at the rightmost position (always a peak)
    2. Determine the height h of this peak using get_height()
    3. Jump backward by this mountain's node count (2^(h+1) - 1) to find the next peak
    4. Repeat until we reach the start of the array

    Returns indices [Rightmost Peak (Smallest), ..., Leftmost Peak (Tallest)]
    """
    peaks = []
    idx = node_count - 1

    while idx >= 0:
        peaks.append(idx)
        height = get_height(idx)
        # Number of nodes in this mountain = 2^(h+1) - 1
        mountain_node_count = (1 << (height + 1)) - 1
        idx -= mountain_node_count

    return peaks


# leaf_index is 0-based; formula maps leaf index to flat MMR position
def leaf_index_to_pos(leaf_index: int) -> int:
    """
    Convert a leaf index (0-based) to its position in the flat MMR.
    Formula: 2*L - popcount(L)
    """
    return 2 * leaf_index - leaf_index.bit_count()


# ------------------------------------------------------------------------------
# Class Implementation
# ------------------------------------------------------------------------------


class MerkleMountainRange(Streamable):
    """
    Flat MMR implementation.
    """

    nodes: list[bytes32]
    leaf_count: uint32  # Number of leaves in the MMR

    def __init__(
        self,
        nodes: list[bytes32] | None = None,
        leaf_count: uint32 = uint32(0),
    ) -> None:
        self.nodes = [] if nodes is None else nodes
        self.leaf_count = leaf_count

        # Validate that node count matches leaf_count
        if leaf_count > 0:
            expected_node_count = 2 * leaf_count - leaf_count.bit_count()
            if len(self.nodes) != expected_node_count:
                raise ValueError(
                    f"Invalid MMR state: {leaf_count} leaves should have {expected_node_count} nodes, "
                    f"but got {len(self.nodes)} nodes"
                )

    def append(self, leaf: bytes32) -> None:
        nodes = self.nodes
        curr_index = len(nodes)
        nodes.append(leaf)

        curr_height = 0

        # Merge upwards
        while True:
            # Node count of subtree at current height: 2^(h+1) - 1
            subtree_node_count = (1 << (curr_height + 1)) - 1

            # Potential left sibling is 'subtree_node_count' back
            left_sibling_index = curr_index - subtree_node_count

            if left_sibling_index < 0:
                break

            # If left node has same height, merge
            if get_height(left_sibling_index) == curr_height:
                left_hash = nodes[left_sibling_index]
                right_hash = nodes[curr_index]

                parent_hash = std_hash(left_hash + right_hash)

                # Append parent
                nodes.append(parent_hash)

                # Move focus to the new parent
                curr_index = len(nodes) - 1
                curr_height += 1
            else:
                # Different heights means we started a new mountain - stop merging
                break

        self.leaf_count = uint32(self.leaf_count + 1)
        log.debug(f"Appended new leaf, MMR leaf_count is now {self.leaf_count}, total nodes: {len(self.nodes)}")

    def pop(self) -> None:
        """
        Remove the last leaf and all parent nodes created by it.
        """
        if self.leaf_count == 0:
            raise ValueError("Cannot pop from empty MMR")

        leaf_index = self.leaf_count - 1

        # In an MMR, each set bit represents a peak. When appending a leaf, peaks of equal
        # height are merged. This works like binary addition: each trailing '1' is unset
        # and produces a merge, so the number of merges equals the trailing 1 count.
        trailing_ones = (leaf_index ^ (leaf_index + 1)).bit_count() - 1
        nodes_to_remove = 1 + trailing_ones

        del self.nodes[-nodes_to_remove:]

        self.leaf_count = uint32(self.leaf_count - 1)
        log.debug(f"removed leaf, leaf_count is now {self.leaf_count} with {len(self.nodes)} nodes ")

    def compute_root(self) -> bytes32 | None:
        """Get the MMR root by bagging the peaks."""
        peak_indices = get_peak_positions(len(self.nodes))
        if not peak_indices:
            return None

        # Bagging Order: Rightmost (Smallest) -> Leftmost (Tallest)
        current_hash = self.nodes[peak_indices[0]]

        for i in range(1, len(peak_indices)):
            left_peak = self.nodes[peak_indices[i]]
            current_hash = std_hash(left_peak + current_hash)

        return current_hash

    def get_tree_height(self) -> int:
        if self.leaf_count == 0:
            return 0
        peak_indices = get_peak_positions(len(self.nodes))
        if not peak_indices:
            return 0
        return get_height(peak_indices[-1])

    def copy(self) -> MerkleMountainRange:
        return MerkleMountainRange(list(self.nodes), uint32(self.leaf_count))

    def get_inclusion_proof_by_index(self, leaf_index: int) -> tuple[uint32, bytes, list[bytes32], bytes32] | None:
        """
        Generate inclusion proof for the N-th leaf.
        """
        if leaf_index >= self.leaf_count:
            return None

        # 1. Find start position
        flat_idx = leaf_index_to_pos(leaf_index)
        if flat_idx >= len(self.nodes):
            return None

        proof_path = []
        flags_bits = []

        # 2. Climb the mountain
        curr = flat_idx
        while True:
            h = get_height(curr)

            # The offset to a sibling at this height is 2^(h+1) - 1
            sibling_offset = (1 << (h + 1)) - 1

            # Case A: We are a Left Child?
            # Then Right Sibling is at `curr + sibling_offset`
            right_sibling_idx = curr + sibling_offset

            if right_sibling_idx < len(self.nodes) and get_height(right_sibling_idx) == h:
                # Yes, we are Left. Record Right Sibling.
                sibling_hash = self.nodes[right_sibling_idx]
                proof_path.append(sibling_hash)
                flags_bits.append(1)  # 1 = Sibling is Right

                # Parent is immediately after the Right Sibling
                curr = right_sibling_idx + 1

            else:
                # Case B: We might be a Right Child
                # Then Left Sibling is at `curr - sibling_offset`
                left_sibling_idx = curr - sibling_offset

                if left_sibling_idx >= 0 and get_height(left_sibling_idx) == h:
                    # Yes, we are Right. Record Left Sibling.
                    sibling_hash = self.nodes[left_sibling_idx]
                    proof_path.append(sibling_hash)
                    flags_bits.append(0)  # 0 = Sibling is Left

                    # Parent is immediately after Us
                    curr += 1
                else:
                    # Case C: No sibling -> We are a Peak
                    break

        # 3. Collect peaks
        peak_indices = get_peak_positions(len(self.nodes))
        all_peaks = [self.nodes[i] for i in peak_indices]

        # 4. Find which peak we ended up at
        peak_index: uint32 | None = None
        for idx, peak_pos in enumerate(peak_indices):
            if peak_pos == curr:
                peak_index = uint32(idx)
                break

        if peak_index is None:
            return None

        # 5. Serialize
        flags = 0
        for i, bit in enumerate(flags_bits):
            flags |= (bit & 1) << i
        num_flag_bytes = (len(flags_bits) + 7) // 8 if flags_bits else 1
        flags_bytes = flags.to_bytes(num_flag_bytes, "little")

        proof_bytes = len(proof_path).to_bytes(2, "big") + flags_bytes + b"".join(bytes(s) for s in proof_path)

        # Exclude our peak from the list of roots
        other_peak_roots = [all_peaks[i] for i in range(len(all_peaks)) if i != peak_index]

        return (peak_index, proof_bytes, other_peak_roots, all_peaks[peak_index])


def verify_mmr_inclusion(
    mmr_root: bytes32,
    leaf: bytes32,
    peak_index: uint32,
    proof_bytes: bytes,
    other_peak_roots: list[bytes32],
    expected_peak_root: bytes32,
) -> bool:
    if len(proof_bytes) < 2:
        return False

    num_siblings = int.from_bytes(proof_bytes[0:2], "big")
    num_flag_bytes = (num_siblings + 7) // 8 if num_siblings > 0 else 1

    if len(proof_bytes) != 2 + num_flag_bytes + num_siblings * 32:
        return False

    # Extract flags
    flags_bytes = proof_bytes[2 : 2 + num_flag_bytes]
    flags_bits = []
    for byte in flags_bytes:
        for i in range(8):
            flags_bits.append((byte >> i) & 1)

    # Extract siblings
    siblings = []
    sibling_start = 2 + num_flag_bytes
    for i in range(num_siblings):
        offset = sibling_start + i * 32
        if offset + 32 > len(proof_bytes):
            return False  # Malformed proof: insufficient bytes
        siblings.append(bytes32(proof_bytes[offset : offset + 32]))

    # Reconstruct Peak
    current_hash = leaf
    for i, sibling in enumerate(siblings):
        direction = flags_bits[i]
        if direction == 0:  # Sibling is Left
            current_hash = std_hash(sibling + current_hash)
        else:  # Sibling is Right
            current_hash = std_hash(current_hash + sibling)

    if current_hash != expected_peak_root:
        return False

    # Reconstruct Root (Bagging)
    all_peak_roots = [*other_peak_roots[:peak_index], current_hash, *other_peak_roots[peak_index:]]

    if not all_peak_roots:
        return False

    current_hash = all_peak_roots[0]
    for i in range(1, len(all_peak_roots)):
        left_peak = all_peak_roots[i]
        current_hash = std_hash(left_peak + current_hash)

    return current_hash == mmr_root
