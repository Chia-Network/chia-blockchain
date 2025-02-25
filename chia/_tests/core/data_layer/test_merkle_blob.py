from __future__ import annotations

import hashlib
import itertools
from dataclasses import dataclass
from random import Random
from typing import Generic, TypeVar, Union, final

import chia_rs.datalayer
import pytest

# TODO: update after resolution in https://github.com/pytest-dev/pytest/issues/7469
from _pytest.fixtures import SubRequest
from chia_rs.datalayer import KeyId, TreeIndex, ValueId

from chia._tests.util.misc import DataCase, Marks, datacases
from chia.data_layer.data_layer_util import Side, internal_hash
from chia.data_layer.util.merkle_blob import (
    KeyOrValueId,
    MerkleBlob,
    NodeMetadata,
    NodeType,
    RawInternalMerkleNode,
    RawLeafMerkleNode,
    RawMerkleNodeProtocol,
    data_size,
    metadata_size,
    pack_raw_node,
    raw_node_classes,
    raw_node_type_to_class,
    spacing,
    undefined_index,
    unpack_raw_node,
)
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.ints import int64

pytestmark = pytest.mark.data_layer


@dataclass
class MerkleTypes:
    # TODO: maybe del the types to avoid them being used, or not from import them, or...
    # TODO: metadata as well
    internal: type[Union[RawInternalMerkleNode, chia_rs.datalayer.InternalNode]]
    leaf: type[Union[RawLeafMerkleNode, chia_rs.datalayer.LeafNode]]
    # metadata: type[Union[NodeMetadata, chia_rs.datalayer.NodeMetadata]]
    blob: type[Union[MerkleBlob, chia_rs.datalayer.MerkleBlob]]
    block_size: int
    data_size: int
    metadata_size: int


python_merkle_types = MerkleTypes(
    internal=RawInternalMerkleNode,
    leaf=RawLeafMerkleNode,
    blob=MerkleBlob,
    block_size=spacing,
    data_size=data_size,
    metadata_size=metadata_size,
)
rust_merkle_types = MerkleTypes(
    internal=chia_rs.datalayer.InternalNode,
    leaf=chia_rs.datalayer.LeafNode,
    blob=chia_rs.datalayer.MerkleBlob,
    data_size=chia_rs.datalayer.DATA_SIZE,
    block_size=chia_rs.datalayer.BLOCK_SIZE,
    metadata_size=chia_rs.datalayer.METADATA_SIZE,
)
all_merkle_types = [python_merkle_types, rust_merkle_types]


@pytest.fixture(
    name="merkle_types",
    params=all_merkle_types,
    ids=["python", "rust"],
)
def merkle_types_fixture(request: SubRequest) -> MerkleTypes:
    return request.param  # type: ignore[no-any-return]


@pytest.fixture(
    name="raw_node_class",
    scope="session",
    params=raw_node_classes,
    ids=[cls.type.name for cls in raw_node_classes],
)
def raw_node_class_fixture(request: SubRequest) -> RawMerkleNodeProtocol:
    # https://github.com/pytest-dev/pytest/issues/8763
    return request.param  # type: ignore[no-any-return]


def test_raw_node_class_types_are_unique() -> None:
    assert len(raw_node_type_to_class) == len(raw_node_classes)


def test_metadata_size_not_changed() -> None:
    assert metadata_size == 2


def test_data_size_not_changed() -> None:
    assert data_size == 53


# TODO: check all struct types against attribute types

RawMerkleNodeT = TypeVar("RawMerkleNodeT", bound=RawMerkleNodeProtocol)


counter = itertools.count()
# hash
internal_reference_blob = bytes([next(counter) for _ in range(32)])
# optional parent
internal_reference_blob += bytes([1])
internal_reference_blob += bytes([next(counter) for _ in range(4)])
# left
internal_reference_blob += bytes([next(counter) for _ in range(4)])
# right
internal_reference_blob += bytes([next(counter) for _ in range(4)])
internal_reference_blob += bytes(0 for _ in range(data_size - len(internal_reference_blob)))
assert len(internal_reference_blob) == data_size

