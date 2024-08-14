from __future__ import annotations

import struct
from dataclasses import astuple, dataclass, field
from enum import IntEnum
from typing import TYPE_CHECKING, ClassVar, Dict, List, NewType, Optional, Protocol, Set, Type, TypeVar, cast, final

from chia.data_layer.data_layer_util import ProofOfInclusion, ProofOfInclusionLayer, Side, internal_hash
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.hash import std_hash

dirty_hash = bytes32(b"\x00" * 32)

TreeIndex = NewType("TreeIndex", int)
KVId = NewType("KVId", int)

T = TypeVar("T")

# TODO: i think that in the objects i would prefer Optional...
# TODO: this is a bit disconnected and finicky etc since i'm not using our fixed
#       width integers (yet)
null_parent = TreeIndex(2 ** (4 * 8) - 1)
undefined_index = TreeIndex(2 ** (4 * 8) - 2)


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
    kv_to_index: Dict[KVId, TreeIndex] = field(default_factory=dict)
    free_indexes: List[TreeIndex] = field(default_factory=list)
    last_allocated_index: TreeIndex = TreeIndex(0)

    def __post_init__(self) -> None:
        self.kv_to_index = self.get_keys_values_indexes()
        self.last_allocated_index = TreeIndex(len(self.blob) // spacing)
        self.free_indexes = self.get_free_indexes()

    def get_new_index(self) -> TreeIndex:
        if len(self.free_indexes) == 0:
            self.last_allocated_index = TreeIndex(self.last_allocated_index + 1)
            return TreeIndex(self.last_allocated_index - 1)

        return self.free_indexes.pop()

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
            index=index,
        )

    def get_metadata(self, index: TreeIndex) -> NodeMetadata:
        if index < 0 or null_parent <= index:
            raise InvalidIndexError(index=index)

        metadata_start = index * spacing
        data_start = metadata_start + metadata_size

        if data_start > len(self.blob):
            raise InvalidIndexError(index=index)

        return NodeMetadata.unpack(self.blob[metadata_start:data_start])

    def update_metadata(self, index: TreeIndex, type: Optional[NodeType] = None, dirty: Optional[bool] = None) -> None:
        metadata = self.get_metadata(index)
        new_type = type if type is not None else metadata.type
        new_dirty = dirty if dirty is not None else metadata.dirty

        metadata_start = index * spacing
        data_start = metadata_start + metadata_size
        self.blob[metadata_start:data_start] = NodeMetadata(type=new_type, dirty=new_dirty).pack()

    def mark_lineage_as_dirty(self, index: TreeIndex) -> None:
        while index != null_parent:
            metadata = self.get_metadata(index)
            if metadata.dirty:
                break
            self.update_metadata(index, dirty=True)
            node = self.get_raw_node(index=index)
            index = node.parent

    def calculate_lazy_hashes(self, index: TreeIndex = TreeIndex(0)) -> bytes32:
        metadata = self.get_metadata(index)
        node = self.get_raw_node(index)
        if not metadata.dirty:
            return bytes32(node.hash)

        assert isinstance(node, RawInternalMerkleNode)
        left_hash = self.calculate_lazy_hashes(node.left)
        right_hash = self.calculate_lazy_hashes(node.right)
        internal_node_hash = internal_hash(left_hash, right_hash)
        self.update_entry(index, hash=internal_node_hash)
        self.update_metadata(index, dirty=False)
        return internal_node_hash

    def get_proof_of_inclusion(self, kvID: KVId) -> ProofOfInclusion:
        if kvID not in self.kv_to_index:
            raise Exception(f"Key {kvID} not present in the store")

        index = self.kv_to_index[kvID]
        node = self.get_raw_node(index)
        assert isinstance(node, RawLeafMerkleNode)

        parents = self.get_lineage(index)
        layers: List[ProofOfInclusionLayer] = []
        for parent in parents[1:]:
            assert isinstance(parent, RawInternalMerkleNode)
            sibling_index = parent.get_sibling_index(index)
            sibling = self.get_raw_node(sibling_index)
            layer = ProofOfInclusionLayer(
                other_hash_side=parent.get_sibling_side(index),
                other_hash=bytes32(sibling.hash),
                combined_hash=bytes32(parent.hash),
            )
            layers.append(layer)
            index = parent.index

        return ProofOfInclusion(node_hash=bytes32(node.hash), layers=layers)

    def get_lineage(self, index: TreeIndex) -> List[RawMerkleNodeProtocol]:
        node = self.get_raw_node(index=index)
        lineage = [node]
        while node.parent != null_parent:
            node = self.get_raw_node(node.parent)
            lineage.append(node)
        return lineage

    def update_entry(
        self,
        index: TreeIndex,
        parent: Optional[TreeIndex] = None,
        left: Optional[TreeIndex] = None,
        right: Optional[TreeIndex] = None,
        hash: Optional[bytes] = None,
        key_value: Optional[KVId] = None,
    ) -> None:
        node = self.get_raw_node(index)
        new_parent = parent if parent is not None else node.parent
        new_hash = hash if hash is not None else node.hash
        if isinstance(node, RawInternalMerkleNode):
            new_left = left if left is not None else node.left
            new_right = right if right is not None else node.right
            new_node: RawMerkleNodeProtocol = RawInternalMerkleNode(
                new_parent, new_left, new_right, new_hash, node.index
            )
        else:
            assert isinstance(node, RawLeafMerkleNode)
            new_key_value = key_value if key_value is not None else node.key_value
            new_node = RawLeafMerkleNode(new_parent, new_key_value, new_hash, node.index)
            if new_key_value != node.key_value:
                del self.kv_to_index[node.key_value]
                self.kv_to_index[new_key_value] = index

        metadata_start = index * spacing
        data_start = metadata_start + metadata_size
        end = data_start + data_size

        self.blob[data_start:end] = pack_raw_node(new_node)

    def get_random_leaf_node(self, seed: bytes) -> RawLeafMerkleNode:
        node = self.get_raw_node(TreeIndex(0))
        for byte in seed:
            for bit in range(8):
                if isinstance(node, RawLeafMerkleNode):
                    return node
                assert isinstance(node, RawInternalMerkleNode)
                if byte & (1 << bit):
                    node = self.get_raw_node(node.left)
                else:
                    node = self.get_raw_node(node.right)

        raise Exception("Cannot find leaf from seed")

    def get_keys_values_indexes(self) -> Dict[KVId, TreeIndex]:
        if len(self.blob) == 0:
            return {}

        kv_to_index: Dict[KVId, TreeIndex] = {}
        queue: List[TreeIndex] = [TreeIndex(0)]
        while len(queue) > 0:
            node_index = queue.pop()
            node = self.get_raw_node(node_index)
            if isinstance(node, RawLeafMerkleNode):
                kv_to_index[node.key_value] = node_index
            else:
                assert isinstance(node, RawInternalMerkleNode)
                queue.append(node.left)
                queue.append(node.right)

        return kv_to_index

    def get_free_indexes(self) -> List[TreeIndex]:
        if len(self.blob) == 0:
            return []

        free_indexes: Set[TreeIndex] = set(TreeIndex(i) for i in range(int(self.last_allocated_index)))
        queue: List[TreeIndex] = [TreeIndex(0)]
        while len(queue) > 0:
            node_index = queue.pop()
            node = self.get_raw_node(node_index)
            assert node_index in free_indexes
            free_indexes.remove(node_index)
            if isinstance(node, RawInternalMerkleNode):
                queue.append(node.left)
                queue.append(node.right)

        return list(free_indexes)

    def insert_entry_to_blob(self, index: TreeIndex, entry: bytes) -> None:
        extend_index = TreeIndex(len(self.blob) // spacing)
        assert index <= extend_index
        if index == extend_index:
            self.blob.extend(entry)
        else:
            start_index = index * spacing
            end_index = (index + 1) * spacing
            self.blob[start_index:end_index] = entry

    def insert(self, key_value: KVId, hash: bytes) -> None:
        if len(self.blob) == 0:
            self.blob.extend(
                NodeMetadata(type=NodeType.leaf, dirty=False).pack()
                + pack_raw_node(RawLeafMerkleNode(null_parent, key_value, hash, TreeIndex(0)))
            )
            self.kv_to_index[key_value] = TreeIndex(0)
            self.free_indexes = []
            self.last_allocated_index = TreeIndex(1)
            return

        seed = std_hash(key_value.to_bytes(8, byteorder="big"))
        old_leaf = self.get_random_leaf_node(bytes(seed))
        internal_node_hash = internal_hash(bytes32(old_leaf.hash), bytes32(hash))

        if len(self.kv_to_index) == 1:
            self.blob.clear()
            self.blob.extend(
                NodeMetadata(type=NodeType.internal, dirty=False).pack()
                + pack_raw_node(
                    RawInternalMerkleNode(
                        null_parent,
                        TreeIndex(1),
                        TreeIndex(2),
                        internal_node_hash,
                        TreeIndex(0),
                    )
                )
            )
            leaf_1 = RawLeafMerkleNode(TreeIndex(0), old_leaf.key_value, old_leaf.hash, TreeIndex(1))
            leaf_2 = RawLeafMerkleNode(TreeIndex(0), key_value, hash, TreeIndex(2))
            for index, leaf in enumerate([leaf_1, leaf_2], start=1):
                self.blob.extend(NodeMetadata(type=NodeType.leaf, dirty=False).pack() + pack_raw_node(leaf))
                self.kv_to_index[leaf.key_value] = TreeIndex(index)
            self.free_indexes = []
            self.last_allocated_index = TreeIndex(3)
            return

        new_leaf_index = self.get_new_index()
        new_internal_node_index = self.get_new_index()
        self.insert_entry_to_blob(
            new_leaf_index,
            NodeMetadata(type=NodeType.leaf, dirty=False).pack()
            + pack_raw_node(RawLeafMerkleNode(new_internal_node_index, key_value, hash, new_leaf_index)),
        )
        self.insert_entry_to_blob(
            new_internal_node_index,
            NodeMetadata(type=NodeType.internal, dirty=False).pack()
            + pack_raw_node(
                RawInternalMerkleNode(
                    old_leaf.parent,
                    old_leaf.index,
                    new_leaf_index,
                    internal_node_hash,
                    new_internal_node_index,
                )
            ),
        )

        old_parent_index = old_leaf.parent
        assert old_parent_index != null_parent

        self.update_entry(old_leaf.index, parent=new_internal_node_index)
        old_parent = self.get_raw_node(old_parent_index)
        assert isinstance(old_parent, RawInternalMerkleNode)
        if old_leaf.index == old_parent.left:
            self.update_entry(old_parent.index, left=new_internal_node_index)
        else:
            assert old_leaf.index == old_parent.right
            self.update_entry(old_parent.index, right=new_internal_node_index)
        self.mark_lineage_as_dirty(old_parent_index)
        self.kv_to_index[key_value] = new_leaf_index

    def delete(self, key_value: KVId) -> None:
        leaf_index = self.kv_to_index[key_value]
        leaf = self.get_raw_node(leaf_index)
        assert isinstance(leaf, RawLeafMerkleNode)
        del self.kv_to_index[key_value]

        parent_index = leaf.parent
        if parent_index == null_parent:
            self.free_indexes = []
            self.last_allocated_index = TreeIndex(0)
            self.blob.clear()
            return

        self.free_indexes.append(leaf_index)
        parent = self.get_raw_node(parent_index)
        assert isinstance(parent, RawInternalMerkleNode)
        sibling_index = parent.get_sibling_index(leaf_index)

        grandparent_index = parent.parent
        if grandparent_index == null_parent:
            sibling = self.get_raw_node(sibling_index)
            if isinstance(sibling, RawLeafMerkleNode):
                node_type = NodeType.leaf
            else:
                assert isinstance(sibling, RawInternalMerkleNode)
                node_type = NodeType.internal
            self.blob[:spacing] = NodeMetadata(type=node_type, dirty=False).pack() + pack_raw_node(sibling)
            self.update_entry(TreeIndex(0), parent=null_parent)
            if isinstance(sibling, RawLeafMerkleNode):
                self.kv_to_index[sibling.key_value] = TreeIndex(0)
            else:
                assert isinstance(sibling, RawInternalMerkleNode)
                for son_index in (sibling.left, sibling.right):
                    self.update_entry(son_index, parent=TreeIndex(0))
            self.free_indexes.append(sibling_index)
            return

        self.free_indexes.append(parent_index)
        grandparent = self.get_raw_node(grandparent_index)
        assert isinstance(grandparent, RawInternalMerkleNode)

        self.update_entry(sibling_index, parent=grandparent_index)
        if grandparent.left == parent_index:
            self.update_entry(grandparent_index, left=sibling_index)
        else:
            assert grandparent.right == parent_index
            self.update_entry(grandparent_index, right=sibling_index)
        self.mark_lineage_as_dirty(grandparent_index)


class RawMerkleNodeProtocol(Protocol):
    struct: ClassVar[struct.Struct]
    type: ClassVar[NodeType]

    def __init__(self, *args: object, index: TreeIndex) -> None: ...

    @property
    def index(self) -> TreeIndex: ...

    @property
    def parent(self) -> TreeIndex: ...

    @property
    def hash(self) -> bytes: ...


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
def unpack_raw_node(index: TreeIndex, metadata: NodeMetadata, data: bytes) -> RawMerkleNodeProtocol:
    cls = raw_node_type_to_class[metadata.type]
    return cls(*cls.struct.unpack(data), index=index)


# TODO: allow broader bytes'ish types
def pack_raw_node(raw_node: RawMerkleNodeProtocol) -> bytes:
    # TODO: really hacky ignoring of the index field
    # TODO: try again to indicate that the RawMerkleNodeProtocol requires the dataclass interface
    return raw_node.struct.pack(*astuple(raw_node)[:-1])  # type: ignore[call-overload]


@final
@dataclass(frozen=True)
class RawInternalMerkleNode:
    if TYPE_CHECKING:
        _protocol_check: ClassVar[RawMerkleNodeProtocol] = cast(
            "RawInternalMerkleNode",
            None,
        )

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
    # TODO: this feels like a bit of a violation being aware of your location
    index: TreeIndex

    def get_sibling_index(self, index: TreeIndex) -> TreeIndex:
        if self.left == index:
            return self.right
        assert self.right == index
        return self.left

    def get_sibling_side(self, index: TreeIndex) -> Side:
        if self.left == index:
            return Side.RIGHT
        assert self.right == index
        return Side.LEFT


@final
@dataclass(frozen=True)
class RawLeafMerkleNode:
    if TYPE_CHECKING:
        _protocol_check: ClassVar[RawMerkleNodeProtocol] = cast(
            "RawLeafMerkleNode",
            None,
        )

    type: ClassVar[NodeType] = NodeType.leaf
    # TODO: make a check for this?
    # must match attribute type and order such that cls(*struct.unpack(cls.format, blob) works
    struct: ClassVar[struct.Struct] = struct.Struct(">IQ32s")

    parent: TreeIndex
    # TODO: how/where are these mapping?  maybe a kv table row id?
    key_value: KVId
    # TODO: maybe bytes32?  maybe that's not 'raw'
    hash: bytes
    # TODO: this feels like a bit of a violation being aware of your location
    index: TreeIndex


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
