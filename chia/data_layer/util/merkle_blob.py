from __future__ import annotations

import struct
from dataclasses import dataclass
from enum import Enum
from typing import ClassVar, Dict, List, Protocol, Type, TypeVar, final

from chia.types.blockchain_format.sized_bytes import bytes32

dirty_hash = bytes32(b"\x00" * 32)


T = TypeVar("T")


class NodeType(Enum):
    root = 0
    internal = 1
    leaf = 2

    # free?


@final
@dataclass(frozen=False)
class MerkleBlob:
    blob: bytearray

    def get_raw_node(self, index: int) -> RawMerkleNodeProtocol:
        metadata_start = index * spacing
        data_start = metadata_start + metadata_size
        end = data_start + data_size
        metadata = NodeMetadata(*NodeMetadata.struct.unpack(self.blob[metadata_start:data_start]))
        return raw_node_from_blob(
            metadata=metadata,
            data=self.blob[data_start:end],
        )


class RawMerkleNodeProtocol(Protocol):
    struct: ClassVar[struct.Struct]
    type: ClassVar[NodeType]


@final
@dataclass(frozen=True)
class NodeMetadata:
    struct: ClassVar[struct.Struct] = struct.Struct(">B?")

    type: NodeType
    # TODO: where should this really be?
    dirty: bool

    @classmethod
    def unpack(cls, blob: bytes) -> NodeMetadata:
        return cls(*cls.struct.unpack(blob))


metadata_size = NodeMetadata.struct.size
data_size = 44
spacing = metadata_size + data_size


# TODO: allow broader bytes'ish types
def raw_node_from_blob(metadata: NodeMetadata, data: bytes) -> RawMerkleNodeProtocol:
    cls = raw_node_type_to_class[metadata.type]
    return cls(*cls.struct.unpack(data))


@final
@dataclass(frozen=True)
class RawRootMerkleNode:
    type: ClassVar[NodeType] = NodeType.root
    # must match attribute type and order such that cls(*struct.unpack(cls.format, blob) works
    struct: ClassVar[struct.Struct] = struct.Struct(">4xII32s")

    left: int
    right: int
    hash: bytes32


@final
@dataclass(frozen=True)
class RawInternalMerkleNode:
    type: ClassVar[NodeType] = NodeType.internal
    # TODO: make a check for this?
    # must match attribute type and order such that cls(*struct.unpack(cls.format, blob) works
    struct: ClassVar[struct.Struct] = struct.Struct(">III32s")

    parent: int
    left: int
    right: int
    hash: bytes32


@final
@dataclass(frozen=True)
class RawLeafMerkleNode:
    type: ClassVar[NodeType] = NodeType.leaf
    # TODO: make a check for this?
    # must match attribute type and order such that cls(*struct.unpack(cls.format, blob) works
    struct: ClassVar[struct.Struct] = struct.Struct(">III32s")

    parent: int
    # TODO: how/where are these mapping?
    key: int
    value: int
    hash: bytes32


raw_node_classes: List[Type[RawMerkleNodeProtocol]] = [
    RawRootMerkleNode,
    RawInternalMerkleNode,
    RawLeafMerkleNode,
]
raw_node_type_to_class: Dict[NodeType, Type[RawMerkleNodeProtocol]] = {cls.type: cls for cls in raw_node_classes}


# MerkleNode = Union["InternalMerkleNode", "LeafMerkleNode"]
#
#
# @final
# @dataclass(frozen=True)
# class InternalMerkleNode:
#     # TODO: avoid the optional, such as with a reference 'root's parent' node or...
#     parent: Optional[MerkleNode]
#     left: MerkleNode
#     right: MerkleNode
#     hash: bytes32
#
#     # def from_raw(self):
#
#
# @final
# @dataclass(frozen=True)
# class InternalMerkleNode:
#     # TODO: avoid the optional, such as with a reference 'root's parent' node or...
#     parent: MerkleNode
#     key: bytes32
#     value: bytes32
#     hash: bytes32
