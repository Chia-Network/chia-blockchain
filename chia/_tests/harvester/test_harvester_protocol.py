from __future__ import annotations

from dataclasses import replace

import pytest
from chia_rs import G1Element, PartialProof
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint8, uint16, uint64
from packaging.version import Version

from chia.harvester.harvester_api import batch_partial_proofs
from chia.protocols.harvester_protocol import (
    MAX_PARTIAL_PROOFS_MESSAGE_SIZE,
    PartialProofsData,
    Plot,
    Plot2,
    supports_new_plot_serialization,
)


def test_old_v2_plot_param_uses_legacy_zero_index_and_meta_group() -> None:
    plot = Plot(
        filename="v2.gplot",
        size=uint8(0x80 | 3),
        plot_id=bytes32.zeros,
        pool_public_key=G1Element(),
        pool_contract_puzzle_hash=None,
        plot_public_key=G1Element(),
        file_size=uint64(0),
        time_modified=uint64(0),
        compression_level=uint8(0),
    )

    param = plot.param()

    assert param.size_v1 is None
    assert param.strength_v2 == 3
    assert param.plot_index == 0
    assert param.meta_group == 0


def test_v2_plot2_param_preserves_index_and_meta_group() -> None:
    plot = Plot2(
        filename="v2.gplot",
        size=uint8(0x80 | 3),
        plot_id=bytes32.zeros,
        pool_public_key=G1Element(),
        pool_contract_puzzle_hash=None,
        plot_public_key=G1Element(),
        file_size=uint64(0),
        time_modified=uint64(0),
        compression_level=uint8(0),
        plot_index=uint16(1234),
        meta_group=uint8(56),
        group_size=uint16(8),
    )

    param = plot.param()

    assert param.size_v1 is None
    assert param.strength_v2 == 3
    assert param.plot_index == 1234
    assert param.meta_group == 56


def test_new_plot_serialization_starts_at_0_0_38() -> None:
    assert not supports_new_plot_serialization(Version("0.0.37"))
    assert supports_new_plot_serialization(Version("0.0.38"))


@pytest.mark.parametrize("count", [0, 1, 20, 100])
@pytest.mark.parametrize("filename_length", [20, 1000])
def test_partial_proof_batches_preserve_indices_and_size(count: int, filename_length: int) -> None:
    response = PartialProofsData(
        challenge_hash=bytes32.zeros,
        sp_hash=bytes32.zeros,
        plot_identifier="p" * filename_length,
        partial_proofs=[PartialProof([uint64(256)] * 16, uint16(index)) for index in range(count)],
        signage_point_index=uint8(0),
        plot_size=uint8(28),
        meta_group=uint8(7),
        strength=uint8(2),
        plot_group_id=bytes32.zeros,
        pool_public_key=None,
        pool_contract_puzzle_hash=bytes32.zeros,
        plot_public_key=G1Element.generator(),
    )
    batches = batch_partial_proofs(response)
    recovered = []
    for batch in batches:
        assert batch.partial_proofs
        assert len(bytes(batch)) <= MAX_PARTIAL_PROOFS_MESSAGE_SIZE
        assert replace(batch, partial_proofs=[]) == replace(response, partial_proofs=[])
        recovered.extend(PartialProofsData.from_bytes(bytes(batch)).partial_proofs)
    assert recovered == response.partial_proofs
    if count == 20 and filename_length == 1000:
        assert len(batches) > 1
    with pytest.raises(ValueError, match="metadata exceeds"):
        batch_partial_proofs(
            replace(
                response,
                plot_identifier="p" * MAX_PARTIAL_PROOFS_MESSAGE_SIZE,
                partial_proofs=[PartialProof([uint64(0)] * 16, uint16(0))],
            )
        )
