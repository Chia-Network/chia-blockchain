from __future__ import annotations

import io
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, ClassVar, NewType, Optional, Protocol, TypeVar, Union, cast, final

from chia.data_layer.data_layer_util import InternalNode, ProofOfInclusion, ProofOfInclusionLayer, Side, internal_hash
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.hash import std_hash
from chia.util.ints import int64, uint8, uint32
from chia.util.streamable import Streamable, streamable

dirty_hash = bytes32(b"\x00" * 32)

if TYPE_CHECKING:
    # for mypy
    TreeIndex = NewType("TreeIndex", uint32)
    KeyOrValueId = int64
    KeyId = NewType("KeyId", KeyOrValueId)
    ValueId = NewType("ValueId", KeyOrValueId)
else:
    # for streamable
    TreeIndex = uint32
    KeyOrValueId = int64
    KeyId = KeyOrValueId
    ValueId = KeyOrValueId


T = TypeVar("T")

undefined_index = TreeIndex(2 ** (4 * 8) - 2)


class InvalidIndexError(Exception):
    def __init__(self, index: object) -> None:
        super().__init__(f"Invalid index: {index}")


class NodeType(uint8, Enum):
    # TODO: maybe use existing?
    internal = uint8(0)
    leaf = uint8(1)

    # free?


class Unspecified: ...


unspecified = Unspecified()