counter = itertools.count()
# hash
leaf_reference_blob = bytes([next(counter) for _ in range(32)])
# optional parent
leaf_reference_blob += bytes([1])
leaf_reference_blob += bytes([next(counter) for _ in range(4)])
# key
leaf_reference_blob += bytes([next(counter) for _ in range(8)])
# value
leaf_reference_blob += bytes([next(counter) for _ in range(8)])
leaf_reference_blob += bytes(0 for _ in range(data_size - len(leaf_reference_blob)))
assert len(leaf_reference_blob) == data_size


@final
@dataclass
class RawNodeFromBlobCase(Generic[RawMerkleNodeT]):
    raw: RawMerkleNodeT
    packed: bytes

    marks: Marks = ()

    @property
    def id(self) -> str:
        return self.raw.type.name


reference_raw_nodes: list[DataCase] = [
    RawNodeFromBlobCase(
        raw=RawInternalMerkleNode(
            hash=bytes32(range(32)),
            parent=TreeIndex(0x20212223),
            left=TreeIndex(0x24252627),
            right=TreeIndex(0x28292A2B),
        ),
        packed=internal_reference_blob,
    ),
    RawNodeFromBlobCase(
        raw=RawLeafMerkleNode(
            hash=bytes32(range(32)),
            parent=TreeIndex(0x20212223),
            key=KeyId(KeyOrValueId(int64(0x2425262728292A2B))),
            value=ValueId(KeyOrValueId(int64(0x2C2D2E2F30313233))),
        ),
        packed=leaf_reference_blob,
    ),
]


@datacases(*reference_raw_nodes)
def test_raw_node_from_blob(case: RawNodeFromBlobCase[RawMerkleNodeProtocol]) -> None:
    node = unpack_raw_node(
        index=TreeIndex(0),
        metadata=NodeMetadata(type=case.raw.type, dirty=False),
        data=case.packed,
    )
    assert node == case.raw


@datacases(*reference_raw_nodes)
def test_raw_node_to_blob(case: RawNodeFromBlobCase[RawMerkleNodeProtocol]) -> None:
    blob = pack_raw_node(case.raw)

    assert blob == case.packed


def test_merkle_blob_one_leaf_loads(merkle_types: MerkleTypes) -> None:
    # TODO: need to persist reference data
    leaf = merkle_types.leaf(
        hash=bytes32(range(32)),
        parent=None,
        key=KeyId(KeyOrValueId(int64(0x0405060708090A0B))),
        value=ValueId(KeyOrValueId(int64(0x0405060708090A1B))),
    )
    blob = bytearray(bytes(NodeMetadata(type=NodeType.leaf, dirty=False)) + pack_raw_node(leaf))

    merkle_blob = merkle_types.blob(blob=blob)
    assert merkle_blob.get_raw_node(TreeIndex(0)) == leaf


