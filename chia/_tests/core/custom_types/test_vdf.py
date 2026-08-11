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


@pytest.mark.parametrize(
    ("witness_type", "witness_size"),
    [
        # Empty / truncated / one-byte-long for witness_type 0 (expected 100).
        (uint8(0), 0),
        (uint8(0), 99),
        (uint8(0), 101),
        # Correct length for a different witness_type.
        (uint8(1), 100),
        (uint8(0), 241),
        # Off-by-one around witness_type 1 (expected 241).
        (uint8(1), 240),
        (uint8(1), 242),
        # Off-by-one around witness_type 63 (expected 8983).
        (uint8(63), 8982),
        (uint8(63), 8984),
    ],
    ids=[
        "type0_empty",
        "type0_one_short",
        "type0_one_long",
        "type1_with_type0_size",
        "type0_with_type1_size",
        "type1_one_short",
        "type1_one_long",
        "type63_one_short",
        "type63_one_long",
    ],
)
def test_invalid_witness_size_rejected_before_verifier(witness_type: uint8, witness_size: int) -> None:
    cache_info_before = vdf.verify_vdf.cache_info()

    classgroup_element = ClassgroupElement.get_default_element()
    info = VDFInfo(bytes32.zeros, uint64(1), classgroup_element)
    proof = VDFProof(witness_type, bytes(witness_size), False)

    assert not vdf.validate_vdf(proof, DEFAULT_CONSTANTS, classgroup_element, info)
    assert vdf.verify_vdf.cache_info() == cache_info_before


def test_witness_type_above_max_rejected_before_verifier() -> None:
    cache_info_before = vdf.verify_vdf.cache_info()

    classgroup_element = ClassgroupElement.get_default_element()
    info = VDFInfo(bytes32.zeros, uint64(1), classgroup_element)
    # MAX_VDF_WITNESS_SIZE is 64; witness_type + 1 must be <= 64, so 64 is rejected.
    proof = VDFProof(uint8(64), bytes(100), False)

    assert not vdf.validate_vdf(proof, DEFAULT_CONSTANTS, classgroup_element, info)
    assert vdf.verify_vdf.cache_info() == cache_info_before
