import dataclasses
from typing import List

import pytest

from chia.data_layer.data_layer_types import ProofOfInclusion, ProofOfInclusionLayer, Side
from chia.types.blockchain_format.sized_bytes import bytes32

# TODO: the names and form of the fixtures/tests don't strike me as super clear...


@pytest.fixture(name="valid_proof_of_inclusion")
def valid_proof_of_inclusion_fixture() -> ProofOfInclusion:
    node_hash = bytes32(b"a" * 32)
    layers: List[ProofOfInclusionLayer] = []

    existing_hash = node_hash

    for other_hash_side, other_hash in ((Side.LEFT, bytes32(b * 32)) for b in [b"b", b"c", b"d"]):
        new_layer = ProofOfInclusionLayer.from_hashes(
            primary_hash=existing_hash,
            other_hash_side=other_hash_side,
            other_hash=other_hash,
        )

        layers.append(new_layer)
        existing_hash = new_layer.combined_hash

    return ProofOfInclusion(node_hash=node_hash, layers=layers)


@pytest.fixture(name="invalid_proof_of_inclusion_bad_root")
def invalid_proof_of_inclusion_bad_root_fixture(valid_proof_of_inclusion: ProofOfInclusion) -> ProofOfInclusion:
    layers = list(valid_proof_of_inclusion.layers)
    layers[-1] = dataclasses.replace(layers[-1], combined_hash=bytes32(b"f" * 32))
    return dataclasses.replace(valid_proof_of_inclusion, layers=layers)


@pytest.fixture(name="invalid_proof_of_inclusion_bad_layer_other_hash")
def invalid_proof_of_inclusion_bad_layer_other_hash_fixture(
    valid_proof_of_inclusion: ProofOfInclusion,
) -> ProofOfInclusion:
    layers = list(valid_proof_of_inclusion.layers)
    layers[1] = dataclasses.replace(layers[1], other_hash=bytes32(b"f" * 32))
    return dataclasses.replace(valid_proof_of_inclusion, layers=layers)


@pytest.fixture(name="invalid_proof_of_inclusion_bad_layer_other_hash_side")
def invalid_proof_of_inclusion_bad_layer_other_hash_side_fixture(
    valid_proof_of_inclusion: ProofOfInclusion,
) -> ProofOfInclusion:
    layers = list(valid_proof_of_inclusion.layers)
    layers[1] = dataclasses.replace(layers[1], other_hash_side=layers[1].other_hash_side.other())
    return dataclasses.replace(valid_proof_of_inclusion, layers=layers)


def test_proof_of_inclusion_is_valid(valid_proof_of_inclusion: ProofOfInclusion) -> None:
    assert valid_proof_of_inclusion.valid()


def test_proof_of_inclusion_is_invalid_bad_root(invalid_proof_of_inclusion_bad_root: ProofOfInclusion) -> None:
    assert not invalid_proof_of_inclusion_bad_root.valid()


def test_proof_of_inclusion_is_invalid_bad_layer_other_hash(
    invalid_proof_of_inclusion_bad_layer_other_hash: ProofOfInclusion,
) -> None:
    assert not invalid_proof_of_inclusion_bad_layer_other_hash.valid()


def test_proof_of_inclusion_is_invalid_bad_layer_other_hash_side(
    invalid_proof_of_inclusion_bad_layer_other_hash_side: ProofOfInclusion,
) -> None:
    assert not invalid_proof_of_inclusion_bad_layer_other_hash_side.valid()