def test_merkle_blob_two_leafs_loads(merkle_types: MerkleTypes) -> None:
    # TODO: break this test down into some reusable data and multiple tests
    # TODO: need to persist reference data
    root = merkle_types.internal(
        hash=bytes32(range(32)),
        parent=None,
        left=TreeIndex(1),
        right=TreeIndex(2),
    )
    left_leaf = merkle_types.leaf(
        hash=bytes32(range(32)),
        parent=TreeIndex(0),
        key=KeyId(KeyOrValueId(int64(0x0405060708090A0B))),
        value=ValueId(KeyOrValueId(int64(0x0405060708090A1B))),
    )
    right_leaf = merkle_types.leaf(
        hash=bytes32(range(32)),
        parent=TreeIndex(0),
        key=KeyId(KeyOrValueId(int64(0x1415161718191A1B))),
        value=ValueId(KeyOrValueId(int64(0x1415161718191A2B))),
    )
    blob = bytearray()
    blob.extend(bytes(NodeMetadata(type=NodeType.internal, dirty=True)) + pack_raw_node(root))
    blob.extend(bytes(NodeMetadata(type=NodeType.leaf, dirty=False)) + pack_raw_node(left_leaf))
    blob.extend(bytes(NodeMetadata(type=NodeType.leaf, dirty=False)) + pack_raw_node(right_leaf))

    merkle_blob = merkle_types.blob(blob=blob)
    assert merkle_blob.get_raw_node(TreeIndex(0)) == root
    assert merkle_blob.get_raw_node(root.left) == left_leaf
    assert merkle_blob.get_raw_node(root.right) == right_leaf
    assert left_leaf.parent is not None
    assert merkle_blob.get_raw_node(left_leaf.parent) == root
    assert right_leaf.parent is not None
    assert merkle_blob.get_raw_node(right_leaf.parent) == root

    assert merkle_blob.get_lineage_with_indexes(TreeIndex(0)) == [(TreeIndex(0), root)]
    expected = [
        (TreeIndex(1), left_leaf),
        (TreeIndex(0), root),
    ]
    assert merkle_blob.get_lineage_with_indexes(root.left) == expected


def generate_kvid(seed: int) -> tuple[KeyId, ValueId]:
    kv_ids: list[KeyOrValueId] = []

    for offset in range(2):
        seed_bytes = (2 * seed + offset).to_bytes(8, byteorder="big", signed=True)
        hash_obj = hashlib.sha256(seed_bytes)
        hash_int = int64.from_bytes(hash_obj.digest()[:8])
        kv_ids.append(KeyOrValueId(hash_int))

    return KeyId(kv_ids[0]), ValueId(kv_ids[1])


def generate_hash(seed: int) -> bytes32:
    seed_bytes = seed.to_bytes(8, byteorder="big", signed=True)
    hash_obj = hashlib.sha256(seed_bytes)
    return bytes32(hash_obj.digest())


def test_insert_delete_loads_all_keys(merkle_types: MerkleTypes) -> None:
    merkle_blob = merkle_types.blob(blob=bytearray())
    num_keys = 200000
    extra_keys = 100000
    max_height = 25
    keys_values: dict[KeyId, ValueId] = {}

    random = Random()
    random.seed(100, version=2)
    expected_num_entries = 0
    current_num_entries = 0

    for seed in range(num_keys):
        [op_type] = random.choices(["insert", "delete"], [0.7, 0.3], k=1)
        if op_type == "delete" and len(keys_values) > 0:
            key = random.choice(list(keys_values.keys()))
            del keys_values[key]
            merkle_blob.delete(key)
            if current_num_entries == 1:
                current_num_entries = 0
                expected_num_entries = 0
            else:
                current_num_entries -= 2
        else:
            key, value = generate_kvid(seed)
            hash = generate_hash(seed)
            merkle_blob.insert(key, value, hash)
            key_index = merkle_blob.get_key_index(key)
            lineage = merkle_blob.get_lineage_with_indexes(key_index)
            assert len(lineage) <= max_height
            keys_values[key] = value
            if current_num_entries == 0:
                current_num_entries = 1
            else:
                current_num_entries += 2

        expected_num_entries = max(expected_num_entries, current_num_entries)
        assert len(merkle_blob.blob) // spacing == expected_num_entries

    assert merkle_blob.get_keys_values() == keys_values

    merkle_blob_2 = merkle_types.blob(blob=bytearray(merkle_blob.blob))
    for seed in range(num_keys, num_keys + extra_keys):
        key, value = generate_kvid(seed)
        hash = generate_hash(seed)
        merkle_blob_2.upsert(key, value, hash)
        key_index = merkle_blob_2.get_key_index(key)
        lineage = merkle_blob_2.get_lineage_with_indexes(key_index)
        assert len(lineage) <= max_height
        keys_values[key] = value
    assert merkle_blob_2.get_keys_values() == keys_values