@final
@dataclass(frozen=False)
class MerkleBlob:
    blob: bytearray
    key_to_index: dict[KeyId, TreeIndex] = field(default_factory=dict)
    free_indexes: list[TreeIndex] = field(default_factory=list)
    last_allocated_index: TreeIndex = TreeIndex(uint32(0))

    def __post_init__(self) -> None:
        blocks, remainder = divmod(len(self.blob), spacing)
        assert remainder == 0, f"unexpected remainder after {blocks} full blocks: {remainder}"
        self.key_to_index = self.get_keys_indexes()
        self.last_allocated_index = TreeIndex(uint32(len(self.blob) // spacing))
        self.free_indexes = self.get_free_indexes()

    @classmethod
    def from_node_list(
        cls: type[MerkleBlob],
        internal_nodes: dict[bytes32, tuple[bytes32, bytes32]],
        terminal_nodes: dict[bytes32, tuple[KeyId, ValueId]],
        root_hash: Optional[bytes32],
    ) -> MerkleBlob:
        merkle_blob = cls(blob=bytearray())

        if root_hash is None:
            if internal_nodes or terminal_nodes:
                raise Exception("Nodes must be empty when root_hash is None")
        else:
            merkle_blob.build_blob_from_node_list(internal_nodes, terminal_nodes, root_hash)

        return merkle_blob

    def build_blob_from_node_list(
        self,
        internal_nodes: dict[bytes32, tuple[bytes32, bytes32]],
        terminal_nodes: dict[bytes32, tuple[KeyId, ValueId]],
        node_hash: bytes32,
    ) -> TreeIndex:
        if node_hash not in terminal_nodes and node_hash not in internal_nodes:
            raise Exception(f"Unknown hash {node_hash.hex()}")

        index = self.get_new_index()
        if node_hash in terminal_nodes:
            kid, vid = terminal_nodes[node_hash]
            self.insert_entry_to_blob(
                index,
                NodeMetadata(type=NodeType.leaf, dirty=False).pack()
                + pack_raw_node(RawLeafMerkleNode(node_hash, None, kid, vid)),
            )
        elif node_hash in internal_nodes:
            self.insert_entry_to_blob(
                index,
                NodeMetadata(type=NodeType.internal, dirty=False).pack()
                + pack_raw_node(
                    RawInternalMerkleNode(
                        node_hash,
                        None,
                        undefined_index,
                        undefined_index,
                    )
                ),
            )
            left_hash, right_hash = internal_nodes[node_hash]
            left_index = self.build_blob_from_node_list(internal_nodes, terminal_nodes, left_hash)
            right_index = self.build_blob_from_node_list(internal_nodes, terminal_nodes, right_hash)
            for child_index in (left_index, right_index):
                self.update_entry(index=child_index, parent=index)
            self.update_entry(index=index, left=left_index, right=right_index)

        return TreeIndex(index)

    def get_new_index(self) -> TreeIndex:
        if len(self.free_indexes) == 0:
            self.last_allocated_index = TreeIndex(uint32(self.last_allocated_index + 1))
            return TreeIndex(uint32(self.last_allocated_index - 1))

        return self.free_indexes.pop()

    def get_raw_node(self, index: TreeIndex) -> RawMerkleNodeProtocol:
        if index is None or index < 0 or undefined_index <= index:
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
            data=block[-data_size:],
            index=index,
        )
        return node

    def empty(self) -> bool:
        return len(self.blob) == 0

    def get_root_hash(self) -> Optional[bytes32]:
        if len(self.blob) == 0:
            return None

        node = self.get_raw_node(index=TreeIndex(uint32(0)))
        return bytes32(node.hash)

    def _get_metadata(self, index: TreeIndex) -> NodeMetadata:
        if index is None or index < 0 or undefined_index <= index:
            raise InvalidIndexError(index=index)

        metadata_start = index * spacing
        data_start = metadata_start + metadata_size

        if data_start > len(self.blob):
            raise InvalidIndexError(index=index)

        return NodeMetadata.unpack(self.blob[metadata_start:data_start])

    def update_metadata(self, index: TreeIndex, type: Optional[NodeType] = None, dirty: Optional[bool] = None) -> None:
        metadata = self._get_metadata(index)
        new_type = type if type is not None else metadata.type
        new_dirty = dirty if dirty is not None else metadata.dirty

        metadata_start = index * spacing
        data_start = metadata_start + metadata_size
        self.blob[metadata_start:data_start] = NodeMetadata(type=new_type, dirty=new_dirty).pack()

    def mark_lineage_as_dirty(self, index: TreeIndex) -> None:
        index_: Optional[TreeIndex] = index
        del index
        while index_ is not None:
            metadata = self._get_metadata(index_)
            if metadata.dirty:
                break
            self.update_metadata(index_, dirty=True)
            node = self.get_raw_node(index=index_)
            index_ = node.parent

    def calculate_lazy_hashes(self, index: TreeIndex = TreeIndex(uint32(0))) -> bytes32:
        metadata = self._get_metadata(index)
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

    def get_proof_of_inclusion(self, key_id: KeyId) -> ProofOfInclusion:
        if key_id not in self.key_to_index:
            raise Exception(f"Key {key_id} not present in the store")

        index = self.key_to_index[key_id]
        node = self.get_raw_node(index)
        assert isinstance(node, RawLeafMerkleNode)

        parents = self.get_lineage_with_indexes(index)
        layers: list[ProofOfInclusionLayer] = []
        for next_index, parent in parents[1:]:
            assert isinstance(parent, RawInternalMerkleNode)
            sibling_index = parent.get_sibling_index(index)
            sibling = self.get_raw_node(sibling_index)
            layer = ProofOfInclusionLayer(
                other_hash_side=parent.get_sibling_side(index),
                other_hash=bytes32(sibling.hash),
                combined_hash=bytes32(parent.hash),
            )
            layers.append(layer)
            index = next_index

        return ProofOfInclusion(node_hash=bytes32(node.hash), layers=layers)

    def get_lineage_with_indexes(self, index: TreeIndex) -> list[tuple[TreeIndex, RawMerkleNodeProtocol]]:
        node = self.get_raw_node(index=index)
        lineage = [(index, node)]
        while node.parent is not None:
            index = node.parent
            node = self.get_raw_node(index)
            lineage.append((index, node))
        return lineage

    def get_lineage_by_key_id(self, key_id: KeyId) -> list[InternalNode]:
        index = self.key_to_index[key_id]
        lineage = self.get_lineage_with_indexes(index)
        internal_nodes: list[InternalNode] = []
        for _, node in lineage[1:]:
            assert isinstance(node, RawInternalMerkleNode)
            left_node = self.get_raw_node(node.left)
            right_node = self.get_raw_node(node.right)
            internal_nodes.append(InternalNode(bytes32(node.hash), bytes32(left_node.hash), bytes32(right_node.hash)))

        return internal_nodes

    def update_entry(
        self,
        index: TreeIndex,
        parent: Union[Optional[TreeIndex], Unspecified] = unspecified,
        left: Union[TreeIndex, Unspecified] = unspecified,
        right: Union[TreeIndex, Unspecified] = unspecified,
        hash: Union[bytes32, Unspecified] = unspecified,
        key: Union[KeyId, Unspecified] = unspecified,
        value: Union[ValueId, Unspecified] = unspecified,
    ) -> None:
        node = self.get_raw_node(index)
        new_parent = parent if not isinstance(parent, Unspecified) else node.parent
        new_hash = hash if not isinstance(hash, Unspecified) else node.hash
        if isinstance(node, RawInternalMerkleNode):
            new_left = left if not isinstance(left, Unspecified) else node.left
            new_right = right if not isinstance(right, Unspecified) else node.right
            new_node: RawMerkleNodeProtocol = RawInternalMerkleNode(new_hash, new_parent, new_left, new_right)
        else:
            assert isinstance(node, RawLeafMerkleNode)
            new_key = key if not isinstance(key, Unspecified) else node.key
            new_value = value if not isinstance(value, Unspecified) else node.value
            new_node = RawLeafMerkleNode(new_hash, new_parent, new_key, new_value)
            if new_key != node.key:
                del self.key_to_index[node.key]
                self.key_to_index[new_key] = index

        metadata_start = index * spacing
        data_start = metadata_start + metadata_size
        end = data_start + data_size

        self.blob[data_start:end] = pack_raw_node(new_node)

    def get_random_leaf_node(self, seed: bytes) -> RawLeafMerkleNode:
        path = "".join(reversed("".join(f"{b:08b}" for b in seed)))
        node = self.get_raw_node(TreeIndex(uint32(0)))
        for bit in path:
            if isinstance(node, RawLeafMerkleNode):
                return node
            assert isinstance(node, RawInternalMerkleNode)
            if bit == "0":
                node = self.get_raw_node(node.left)
            else:
                node = self.get_raw_node(node.right)

        raise Exception("Cannot find leaf from seed")

    def get_keys_indexes(self) -> dict[KeyId, TreeIndex]:
        if len(self.blob) == 0:
            return {}

        key_to_index: dict[KeyId, TreeIndex] = {}
        queue: list[TreeIndex] = [TreeIndex(uint32(0))]
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

    def get_hashes_indexes(self) -> dict[bytes32, TreeIndex]:
        if len(self.blob) == 0:
            return {}

        hash_to_index: dict[bytes32, TreeIndex] = {}
        queue: list[TreeIndex] = [TreeIndex(uint32(0))]
        while len(queue) > 0:
            node_index = queue.pop()
            node = self.get_raw_node(node_index)
            hash_to_index[bytes32(node.hash)] = node_index
            if isinstance(node, RawInternalMerkleNode):
                queue.append(node.left)
                queue.append(node.right)

        return hash_to_index

    def get_keys_values(self) -> dict[KeyId, ValueId]:
        if len(self.blob) == 0:
            return {}

        keys_values: dict[KeyId, ValueId] = {}
        queue: list[TreeIndex] = [TreeIndex(uint32(0))]
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

    def get_free_indexes(self) -> list[TreeIndex]:
        if len(self.blob) == 0:
            return []

        free_indexes: set[TreeIndex] = {TreeIndex(uint32(i)) for i in range(int(self.last_allocated_index))}
        queue: list[TreeIndex] = [TreeIndex(uint32(0))]
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
        extend_index = TreeIndex(uint32(len(self.blob) // spacing))
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
            right_index = old_leaf_index
        else:
            internal_node_hash = internal_hash(bytes32(old_leaf.hash), bytes32(new_node.hash))
            left_index = old_leaf_index
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
                )
            ),
        )
        self.update_entry(new_index, parent=new_internal_node_index)

        old_parent_index = old_leaf.parent
        assert old_parent_index is not None

        self.update_entry(old_leaf_index, parent=new_internal_node_index)
        old_parent = self.get_raw_node(old_parent_index)
        assert isinstance(old_parent, RawInternalMerkleNode)
        if old_leaf_index == old_parent.left:
            self.update_entry(old_parent_index, left=new_internal_node_index)
        else:
            assert old_leaf_index == old_parent.right
            self.update_entry(old_parent_index, right=new_internal_node_index)
        self.mark_lineage_as_dirty(old_parent_index)
        if isinstance(new_node, RawLeafMerkleNode):
            self.key_to_index[new_node.key] = new_index

    def key_exists(self, key: KeyId) -> bool:
        return key in self.key_to_index

    def insert(
        self,
        key: KeyId,
        value: ValueId,
        hash: bytes32,
        reference_kid: Optional[KeyId] = None,
        side: Optional[Side] = None,
    ) -> None:
        if key in self.key_to_index:
            raise Exception("Key already present")
        if len(self.blob) == 0:
            self.blob.extend(
                NodeMetadata(type=NodeType.leaf, dirty=False).pack()
                + pack_raw_node(RawLeafMerkleNode(hash, None, key, value))
            )
            self.key_to_index[key] = TreeIndex(uint32(0))
            self.free_indexes = []
            self.last_allocated_index = TreeIndex(uint32(1))
            return

        seed = std_hash(key.to_bytes(8, byteorder="big", signed=True))
        if reference_kid is None:
            old_leaf: RawMerkleNodeProtocol = self.get_random_leaf_node(bytes(seed))
        else:
            leaf_index = self.key_to_index[reference_kid]
            old_leaf = self.get_raw_node(leaf_index)
        assert isinstance(old_leaf, RawLeafMerkleNode)
        old_leaf_index = self.key_to_index[old_leaf.key]
        if side is None:
            side = Side.LEFT if seed[0] < 128 else Side.RIGHT

        if len(self.key_to_index) == 1:
            self.blob.clear()
            if side == Side.LEFT:
                internal_node_hash = internal_hash(bytes32(hash), bytes32(old_leaf.hash))
            else:
                internal_node_hash = internal_hash(bytes32(old_leaf.hash), bytes32(hash))
            self.blob.extend(
                NodeMetadata(type=NodeType.internal, dirty=False).pack()
                + pack_raw_node(
                    RawInternalMerkleNode(
                        internal_node_hash,
                        None,
                        TreeIndex(uint32(1)),
                        TreeIndex(uint32(2)),
                    )
                )
            )
            leaf_1 = RawLeafMerkleNode(old_leaf.hash, TreeIndex(uint32(0)), old_leaf.key, old_leaf.value)
            leaf_2 = RawLeafMerkleNode(hash, TreeIndex(uint32(0)), key, value)
            if side == Side.LEFT:
                leaf_1, leaf_2 = leaf_2, leaf_1
            for index, leaf in enumerate([leaf_1, leaf_2], start=1):
                self.blob.extend(NodeMetadata(type=NodeType.leaf, dirty=False).pack() + pack_raw_node(leaf))
                self.key_to_index[leaf.key] = TreeIndex(uint32(index))
            self.free_indexes = []
            self.last_allocated_index = TreeIndex(uint32(3))
            return

        new_leaf_index = self.get_new_index()
        self.insert_entry_to_blob(
            new_leaf_index,
            NodeMetadata(type=NodeType.leaf, dirty=False).pack()
            + pack_raw_node(RawLeafMerkleNode(hash, undefined_index, key, value)),
        )
        self.insert_from_leaf(old_leaf_index, new_leaf_index, side)

    def delete(self, key: KeyId) -> None:
        leaf_index = self.key_to_index[key]
        leaf = self.get_raw_node(leaf_index)
        assert isinstance(leaf, RawLeafMerkleNode)
        del self.key_to_index[key]

        parent_index = leaf.parent
        if parent_index is None:
            self.free_indexes = []
            self.last_allocated_index = TreeIndex(uint32(0))
            self.blob.clear()
            return

        self.free_indexes.append(leaf_index)
        parent = self.get_raw_node(parent_index)
        assert isinstance(parent, RawInternalMerkleNode)
        sibling_index = parent.get_sibling_index(leaf_index)

        grandparent_index = parent.parent
        if grandparent_index is None:
            sibling = self.get_raw_node(sibling_index)
            metadata = self._get_metadata(sibling_index)
            if isinstance(sibling, RawLeafMerkleNode):
                node_type = NodeType.leaf
            else:
                assert isinstance(sibling, RawInternalMerkleNode)
                node_type = NodeType.internal
            self.blob[:spacing] = NodeMetadata(type=node_type, dirty=metadata.dirty).pack() + pack_raw_node(sibling)
            self.update_entry(TreeIndex(uint32(0)), parent=None)
            if isinstance(sibling, RawLeafMerkleNode):
                self.key_to_index[sibling.key] = TreeIndex(uint32(0))
            else:
                assert isinstance(sibling, RawInternalMerkleNode)
                for son_index in (sibling.left, sibling.right):
                    self.update_entry(son_index, parent=TreeIndex(uint32(0)))
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

    def upsert(self, key: KeyId, value: ValueId, hash: bytes32) -> None:
        if key not in self.key_to_index:
            self.insert(key, value, hash)
            return

        leaf_index = self.key_to_index[key]
        self.update_entry(index=leaf_index, hash=hash, value=value)
        node = self.get_raw_node(leaf_index)
        if node.parent is not None:
            self.mark_lineage_as_dirty(node.parent)

    def get_min_height_leaf(self) -> RawLeafMerkleNode:
        queue: list[TreeIndex] = [TreeIndex(uint32(0))]
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

    def get_nodes_with_indexes(
        self, index: TreeIndex = TreeIndex(uint32(0))
    ) -> list[tuple[TreeIndex, RawMerkleNodeProtocol]]:
        node = self.get_raw_node(index)
        this = [(index, node)]
        if isinstance(node, RawLeafMerkleNode):
            return this

        assert isinstance(node, RawInternalMerkleNode)

        left_nodes = self.get_nodes_with_indexes(node.left)
        right_nodes = self.get_nodes_with_indexes(node.right)

        return this + left_nodes + right_nodes

    def batch_insert(self, keys_values: list[tuple[KeyId, ValueId]], hashes: list[bytes32]) -> None:
        indexes: list[TreeIndex] = []

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
                + pack_raw_node(RawLeafMerkleNode(hash, undefined_index, key, value)),
            )
            indexes.append(new_leaf_index)
            self.key_to_index[key] = new_leaf_index

        while len(indexes) > 1:
            new_indexes: list[TreeIndex] = []
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
            self.insert_from_leaf(self.key_to_index[min_height_leaf.key], indexes[0])


