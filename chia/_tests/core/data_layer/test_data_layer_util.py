from __future__ import annotations

import dataclasses
from random import Random
from typing import List, Tuple

import pytest

# TODO: update after resolution in https://github.com/pytest-dev/pytest/issues/7469
from _pytest.fixtures import SubRequest

from chia._tests.util.misc import Marks, datacases, measure_runtime
from chia.data_layer.data_layer_util import (
    ClearPendingRootsRequest,
    ClearPendingRootsResponse,
    ProofOfInclusion,
    ProofOfInclusionLayer,
    Root,
    Side,
    Status,
    internal_hash,
    key_hash,
    leaf_hash,
)
from chia.rpc.data_layer_rpc_util import MarshallableProtocol
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.serialized_program import SerializedProgram
from chia.types.blockchain_format.sized_bytes import bytes32

pytestmark = pytest.mark.data_layer


def create_valid_proof_of_inclusion(layer_count: int, other_hash_side: Side) -> ProofOfInclusion:
    node_hash = bytes32(b"a" * 32)
    layers: List[ProofOfInclusionLayer] = []

    existing_hash = node_hash

    other_hashes = [bytes32([i] * 32) for i in range(layer_count)]

    for other_hash in other_hashes:
        new_layer = ProofOfInclusionLayer.from_hashes(
            primary_hash=existing_hash,
            other_hash_side=other_hash_side,
            other_hash=other_hash,
        )

        layers.append(new_layer)
        existing_hash = new_layer.combined_hash

    return ProofOfInclusion(node_hash=node_hash, layers=layers)


@pytest.fixture(name="side", params=[Side.LEFT, Side.RIGHT])
def side_fixture(request: SubRequest) -> Side:
    # https://github.com/pytest-dev/pytest/issues/8763
    return request.param  # type: ignore[no-any-return]


@pytest.fixture(name="valid_proof_of_inclusion", params=[0, 1, 5])
def valid_proof_of_inclusion_fixture(request: SubRequest, side: Side) -> ProofOfInclusion:
    return create_valid_proof_of_inclusion(layer_count=request.param, other_hash_side=side)


@pytest.fixture(
    name="invalid_proof_of_inclusion",
    params=["bad root hash", "bad other hash", "bad other side", "bad node hash"],
)
def invalid_proof_of_inclusion_fixture(request: SubRequest, side: Side) -> ProofOfInclusion:
    valid_proof_of_inclusion = create_valid_proof_of_inclusion(layer_count=5, other_hash_side=side)

    layers = list(valid_proof_of_inclusion.layers)
    a_hash = bytes32(b"f" * 32)

    if request.param == "bad root hash":
        layers[-1] = dataclasses.replace(layers[-1], combined_hash=a_hash)
        return dataclasses.replace(valid_proof_of_inclusion, layers=layers)
    elif request.param == "bad other hash":
        layers[1] = dataclasses.replace(layers[1], other_hash=a_hash)
        return dataclasses.replace(valid_proof_of_inclusion, layers=layers)
    elif request.param == "bad other side":
        layers[1] = dataclasses.replace(layers[1], other_hash_side=layers[1].other_hash_side.other())
        return dataclasses.replace(valid_proof_of_inclusion, layers=layers)
    elif request.param == "bad node hash":
        return dataclasses.replace(valid_proof_of_inclusion, node_hash=a_hash)

    raise Exception(f"Unhandled parametrization: {request.param!r}")  # pragma: no cover


def test_proof_of_inclusion_is_valid(valid_proof_of_inclusion: ProofOfInclusion) -> None:
    assert valid_proof_of_inclusion.valid()


def test_proof_of_inclusion_is_invalid(invalid_proof_of_inclusion: ProofOfInclusion) -> None:
    assert not invalid_proof_of_inclusion.valid()


@dataclasses.dataclass()
class RoundTripCase:
    id: str
    instance: MarshallableProtocol
    marks: Marks = ()


@datacases(
    RoundTripCase(
        id="Root",
        instance=Root(
            store_id=bytes32(b"\x00" * 32),
            node_hash=bytes32(b"\x01" * 32),
            generation=3,
            status=Status.PENDING,
        ),
    ),
    RoundTripCase(
        id="ClearPendingRootsRequest",
        instance=ClearPendingRootsRequest(store_id=bytes32(b"\x12" * 32)),
    ),
    RoundTripCase(
        id="ClearPendingRootsResponse success",
        instance=ClearPendingRootsResponse(
            success=True,
            root=Root(
                store_id=bytes32(b"\x00" * 32),
                node_hash=bytes32(b"\x01" * 32),
                generation=3,
                status=Status.PENDING,
            ),
        ),
    ),
    RoundTripCase(
        id="ClearPendingRootsResponse failure",
        instance=ClearPendingRootsResponse(success=False, root=None),
    ),
)
def test_marshalling_round_trip(case: RoundTripCase) -> None:
    marshalled = case.instance.marshal()
    unmarshalled = type(case.instance).unmarshal(marshalled)
    assert case.instance == unmarshalled


def test_internal_hash(seeded_random: Random) -> None:
    def definition(left_hash: bytes32, right_hash: bytes32) -> bytes32:
        return Program.to((left_hash, right_hash)).get_tree_hash_precalc(left_hash, right_hash)

    data: List[Tuple[bytes32, bytes32, bytes32]] = []
    for _ in range(5000):
        left_hash = bytes32.random(r=seeded_random)
        right_hash = bytes32.random(r=seeded_random)
        reference = definition(left_hash=left_hash, right_hash=right_hash)
        data.append((left_hash, right_hash, reference))

    with measure_runtime(label="optimization"):
        for left_hash, right_hash, reference in data:
            assert internal_hash(left_hash=left_hash, right_hash=right_hash) == reference

    with measure_runtime(label="definition"):
        for left_hash, right_hash, reference in data:
            assert definition(left_hash=left_hash, right_hash=right_hash) == reference


def test_leaf_hash(seeded_random: Random) -> None:
    def definition(key: bytes, value: bytes) -> bytes32:
        return SerializedProgram.to((key, value)).get_tree_hash()

    data: List[Tuple[bytes, bytes, bytes32]] = []
    for cycle in range(20000):
        if cycle in (0, 1):
            length = 0
        else:
            length = seeded_random.randrange(100)
        key = seeded_random.getrandbits(length * 8).to_bytes(length, "big")
        if cycle in (1, 2):
            length = 0
        else:
            length = seeded_random.randrange(100)
        value = seeded_random.getrandbits(length * 8).to_bytes(length, "big")
        reference = definition(key=key, value=value)
        data.append((key, value, reference))

    with measure_runtime(label="optimization"):
        for key, value, reference in data:
            assert leaf_hash(key=key, value=value) == reference

    with measure_runtime(label="definition"):
        for key, value, reference in data:
            assert definition(key=key, value=value) == reference


def test_key_hash(seeded_random: Random) -> None:
    def definition(key: bytes) -> bytes32:
        return SerializedProgram.to(key).get_tree_hash()

    data: List[Tuple[bytes, bytes32]] = []
    for cycle in range(30000):
        if cycle == 0:
            length = 0
        else:
            length = seeded_random.randrange(100)
        key = seeded_random.getrandbits(length * 8).to_bytes(length, "big")
        reference = definition(key=key)
        data.append((key, reference))

    with measure_runtime(label="optimization"):
        for key, reference in data:
            assert key_hash(key=key) == reference

    with measure_runtime(label="definition"):
        for key, reference in data:
            assert definition(key=key) == reference