def test_small_insert_deletes(merkle_types: MerkleTypes) -> None:
    merkle_blob = merkle_types.blob(blob=bytearray())
    num_repeats = 100
    max_inserts = 25
    seed = 0

    random = Random()
    random.seed(100, version=2)

    for repeats in range(num_repeats):
        for num_inserts in range(1, max_inserts):
            keys_values: dict[KeyId, ValueId] = {}
            for inserts in range(num_inserts):
                seed += 1
                key, value = generate_kvid(seed)
                hash = generate_hash(seed)
                merkle_blob.insert(key, value, hash)
                keys_values[key] = value

            delete_order = list(keys_values.keys())
            random.shuffle(delete_order)
            remaining_keys_values = set(keys_values.keys())
            for kv_id in delete_order:
                merkle_blob.delete(kv_id)
                remaining_keys_values.remove(kv_id)
                assert set(merkle_blob.get_keys_values().keys()) == remaining_keys_values
            assert not remaining_keys_values


def test_proof_of_inclusion_merkle_blob(merkle_types: MerkleTypes) -> None:
    num_repeats = 10
    seed = 0

    random = Random()
    random.seed(100, version=2)

    merkle_blob = merkle_types.blob(blob=bytearray())
    keys_values: dict[KeyId, ValueId] = {}

    for repeats in range(num_repeats):
        num_inserts = 1 + repeats * 100
        num_deletes = 1 + repeats * 10

        kv_ids: list[tuple[KeyId, ValueId]] = []
        hashes: list[bytes32] = []
        for _ in range(num_inserts):
            seed += 1
            key, value = generate_kvid(seed)
            kv_ids.append((key, value))
            hashes.append(generate_hash(seed))
            keys_values[key] = value

        merkle_blob.batch_insert(kv_ids, hashes)
        merkle_blob.calculate_lazy_hashes()

        for kv_id in keys_values.keys():
            proof_of_inclusion = merkle_blob.get_proof_of_inclusion(kv_id)
            assert proof_of_inclusion.valid()

        delete_ordering = list(keys_values.keys())
        random.shuffle(delete_ordering)
        delete_ordering = delete_ordering[:num_deletes]
        for kv_id in delete_ordering:
            merkle_blob.delete(kv_id)
            del keys_values[kv_id]

        for kv_id in delete_ordering:
            with pytest.raises(chia_rs.datalayer.UnknownKeyError):
                merkle_blob.get_proof_of_inclusion(kv_id)

        new_keys_values: dict[KeyId, ValueId] = {}
        for old_kv in keys_values.keys():
            seed += 1
            _, value = generate_kvid(seed)
            hash = generate_hash(seed)
            merkle_blob.upsert(old_kv, value, hash)
            new_keys_values[old_kv] = value
        if not merkle_blob.empty():
            merkle_blob.calculate_lazy_hashes()

        keys_values = new_keys_values
        for kv_id in keys_values:
            proof_of_inclusion = merkle_blob.get_proof_of_inclusion(kv_id)
            assert proof_of_inclusion.valid()


@pytest.mark.parametrize(argnames="index", argvalues=[TreeIndex(1), undefined_index])
def test_get_raw_node_raises_for_invalid_indexes(index: TreeIndex, merkle_types: MerkleTypes) -> None:
    merkle_blob = merkle_types.blob(blob=bytearray())
    merkle_blob.insert(
        KeyId(KeyOrValueId(int64(0x1415161718191A1B))),
        ValueId(KeyOrValueId(int64(0x1415161718191A1B))),
        bytes32(range(12, 12 + 32)),
    )

    if index is None:
        expected = (chia_rs.datalayer.BlockIndexOutOfBoundsError, TypeError)
    else:
        expected = chia_rs.datalayer.BlockIndexOutOfBoundsError

    with pytest.raises(expected):
        merkle_blob.get_raw_node(index)

    # this is a python-implementation detail test
    if isinstance(merkle_blob, MerkleBlob):
        with pytest.raises(chia_rs.datalayer.BlockIndexOutOfBoundsError):
            merkle_blob._get_metadata(index)