class RawMerkleNodeProtocol(Protocol):
    type: ClassVar[NodeType]

    def __init__(self, *args: object) -> None: ...

    @property
    def parent(self) -> Optional[TreeIndex]: ...

    @property
    def hash(self) -> bytes32: ...

    # TODO: didn't get this hinting figured out
    # @classmethod
    # def from_bytes(cls: type[TP], blob: bytes) -> TP: ...

    def __bytes__(self) -> bytes: ...


@final
@streamable
@dataclass(frozen=True)
class NodeMetadata(Streamable):
    type: uint8  # NodeType
    # TODO: where should this really be?
    dirty: bool

    def pack(self) -> bytes:
        return bytes(self)

    @classmethod
    def unpack(cls, blob: bytes) -> NodeMetadata:
        return cls.from_bytes(blob)


# TODO: allow broader bytes'ish types
def unpack_raw_node(index: TreeIndex, metadata: NodeMetadata, data: bytes) -> RawMerkleNodeProtocol:
    assert len(data) == data_size
    cls = raw_node_type_to_class[metadata.type]

    # avoiding the EOF assert in Streamable.from_bytes() since we have padded blocks
    f = io.BytesIO(data)
    return cls.parse(f)  # type: ignore[attr-defined, no-any-return]


# TODO: allow broader bytes'ish types
def pack_raw_node(raw_node: RawMerkleNodeProtocol) -> bytes:
    data = bytes(raw_node)
    padding = data_size - len(data)
    assert padding >= 0, f"unexpected negative padding: {padding}"
    if padding > 0:
        data += bytes(padding)

    assert len(data) == data_size
    return data


