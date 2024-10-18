from __future__ import annotations

import struct
from dataclasses import dataclass, field
from enum import IntEnum
from typing import (
    TYPE_CHECKING,
    ClassVar,
    Dict,
    List,
    NewType,
    Optional,
    Protocol,
    Set,
    Tuple,
    Type,
    TypeVar,
    cast,
    final,
)

from chia.data_layer.data_layer_util import InternalNode, ProofOfInclusion, ProofOfInclusionLayer, Side, internal_hash
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
    key_to_index: Dict[KVId, TreeIndex] = field(default_factory=dict)
    free_indexes: List[TreeIndex] = field(default_factory=list)
    last_allocated_index: TreeIndex = TreeIndex(0)

    def __post_init__(self) -> None:
        self.key_to_index = self.get_keys_indexes()
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

        block = self.blob[metadata_start:end]
        metadata = NodeMetadata.unpack(block[:metadata_size])
        node = unpack_raw_node(
            metadata=metadata,
            data=block[-int(data_size) :],
            index=index,
        )
        return node

    def empty(self) -> bool:
        return len(self.blob) == 0

    def get_root_hash(self) -> Optional[bytes32]:
        if len(self.blob) == 0:
            return None

        node = self.get_raw_node(index=TreeIndex(0))
        return bytes32(node.hash)

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
        if kvID not in self.key_to_index:
            raise Exception(f"Key {kvID} not present in the store")

        index = self.key_to_index[kvID]
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

    def get_lineage_by_key_id(self, kid: KVId) -> List[InternalNode]:
        index = self.key_to_index[kid]
        lineage = self.get_lineage(index)
        internal_nodes: List[InternalNode] = []
        for node in lineage[1:]:
            assert isinstance(node, RawInternalMerkleNode)
            left_node = self.get_raw_node(node.left)
            right_node = self.get_raw_node(node.right)
            internal_nodes.append(InternalNode(bytes32(node.hash), bytes32(left_node.hash), bytes32(right_node.hash)))

        return internal_nodes

    def update_entry(
        self,
        index: TreeIndex,
        parent: Optional[TreeIndex] = None,
        left: Optional[TreeIndex] = None,
        right: Optional[TreeIndex] = None,
        hash: Optional[bytes] = None,
        key: Optional[KVId] = None,
        value: Optional[KVId] = None,
    ) -> None:
        node = self.get_raw_node(index)
        new_parent = parent if parent is not None else node.parent
        new_hash = hash if hash is not None else node.hash
        if isinstance(node, RawInternalMerkleNode):
            new_left = left if left is not None else node.left
            new_right = right if right is not None else node.right
            new_node: RawMerkleNodeProtocol = RawInternalMerkleNode(
                new_hash, new_parent, new_left, new_right, node.index
            )
        else:
            assert isinstance(node, RawLeafMerkleNode)
            new_key = key if key is not None else node.key
            new_value = value if value is not None else node.value
            new_node = RawLeafMerkleNode(new_hash, new_parent, new_key, new_value, node.index)
            if new_key != node.key:
                del self.key_to_index[node.key]
                self.key_to_index[new_key] = index

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

    def get_keys_indexes(self) -> Dict[KVId, TreeIndex]:
        if len(self.blob) == 0:
            return {}

        key_to_index: Dict[KVId, TreeIndex] = {}
        queue: List[TreeIndex] = [TreeIndex(0)]
        while len(queue) > 0:
            node_index = queue.pop()
            node = self.get_raw_node(node_index)
            if isinstance(node, RawLeafMerkleNode):
                key_to_index[node.key] = node_index
            else:
                assert isinstance(node, RawInternalMerkleNode)
                queue.append(node.left)
                queue.append(node.right)

        return key_to_index

    def get_hashes_indexes(self) -> Dict[bytes32, TreeIndex]:
        if len(self.blob) == 0:
            return {}

        hash_to_index: Dict[bytes32, TreeIndex] = {}
        queue: List[TreeIndex] = [TreeIndex(0)]
        while len(queue) > 0:
            node_index = queue.pop()
            node = self.get_raw_node(node_index)
            hash_to_index[bytes32(node.hash)] = node_index
            if isinstance(node, RawInternalMerkleNode):
                queue.append(node.left)
                queue.append(node.right)

        return hash_to_index

    def get_keys_values(self) -> Dict[KVId, KVId]:
        if len(self.blob) == 0:
            return {}

        keys_values: Dict[KVId, KVId] = {}
        queue: List[TreeIndex] = [TreeIndex(0)]
        while len(queue) > 0:
            node_index = queue.pop()
            node = self.get_raw_node(node_index)
            if isinstance(node, RawLeafMerkleNode):
                keys_values[node.key] = node.value
            else:
                assert isinstance(node, RawInternalMerkleNode)
                queue.append(node.left)
                queue.append(node.right)

        return keys_values

    def get_free_indexes(self) -> List[TreeIndex]:
        if len(self.blob) == 0:
            return []

        free_indexes: Set[TreeIndex] = {TreeIndex(i) for i in range(int(self.last_allocated_index))}
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

    def insert_from_leaf(self, old_leaf_index: TreeIndex, new_index: TreeIndex, side: Side = Side.LEFT) -> None:
        new_internal_node_index = self.get_new_index()
        old_leaf = self.get_raw_node(old_leaf_index)
        new_node = self.get_raw_node(new_index)
        if side == Side.LEFT:
            internal_node_hash = internal_hash(bytes32(new_node.hash), bytes32(old_leaf.hash))
            left_index = new_index
            right_index = old_leaf.index
        else:
            internal_node_hash = internal_hash(bytes32(old_leaf.hash), bytes32(new_node.hash))
            left_index = old_leaf.index
            right_index = new_index

        self.insert_entry_to_blob(
            new_internal_node_index,
            NodeMetadata(type=NodeType.internal, dirty=False).pack()
            + pack_raw_node(
                RawInternalMerkleNode(
                    internal_node_hash,
                    old_leaf.parent,
                    left_index,
                    right_index,
                    new_internal_node_index,
                )
            ),
        )
        self.update_entry(new_index, parent=new_internal_node_index)

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
        if isinstance(new_node, RawLeafMerkleNode):
            self.key_to_index[new_node.key] = new_index

    def insert(
        self,
        key: KVId,
        value: KVId,
        hash: bytes,
        reference_kid: Optional[KVId] = None,
        side: Optional[Side] = None,
    ) -> None:
        if key in self.key_to_index:
            raise Exception("Key already present")
        if len(self.blob) == 0:
            self.blob.extend(
                NodeMetadata(type=NodeType.leaf, dirty=False).pack()
                + pack_raw_node(RawLeafMerkleNode(hash, null_parent, key, value, TreeIndex(0)))
            )
            self.key_to_index[key] = TreeIndex(0)
            self.free_indexes = []
            self.last_allocated_index = TreeIndex(1)
            return

        seed = std_hash(key.to_bytes(8, byteorder="big"))
        if reference_kid is None:
            old_leaf: RawMerkleNodeProtocol = self.get_random_leaf_node(bytes(seed))
        else:
            leaf_index = self.key_to_index[reference_kid]
            old_leaf = self.get_raw_node(leaf_index)
        assert isinstance(old_leaf, RawLeafMerkleNode)
        if side is None:
            side = Side.LEFT if seed[0] < 128 else Side.RIGHT

        if len(self.key_to_index) == 1:
            self.blob.clear()
            internal_node_hash = internal_hash(bytes32(old_leaf.hash), bytes32(hash))
            self.blob.extend(
                NodeMetadata(type=NodeType.internal, dirty=False).pack()
                + pack_raw_node(
                    RawInternalMerkleNode(
                        internal_node_hash,
                        null_parent,
                        TreeIndex(1),
                        TreeIndex(2),
                        TreeIndex(0),
                    )
                )
            )
            leaf_1 = RawLeafMerkleNode(old_leaf.hash, TreeIndex(0), old_leaf.key, old_leaf.value, TreeIndex(1))
            leaf_2 = RawLeafMerkleNode(hash, TreeIndex(0), key, value, TreeIndex(2))
            if side == Side.LEFT:
                leaf_1, leaf_2 = leaf_2, leaf_1
            for index, leaf in enumerate([leaf_1, leaf_2], start=1):
                self.blob.extend(NodeMetadata(type=NodeType.leaf, dirty=False).pack() + pack_raw_node(leaf))
                self.key_to_index[leaf.key] = TreeIndex(index)
            self.free_indexes = []
            self.last_allocated_index = TreeIndex(3)
            return

        new_leaf_index = self.get_new_index()
        self.insert_entry_to_blob(
            new_leaf_index,
            NodeMetadata(type=NodeType.leaf, dirty=False).pack()
            + pack_raw_node(RawLeafMerkleNode(hash, undefined_index, key, value, new_leaf_index)),
        )
        self.insert_from_leaf(old_leaf.index, new_leaf_index, side)

    def delete(self, key: KVId) -> None:
        leaf_index = self.key_to_index[key]
        leaf = self.get_raw_node(leaf_index)
        assert isinstance(leaf, RawLeafMerkleNode)
        del self.key_to_index[key]

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
            metadata = self.get_metadata(sibling_index)
            if isinstance(sibling, RawLeafMerkleNode):
                node_type = NodeType.leaf
            else:
                assert isinstance(sibling, RawInternalMerkleNode)
                node_type = NodeType.internal
            self.blob[:spacing] = NodeMetadata(type=node_type, dirty=metadata.dirty).pack() + pack_raw_node(sibling)
            self.update_entry(TreeIndex(0), parent=null_parent)
            if isinstance(sibling, RawLeafMerkleNode):
                self.key_to_index[sibling.key] = TreeIndex(0)
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

    def upsert(self, key: KVId, value: KVId, hash: bytes) -> None:
        if key not in self.key_to_index:
            self.insert(key, value, hash)
            return

        leaf_index = self.key_to_index[key]
        self.update_entry(index=leaf_index, hash=hash, value=value)
        node = self.get_raw_node(leaf_index)
        if node.parent != null_parent:
            self.mark_lineage_as_dirty(node.parent)

    def get_min_height_leaf(self) -> RawLeafMerkleNode:
        queue: List[TreeIndex] = [TreeIndex(0)]
        while len(queue) > 0:
            node_index = queue.pop()
            node = self.get_raw_node(node_index)
            if isinstance(node, RawLeafMerkleNode):
                return node
            else:
                assert isinstance(node, RawInternalMerkleNode)
                queue.append(node.left)
                queue.append(node.right)

        raise Exception("Cannot find a leaf in the tree")

    def get_hash_at_index(self, index: TreeIndex) -> bytes32:
        node = self.get_raw_node(index)
        return bytes32(node.hash)

    def get_nodes(self, index: TreeIndex = TreeIndex(0)) -> List[RawMerkleNodeProtocol]:
        node = self.get_raw_node(index)
        if isinstance(node, RawLeafMerkleNode):
            return [node]

        assert isinstance(node, RawInternalMerkleNode)

        left_nodes = self.get_nodes(node.left)
        right_nodes = self.get_nodes(node.right)

        return [node] + left_nodes + right_nodes

    def batch_insert(self, keys_values: List[Tuple[KVId, KVId]], hashes: List[bytes]) -> None:
        indexes: List[TreeIndex] = []

        if len(self.key_to_index) <= 1:
            for _ in range(2):
                if len(keys_values) == 0:
                    return
                key, value = keys_values.pop()
                hash = hashes.pop()
                self.insert(key, value, hash)

        for (key, value), hash in zip(keys_values, hashes):
            new_leaf_index = self.get_new_index()
            self.insert_entry_to_blob(
                new_leaf_index,
                NodeMetadata(type=NodeType.leaf, dirty=False).pack()
                + pack_raw_node(RawLeafMerkleNode(hash, undefined_index, key, value, new_leaf_index)),
            )
            indexes.append(new_leaf_index)
            self.key_to_index[key] = new_leaf_index

        while len(indexes) > 1:
            new_indexes: List[TreeIndex] = []
            for i in range(0, len(indexes) - 1, 2):
                index_1 = indexes[i]
                index_2 = indexes[i + 1]
                node_1 = self.get_raw_node(index_1)
                node_2 = self.get_raw_node(index_2)
                new_internal_node_index = self.get_new_index()
                internal_node_hash = internal_hash(bytes32(node_1.hash), bytes32(node_2.hash))
                self.insert_entry_to_blob(
                    new_internal_node_index,
                    NodeMetadata(type=NodeType.internal, dirty=False).pack()
                    + pack_raw_node(
                        RawInternalMerkleNode(
                            internal_node_hash,
                            undefined_index,
                            index_1,
                            index_2,
                            new_internal_node_index,
                        )
                    ),
                )
                self.update_entry(index_1, parent=new_internal_node_index)
                self.update_entry(index_2, parent=new_internal_node_index)
                new_indexes.append(new_internal_node_index)

            if len(indexes) % 2 != 0:
                new_indexes.append(indexes[-1])
            indexes = new_indexes

        if len(indexes) == 1:
            min_height_leaf = self.get_min_height_leaf()
            self.insert_from_leaf(min_height_leaf.index, indexes[0])


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

    def as_tuple(self) -> Tuple[object, ...]: ...


