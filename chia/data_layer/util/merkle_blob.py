from __future__ import annotations

import struct
from dataclasses import astuple, dataclass
from enum import IntEnum
from typing import ClassVar, Dict, List, NewType, Protocol, Type, TypeVar, final

from chia.types.blockchain_format.sized_bytes import bytes32

dirty_hash = bytes32(b"\x00" * 32)

TreeIndex = NewType("TreeIndex", int)
KVId = NewType("KVId", int)

T = TypeVar("T")

# TODO: i think that in the objects i would prefer Optional...
# TODO: this is a bit disconnected and finicky etc since i'm not using our fixed
#       width integers (yet)
null_parent = TreeIndex(2 ** (4 * 8) - 1)


class InvalidIndexError(Exception):
    def __init__(self, index: TreeIndex) -> None:
        super().__init__(f"Invalid index: {index}")


class NodeType(IntEnum):
    # TODO: maybe use existing?
    internal = 0
    leaf = 1

    # free?


@final
@dataclass(frozen=False)
class MerkleBlob:
    blob: bytearray

    def get_raw_node(self, index: TreeIndex) -> RawMerkleNodeProtocol:
        if index < 0 or null_parent <= index:
            raise InvalidIndexError(index=index)

        metadata_start = index * spacing
        data_start = metadata_start + metadata_size
        end = data_start + data_size

        if end > len(self.blob):
            raise InvalidIndexError(index=index)

        metadata = NodeMetadata.unpack(self.blob[metadata_start:data_start])
        return unpack_raw_node(
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

    def pack(self) -> bytes:
        return self.struct.pack(*astuple(self))

    @classmethod
    def unpack(cls, blob: bytes) -> NodeMetadata:
        return cls(*cls.struct.unpack(blob))


# TODO: allow broader bytes'ish types
def unpack_raw_node(metadata: NodeMetadata, data: bytes) -> RawMerkleNodeProtocol:
    cls = raw_node_type_to_class[metadata.type]
    return cls(*cls.struct.unpack(data))


# TODO: allow broader bytes'ish types
def pack_raw_node(raw_node: RawMerkleNodeProtocol) -> bytes:
    # TODO: try again to indicate that the RawMerkleNodeProtocol requires the dataclass interface
    return raw_node.struct.pack(*astuple(raw_node))  # type: ignore[call-overload]


@final
@dataclass(frozen=True)
class RawInternalMerkleNode:
    type: ClassVar[NodeType] = NodeType.internal
    # TODO: make a check for this?
    # must match attribute type and order such that cls(*struct.unpack(cls.format, blob) works
    struct: ClassVar[struct.Struct] = struct.Struct(">III32s")

    parent: TreeIndex
    left: TreeIndex
    right: TreeIndex
    # TODO: maybe bytes32?  maybe that's not 'raw'
    # TODO: how much slower to just not store the hashes at all?
    hash: bytes


@final
@dataclass(frozen=True)
class RawLeafMerkleNode:
    type: ClassVar[NodeType] = NodeType.leaf
    # TODO: make a check for this?
    # must match attribute type and order such that cls(*struct.unpack(cls.format, blob) works
    struct: ClassVar[struct.Struct] = struct.Struct(">IQ32s")

    parent: TreeIndex
    # TODO: how/where are these mapping?  maybe a kv table row id?
    key_value: KVId
    # TODO: maybe bytes32?  maybe that's not 'raw'
    hash: bytes


metadata_size = NodeMetadata.struct.size
data_size = RawInternalMerkleNode.struct.size
spacing = metadata_size + data_size


raw_node_classes: List[Type[RawMerkleNodeProtocol]] = [
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
