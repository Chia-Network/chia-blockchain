from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import Dict, Generic, List, Type, TypeVar, final

import pytest

# TODO: update after resolution in https://github.com/pytest-dev/pytest/issues/7469
from _pytest.fixtures import SubRequest

from chia._tests.util.misc import DataCase, Marks, datacases
from chia.data_layer.util.merkle_blob import (
    KVId,
    NodeMetadata,
    RawInternalMerkleNode,
    RawLeafMerkleNode,
    RawMerkleNodeProtocol,
    RawRootMerkleNode,
    TreeIndex,
    data_size,
    metadata_size,
    pack_raw_node,
    raw_node_classes,
    raw_node_type_to_class,
    unpack_raw_node,
)


@pytest.fixture(
    name="raw_node_class",
    scope="session",
    params=raw_node_classes,
    ids=[cls.type.name for cls in raw_node_classes],
)
def raw_node_class_fixture(request: SubRequest) -> RawMerkleNodeProtocol:
    # https://github.com/pytest-dev/pytest/issues/8763
    return request.param  # type: ignore[no-any-return]


class_to_structs: Dict[Type[object], struct.Struct] = {
    NodeMetadata: NodeMetadata.struct,
    **{cls: cls.struct for cls in raw_node_classes},
}


@pytest.fixture(
    name="class_struct",
    scope="session",
    params=class_to_structs.values(),
    ids=[cls.__name__ for cls in class_to_structs.keys()],
)
def class_struct_fixture(request: SubRequest) -> RawMerkleNodeProtocol:
    # https://github.com/pytest-dev/pytest/issues/8763
    return request.param  # type: ignore[no-any-return]


def test_raw_node_class_types_are_unique() -> None:
    assert len(raw_node_type_to_class) == len(raw_node_classes)


def test_metadata_size_not_changed() -> None:
    assert metadata_size == 2


def test_data_size_not_changed() -> None:
    assert data_size == 44


def test_raw_node_struct_sizes(raw_node_class: RawMerkleNodeProtocol) -> None:
    assert raw_node_class.struct.size == data_size


def test_all_big_endian(class_struct: struct.Struct) -> None:
    assert class_struct.format.startswith(">")


# TODO: check all struct types against attribute types

RawMerkleNodeT = TypeVar("RawMerkleNodeT", bound=RawMerkleNodeProtocol)


reference_blob = bytes(range(data_size))


@final
@dataclass
class RawNodeFromBlobCase(Generic[RawMerkleNodeT]):
    raw: RawMerkleNodeT
    blob_to_unpack: bytes = reference_blob
    packed_blob_reference: bytes = reference_blob

    marks: Marks = ()

    @property
    def id(self) -> str:
        return self.raw.type.name


reference_raw_nodes: List[DataCase] = [
    RawNodeFromBlobCase(
        raw=RawRootMerkleNode(
            left=TreeIndex(0x04050607),
            right=TreeIndex(0x08090A0B),
            hash=bytes(range(12, data_size)),
        ),
        packed_blob_reference=b"\x00\x00\x00\x00" + reference_blob[4:],
    ),
    RawNodeFromBlobCase(
        raw=RawInternalMerkleNode(
            parent=TreeIndex(0x00010203),
            left=TreeIndex(0x04050607),
            right=TreeIndex(0x08090A0B),
            hash=bytes(range(12, data_size)),
        ),
    ),
    RawNodeFromBlobCase(
        raw=RawLeafMerkleNode(
            parent=TreeIndex(0x00010203),
            key=KVId(0x04050607),
            value=KVId(0x08090A0B),
            hash=bytes(range(12, data_size)),
        ),
    ),
]


@datacases(*reference_raw_nodes)
def test_raw_node_from_blob(case: RawNodeFromBlobCase[RawMerkleNodeProtocol]) -> None:
    node = unpack_raw_node(
        NodeMetadata(type=case.raw.type, dirty=False),
        case.blob_to_unpack,
    )
    assert node == case.raw


@datacases(*reference_raw_nodes)
def test_raw_node_to_blob(case: RawNodeFromBlobCase[RawMerkleNodeProtocol]) -> None:
    blob = pack_raw_node(case.raw)
    assert blob == case.packed_blob_reference
