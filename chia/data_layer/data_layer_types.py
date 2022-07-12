from dataclasses import dataclass, field
from enum import IntEnum
from typing import Dict, List, Optional, Tuple, Type, Union

import aiosqlite as aiosqlite
from typing_extensions import final

from chia.data_layer.data_layer_util import internal_hash
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.byte_types import hexstr_to_bytes
from chia.util.streamable import Streamable, streamable


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

    def other(self) -> "Side":
        if self == Side.LEFT:
            return Side.RIGHT

        return Side.LEFT


class OperationType(IntEnum):
    INSERT = 0
    DELETE = 1


class CommitState(IntEnum):
    OPEN = 0
    FINALIZED = 1
    ROLLED_BACK = 2


Node = Union["TerminalNode", "InternalNode"]


def calculate_internal_hash(hash: bytes32, other_hash_side: Side, other_hash: bytes32) -> bytes32:
    if other_hash_side == Side.LEFT:
        return internal_hash(left_hash=other_hash, right_hash=hash)
    elif other_hash_side == Side.RIGHT:
        return internal_hash(left_hash=hash, right_hash=other_hash)

    raise Exception(f"Invalid side: {other_hash_side!r}")


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

    # It is unclear how to properly satisfy the generic Row normally, let alone for
    # dict-like rows.  https://github.com/python/typeshed/issues/8027
    @classmethod
    def from_row(cls, row: aiosqlite.Row) -> "TerminalNode":  # type: ignore[type-arg]
        return cls(
            hash=bytes32.fromhex(row["hash"]),
            # generation=row["generation"],
            key=bytes.fromhex(row["key"]),
            value=bytes.fromhex(row["value"]),
        )


@final
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

    @classmethod
    def from_hashes(cls, primary_hash: bytes32, other_hash_side: Side, other_hash: bytes32) -> "ProofOfInclusionLayer":
        combined_hash = calculate_internal_hash(
            hash=primary_hash,
            other_hash_side=other_hash_side,
            other_hash=other_hash,
        )

        return cls(other_hash_side=other_hash_side, other_hash=other_hash, combined_hash=combined_hash)


other_side_to_bit = {Side.LEFT: 1, Side.RIGHT: 0}


@dataclass(frozen=True)
class ProofOfInclusion:
    node_hash: bytes32
    # children before parents
    layers: List[ProofOfInclusionLayer]

    @property
    def root_hash(self) -> bytes32:
        if len(self.layers) == 0:
            return self.node_hash

        return self.layers[-1].combined_hash

    def as_program(self) -> Program:
        sibling_sides = sum(
            other_side_to_bit[layer.other_hash_side] << index for index, layer in enumerate(self.layers)
        )
        sibling_hashes = [layer.other_hash for layer in self.layers]

        # https://github.com/Chia-Network/clvm/pull/102
        # https://github.com/Chia-Network/clvm/pull/106
        return Program.to([sibling_sides, sibling_hashes])  # type: ignore[no-any-return]

    def valid(self) -> bool:
        existing_hash = self.node_hash

        for layer in self.layers:
            calculated_hash = calculate_internal_hash(
                hash=existing_hash, other_hash_side=layer.other_hash_side, other_hash=layer.other_hash
            )

            if calculated_hash != layer.combined_hash:
                return False

            existing_hash = calculated_hash

        if existing_hash != self.root_hash:
            return False

        return True


@dataclass(frozen=True)
class InternalNode:
    hash: bytes32
    # generation: int
    left_hash: bytes32
    right_hash: bytes32

    pair: Optional[Tuple[Node, Node]] = None
    atom: None = None

    # It is unclear how to properly satisfy the generic Row normally, let alone for
    # dict-like rows.  https://github.com/python/typeshed/issues/8027
    @classmethod
    def from_row(cls, row: aiosqlite.Row) -> "InternalNode":  # type: ignore[type-arg]
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

    # It is unclear how to properly satisfy the generic Row normally, let alone for
    # dict-like rows.  https://github.com/python/typeshed/issues/8027
    @classmethod
    def from_row(cls, row: aiosqlite.Row) -> "Root":  # type: ignore[type-arg]
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
        )


node_type_to_class: Dict[NodeType, Union[Type[InternalNode], Type[TerminalNode]]] = {
    NodeType.INTERNAL: InternalNode,
    NodeType.TERMINAL: TerminalNode,
}


@dataclass(frozen=True)
class Subscription:
    tree_id: bytes32
    urls: List[str]


@dataclass(frozen=True)
class DiffData:
    type: OperationType
    key: bytes
    value: bytes


@streamable
@dataclass(frozen=True)
class SerializedNode(Streamable):
    is_terminal: bool
    value1: bytes
    value2: bytes
