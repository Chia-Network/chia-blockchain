import dataclasses
from typing import List

import pytest

# TODO: update after resolution in https://github.com/pytest-dev/pytest/issues/7469
from _pytest.fixtures import SubRequest

from chia.data_layer.data_layer_types import ProofOfInclusion, ProofOfInclusionLayer, Side
from chia.types.blockchain_format.sized_bytes import bytes32


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


@pytest.fixture(name="invalid_proof_of_inclusion", params=[0, 1, 2])
def invalid_proof_of_inclusion_fixture(
    request: SubRequest, valid_proof_of_inclusion: ProofOfInclusion
) -> ProofOfInclusion:
    layers = list(valid_proof_of_inclusion.layers)
    if request.param == 0:
        layers[-1] = dataclasses.replace(layers[-1], combined_hash=bytes32(b"f" * 32))
    elif request.param == 1:
        layers[1] = dataclasses.replace(layers[1], other_hash=bytes32(b"f" * 32))
    elif request.param == 2:
        layers[1] = dataclasses.replace(layers[1], other_hash_side=layers[1].other_hash_side.other())
    return dataclasses.replace(valid_proof_of_inclusion, layers=layers)


def test_proof_of_inclusion_is_valid(valid_proof_of_inclusion: ProofOfInclusion) -> None:
    assert valid_proof_of_inclusion.valid()


def test_proof_of_inclusion_is_invalid(invalid_proof_of_inclusion: ProofOfInclusion) -> None:
    assert not invalid_proof_of_inclusion.valid()