@final
@streamable
@dataclass(frozen=True)
class RawInternalMerkleNode(Streamable):
    if TYPE_CHECKING:
        _protocol_check: ClassVar[RawMerkleNodeProtocol] = cast(
            "RawInternalMerkleNode",
            None,
        )

    type: ClassVar[NodeType] = NodeType.internal

    hash: bytes32
    parent: Optional[TreeIndex]
    left: TreeIndex
    right: TreeIndex

    # TODO: maybe bytes32?  maybe that's not 'raw'
    # TODO: how much slower to just not store the hashes at all?

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
@streamable
@dataclass(frozen=True)
class RawLeafMerkleNode(Streamable):
    if TYPE_CHECKING:
        _protocol_check: ClassVar[RawMerkleNodeProtocol] = cast(
            "RawLeafMerkleNode",
            None,
        )

    type: ClassVar[NodeType] = NodeType.leaf

    hash: bytes32
    parent: Optional[TreeIndex]
    # TODO: how/where are these mapping?  maybe a kv table row id?
    key: KeyId
    value: ValueId


metadata_size = 2  # NodeMetadata.struct.size
data_size = 53  # RawInternalMerkleNode.struct.size
spacing = metadata_size + data_size


raw_node_classes: list[type[RawMerkleNodeProtocol]] = [
    RawInternalMerkleNode,
    RawLeafMerkleNode,
]
raw_node_type_to_class: dict[uint8, type[RawMerkleNodeProtocol]] = {cls.type.value: cls for cls in raw_node_classes}


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
