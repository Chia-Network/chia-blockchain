from dataclasses import dataclass, field
from enum import IntEnum
from typing import Dict, List, Optional, Tuple, Type, Union

import aiosqlite as aiosqlite

from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.byte_types import hexstr_to_bytes
from chia.util.ints import uint16


class Status(IntEnum):
    PENDING = 1
    COMMITTED = 2


class NodeType(IntEnum):
    # EMPTY = 0
    INTERNAL = 1
    TERMINAL = 2


class Side(IntEnum):
    LEFT = 0
    RIGHT = 1


class OperationType(IntEnum):
    INSERT = 0
    DELETE = 1


class CommitState(IntEnum):
    OPEN = 0
    FINALIZED = 1
    ROLLED_BACK = 2


Node = Union["TerminalNode", "InternalNode"]


@dataclass(frozen=True)
class TerminalNode:
    hash: bytes32
    # generation: int
    key: bytes
    value: bytes

    atom: None = field(init=False, default=None)

    @property
    def pair(self) -> Tuple[bytes32, bytes32]:
        return Program.to(self.key), Program.to(self.value)

    @classmethod
    def from_row(cls, row: aiosqlite.Row) -> "TerminalNode":
        return cls(
            hash=bytes32.fromhex(row["hash"]),
            # generation=row["generation"],
            key=bytes.fromhex(row["key"]),
            value=bytes.fromhex(row["value"]),
        )


@dataclass(frozen=True)
class ProofOfInclusionLayer:
    other_hash_side: Side
    other_hash: bytes32
    combined_hash: bytes32

    @classmethod
    def from_internal_node(
        cls,
        internal_node: "InternalNode",
        traversal_child_hash: bytes32,
    ) -> "ProofOfInclusionLayer":
        return ProofOfInclusionLayer(
            other_hash_side=internal_node.other_child_side(hash=traversal_child_hash),
            other_hash=internal_node.other_child_hash(hash=traversal_child_hash),
            combined_hash=internal_node.hash,
        )


other_side_to_bit = {Side.LEFT: 1, Side.RIGHT: 0}


@dataclass(frozen=True)
class ProofOfInclusion:
    node_hash: bytes32
    root_hash: bytes32
    # children before parents
    layers: List[ProofOfInclusionLayer]

    def as_program(self) -> Program:
        sibling_sides = sum(
            other_side_to_bit[layer.other_hash_side] << index for index, layer in enumerate(self.layers)
        )
        sibling_hashes = [layer.other_hash for layer in self.layers]

        # TODO: Remove ignore when done.
        #       https://github.com/Chia-Network/clvm/pull/102
        #       https://github.com/Chia-Network/clvm/pull/106
        return Program.to([sibling_sides, sibling_hashes])  # type: ignore[no-any-return]


@dataclass(frozen=True)
class InternalNode:
    hash: bytes32
    # generation: int
    left_hash: bytes32
    right_hash: bytes32

    pair: Optional[Tuple[Node, Node]] = None
    atom: None = None

    @classmethod
    def from_row(cls, row: aiosqlite.Row) -> "InternalNode":
        return cls(
            hash=bytes32(hexstr_to_bytes(row["hash"])),
            # generation=row["generation"],
            left_hash=bytes32(hexstr_to_bytes(row["left"])),
            right_hash=bytes32(hexstr_to_bytes(row["right"])),
        )

    def other_child_hash(self, hash: bytes32) -> bytes32:
        if self.left_hash == hash:
            return self.right_hash
        elif self.right_hash == hash:
            return self.left_hash

        # TODO: real exception considerations
        raise Exception("provided hash not present")

    def other_child_side(self, hash: bytes32) -> Side:
        if self.left_hash == hash:
            return Side.RIGHT
        elif self.right_hash == hash:
            return Side.LEFT

        # TODO: real exception considerations
        raise Exception("provided hash not present")


@dataclass(frozen=True)
class Root:
    tree_id: bytes32
    node_hash: Optional[bytes32]
    generation: int
    status: Status
    submissions: int

    @classmethod
    def from_row(cls, row: aiosqlite.Row) -> "Root":
        raw_node_hash = row["node_hash"]
        if raw_node_hash is None:
            node_hash = None
        else:
            node_hash = bytes32(hexstr_to_bytes(raw_node_hash))

        return cls(
            tree_id=bytes32(hexstr_to_bytes(row["tree_id"])),
            node_hash=node_hash,
            generation=row["generation"],
            status=Status(row["status"]),
            submissions=row["submissions"],
        )


node_type_to_class: Dict[NodeType, Union[Type[InternalNode], Type[TerminalNode]]] = {
    NodeType.INTERNAL: InternalNode,
    NodeType.TERMINAL: TerminalNode,
}


@dataclass(frozen=True)
class InsertionData:
    hash: bytes32
    key: bytes
    value: bytes
    reference_node_hash: Optional[bytes32]
    side: Optional[Side]
    root_status: Status


@dataclass(frozen=True)
class DeletionData:
    hash: Optional[bytes32]
    key: bytes
    root_status: Status


class DownloadMode(IntEnum):
    LATEST = 0
    HISTORY = 1


@dataclass(frozen=True)
class Subscription:
    tree_id: bytes32
    mode: DownloadMode
    ip: str
    port: uint16


@dataclass(frozen=True)
class DiffData:
    type: OperationType
    key: bytes
    value: bytes
