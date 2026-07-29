from __future__ import annotations

import pytest
from chia_rs import VDFInfo, VDFProof
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint8, uint64

from chia.consensus.default_constants import DEFAULT_CONSTANTS
from chia.types.blockchain_format import vdf
from chia.types.blockchain_format.classgroup import ClassgroupElement


@pytest.mark.parametrize(
    ("witness_type", "witness_size"),
    [
        (uint8(0), 100),
        (uint8(1), 241),
        (uint8(63), 8983),
    ],
)
def test_expected_witness_sizes_reach_verifier(
    monkeypatch: pytest.MonkeyPatch, witness_type: uint8, witness_size: int
) -> None:
    verifier_calls = 0

    def accept_proof(*args: object) -> bool:
        nonlocal verifier_calls
        verifier_calls += 1
        return True

    monkeypatch.setattr(vdf, "get_discriminant", lambda *args: 1)
    monkeypatch.setattr(vdf, "verify_vdf", accept_proof)

    classgroup_element = ClassgroupElement.get_default_element()
    info = VDFInfo(bytes32.zeros, uint64(1), classgroup_element)
    proof = VDFProof(witness_type, bytes(witness_size), False)

    assert vdf.validate_vdf(proof, DEFAULT_CONSTANTS, classgroup_element, info)
    assert verifier_calls == 1


def test_oversized_witness_rejected_before_cached_verifier() -> None:
    cache_info_before = vdf.verify_vdf.cache_info()

    classgroup_element = ClassgroupElement.get_default_element()
    info = VDFInfo(bytes32.zeros, uint64(1), classgroup_element)
    proof = VDFProof(uint8(0), bytes(2_000_000), False)

    assert not vdf.validate_vdf(proof, DEFAULT_CONSTANTS, classgroup_element, info)
    assert vdf.verify_vdf.cache_info() == cache_info_before
