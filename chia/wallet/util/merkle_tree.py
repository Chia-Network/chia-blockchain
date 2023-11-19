from __future__ import annotations

import math
from enum import Enum
from typing import List, Optional, Tuple

from clvm.casts import int_to_bytes

from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.hash import std_hash

ONE = int_to_bytes(1)
TWO = int_to_bytes(2)


def hash_a_pair(left: bytes32, right: bytes32) -> bytes32:
    return std_hash(TWO + left + right)


def hash_an_atom(atom: bytes32) -> bytes32:
    return std_hash(ONE + atom)


class TreeType(Enum):
    TREE = 1
    WATERFALL = 2


class MerkleTree:
    type: TreeType
    nodes: List[bytes32]

    def __init__(self, nodes: List[bytes32], waterfall: bool = False) -> None:
        self.type = TreeType.WATERFALL if waterfall else TreeType.TREE
        self.nodes = nodes

    def split_list(self, puzzle_hashes: List[bytes32]) -> Tuple[List[bytes32], List[bytes32]]:
        if self.type == TreeType.TREE:
            mid_index = math.ceil(len(puzzle_hashes) / 2)
            first = puzzle_hashes[0:mid_index]
            rest = puzzle_hashes[mid_index : len(puzzle_hashes)]
        else:
            first = puzzle_hashes[0:-1]
            rest = puzzle_hashes[-1 : len(puzzle_hashes)]

        return first, rest

    def _root(self, puzzle_hashes: List[bytes32]) -> bytes32:
        if len(puzzle_hashes) == 1:
            return hash_an_atom(puzzle_hashes[0])
        else:
            first, rest = self.split_list(puzzle_hashes)
            return hash_a_pair(self._root(first), self._root(rest))

    def calculate_root(self) -> bytes32:
        return self._root(self.nodes)

    def _proof(
        self, puzzle_hashes: List[bytes32], searching_for: bytes32
    ) -> Tuple[Optional[int], Optional[List[bytes32]], bytes32, Optional[int]]:
        if len(puzzle_hashes) == 1:
            atom_hash = hash_an_atom(puzzle_hashes[0])
            if puzzle_hashes[0] == searching_for:
                return (0, [], atom_hash, 0)
            else:
                return (None, [], atom_hash, None)
        else:
            first, rest = self.split_list(puzzle_hashes)
            first_hash = self._proof(first, searching_for)
            rest_hash = self._proof(rest, searching_for)

            final_path = None
            final_list = None
            bit_num = None

            if first_hash[0] is not None:
                final_list = first_hash[1]
                # TODO: handle hints
                #       error: Item "None" of "Optional[List[bytes32]]" has no attribute "append"  [union-attr]
                final_list.append(rest_hash[2])  # type: ignore[union-attr]
                bit_num = first_hash[3]
                final_path = first_hash[0]
            elif rest_hash[0] is not None:
                final_list = rest_hash[1]
                # TODO: handle hints
                #       error: Item "None" of "Optional[List[bytes32]]" has no attribute "append"  [union-attr]
                final_list.append(first_hash[2])  # type: ignore[union-attr]
                bit_num = rest_hash[3]
                # TODO: handle hints
                #       error: Unsupported operand types for << ("int" and "None")  [operator]
                #       note: Right operand is of type "Optional[int]"
                final_path = rest_hash[0] | (1 << bit_num)  # type: ignore[operator]

            pair_hash = hash_a_pair(first_hash[2], rest_hash[2])

            return (final_path, final_list, pair_hash, bit_num + 1 if bit_num is not None else None)

    def generate_proof(self, leaf_reveal: bytes32) -> Tuple[Optional[int], List[Optional[List[bytes32]]]]:
        proof = self._proof(self.nodes, leaf_reveal)
        return (proof[0], [proof[1]])