@final
@dataclass(frozen=True)
class NodeMetadata:
    struct: ClassVar[struct.Struct] = struct.Struct(">B?")

    type: NodeType
    # TODO: where should this really be?
    dirty: bool

    def pack(self) -> bytes:
        return self.struct.pack(self.type, self.dirty)

    @classmethod
    def unpack(cls, blob: bytes) -> NodeMetadata:
        return cls(*cls.struct.unpack(blob))


# TODO: allow broader bytes'ish types
def unpack_raw_node(index: TreeIndex, metadata: NodeMetadata, data: bytes) -> RawMerkleNodeProtocol:
    cls = raw_node_type_to_class[metadata.type]
    return cls(*cls.struct.unpack(data), index=index)


# TODO: allow broader bytes'ish types
def pack_raw_node(raw_node: RawMerkleNodeProtocol) -> bytes:
    return raw_node.struct.pack(*raw_node.as_tuple())


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
    struct: ClassVar[struct.Struct] = struct.Struct(">32sIII8x")

    hash: bytes
    parent: TreeIndex
    left: TreeIndex
    right: TreeIndex

    # TODO: maybe bytes32?  maybe that's not 'raw'
    # TODO: how much slower to just not store the hashes at all?
    # TODO: this feels like a bit of a violation being aware of your location
    index: TreeIndex

    def as_tuple(self) -> Tuple[bytes, TreeIndex, TreeIndex, TreeIndex]:
        return (self.hash, self.parent, self.left, self.right)

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
    struct: ClassVar[struct.Struct] = struct.Struct(">32sIQQ")

    hash: bytes
    parent: TreeIndex
    # TODO: how/where are these mapping?  maybe a kv table row id?
    key: KVId
    value: KVId
    # TODO: maybe bytes32?  maybe that's not 'raw'
    # TODO: this feels like a bit of a violation being aware of your location
    index: TreeIndex

    def as_tuple(self) -> Tuple[bytes, TreeIndex, KVId, KVId]:
        return (self.hash, self.parent, self.key, self.value)


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