def test_helper_methods(merkle_types: MerkleTypes) -> None:
    merkle_blob = merkle_types.blob(blob=bytearray())
    assert merkle_blob.empty()
    assert merkle_blob.get_root_hash() is None

    key, value = generate_kvid(0)
    hash = generate_hash(0)
    merkle_blob.insert(key, value, hash)
    assert not merkle_blob.empty()
    assert merkle_blob.get_root_hash() is not None
    assert merkle_blob.get_root_hash() == merkle_blob.get_hash_at_index(TreeIndex(0))

    merkle_blob.delete(key)
    assert merkle_blob.empty()
    assert merkle_blob.get_root_hash() is None


def test_insert_with_reference_key_and_side(merkle_types: MerkleTypes) -> None:
    num_inserts = 50
    merkle_blob = merkle_types.blob(blob=bytearray())
    reference_kid = None
    side = None

    for operation in range(num_inserts):
        key, value = generate_kvid(operation)
        hash = generate_hash(operation)
        merkle_blob.insert(key, value, hash, reference_kid, side)
        if reference_kid is not None:
            assert side is not None
            index = merkle_blob.get_key_index(key)
            node = merkle_blob.get_raw_node(index)
            parent = merkle_blob.get_raw_node(node.parent)
            if side == Side.LEFT:
                assert parent.left == index
            else:
                assert parent.right == index
            assert len(merkle_blob.get_lineage_with_indexes(index)) == operation + 1
        side = Side.LEFT if operation % 2 == 0 else Side.RIGHT
        reference_kid = key


def test_double_insert_fails(merkle_types: MerkleTypes) -> None:
    merkle_blob = merkle_types.blob(blob=bytearray())
    key, value = generate_kvid(0)
    hash = generate_hash(0)
    merkle_blob.insert(key, value, hash)
    # TODO: this exception should just be more specific to avoid the case sensitivity concerns
    with pytest.raises(chia_rs.datalayer.KeyAlreadyPresentError):
        merkle_blob.insert(key, value, hash)


def test_get_nodes(merkle_types: MerkleTypes) -> None:
    merkle_blob = merkle_types.blob(blob=bytearray())
    num_inserts = 500
    keys = set()
    seen_keys = set()
    seen_indexes = set()
    for operation in range(num_inserts):
        key, value = generate_kvid(operation)
        hash = generate_hash(operation)
        merkle_blob.insert(key, value, hash)
        keys.add(key)

    merkle_blob.calculate_lazy_hashes()
    all_nodes = merkle_blob.get_nodes_with_indexes()
    for index, node in all_nodes:
        if isinstance(node, (RawInternalMerkleNode, chia_rs.datalayer.InternalNode)):
            left = merkle_blob.get_raw_node(node.left)
            right = merkle_blob.get_raw_node(node.right)
            assert left.parent == index
            assert right.parent == index
            assert bytes32(node.hash) == internal_hash(bytes32(left.hash), bytes32(right.hash))
            # assert nodes are provided in left-to-right ordering
            assert node.left not in seen_indexes
            assert node.right not in seen_indexes
        else:
            assert isinstance(node, (RawLeafMerkleNode, chia_rs.datalayer.LeafNode))
            seen_keys.add(node.key)
        seen_indexes.add(index)

    assert keys == seen_keys


def test_just_insert_a_bunch(merkle_types: MerkleTypes) -> None:
    HASH = bytes32(range(12, 12 + 32))

    import pathlib

    path = pathlib.Path("~/tmp/mbt/").expanduser()
    path.joinpath("py").mkdir(parents=True, exist_ok=True)
    path.joinpath("rs").mkdir(parents=True, exist_ok=True)

    merkle_blob = merkle_types.blob(blob=bytearray())
    import time

    total_time = 0.0
    for i in range(100000):
        start = time.monotonic()
        merkle_blob.insert(KeyId(KeyOrValueId(int64(i))), ValueId(KeyOrValueId(int64(i))), HASH)
        end = time.monotonic()
        total_time += end - start
