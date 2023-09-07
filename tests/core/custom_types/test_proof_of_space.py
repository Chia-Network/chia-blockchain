from __future__ import annotations

from dataclasses import dataclass
from secrets import token_bytes
from typing import Optional

import pytest
from blspy import G1Element

from chia.consensus.default_constants import DEFAULT_CONSTANTS
from chia.types.blockchain_format.proof_of_space import ProofOfSpace, passes_plot_filter, verify_and_get_quality_string
from chia.types.blockchain_format.sized_bytes import bytes32, bytes48
from chia.util.ints import uint8, uint32
from tests.util.misc import Marks, datacases


@dataclass
class ProofOfSpaceCase:
    id: str
    pos_challenge: bytes32
    plot_size: uint8
    plot_public_key: G1Element
    pool_public_key: Optional[G1Element] = None
    pool_contract_puzzle_hash: Optional[bytes32] = None
    height: uint32 = uint32(0)
    expected_error: Optional[str] = None
    marks: Marks = ()


@datacases(
    ProofOfSpaceCase(
        id="Neither pool public key nor pool contract puzzle hash",
        pos_challenge=bytes32(b"1" * 32),
        plot_size=uint8(0),
        plot_public_key=G1Element(),
        expected_error="Expected pool public key or pool contract puzzle hash but got neither",
    ),
    ProofOfSpaceCase(
        id="Both pool public key and pool contract puzzle hash",
        pos_challenge=bytes32(b"1" * 32),
        plot_size=uint8(0),
        plot_public_key=G1Element(),
        pool_public_key=G1Element(),
        pool_contract_puzzle_hash=bytes32(b"1" * 32),
        expected_error="Expected pool public key or pool contract puzzle hash but got both",
    ),
    ProofOfSpaceCase(
        id="Lower than minimum plot size",
        pos_challenge=bytes32(b"1" * 32),
        plot_size=uint8(31),
        plot_public_key=G1Element(),
        pool_public_key=G1Element(),
        expected_error="Plot size is lower than the minimum",
    ),
    ProofOfSpaceCase(
        id="Higher than maximum plot size",
        pos_challenge=bytes32(b"1" * 32),
        plot_size=uint8(51),
        plot_public_key=G1Element(),
        pool_public_key=G1Element(),
        expected_error="Plot size is higher than the maximum",
    ),
    ProofOfSpaceCase(
        id="Different challenge",
        pos_challenge=bytes32(b"1" * 32),
        plot_size=uint8(42),
        pool_public_key=G1Element(),
        plot_public_key=G1Element(),
        expected_error="Calculated pos challenge doesn't match the provided one",
    ),
    ProofOfSpaceCase(
        id="Not passing the plot filter with size 9",
        pos_challenge=bytes32.from_hexstr("08b23cc2844dfb92d2eedaa705a1ce665d571ee753bd81cbb67b92caa6d34722"),
        plot_size=uint8(42),
        pool_public_key=G1Element.from_bytes_unchecked(
            bytes48.from_hexstr(
                "b6449c2c68df97c19e884427e42ee7350982d4020571ead08732615ff39bd216bfd630b6460784982bec98b49fea79d0"
            )
        ),
        plot_public_key=G1Element.from_bytes_unchecked(
            bytes48.from_hexstr(
                "b17d368f5400230b2b01464807825bf4163c5c159bd7d4465f935912e538ac9fb996dd9a9c479bd8aa6256bdca1fed96"
            )
        ),
        height=uint32(5495999),
        expected_error="Did not pass the plot filter",
    ),
    ProofOfSpaceCase(
        id="Passing the plot filter with size 8",
        pos_challenge=bytes32.from_hexstr("08b23cc2844dfb92d2eedaa705a1ce665d571ee753bd81cbb67b92caa6d34722"),
        plot_size=uint8(42),
        pool_public_key=G1Element.from_bytes_unchecked(
            bytes48.from_hexstr(
                "b6449c2c68df97c19e884427e42ee7350982d4020571ead08732615ff39bd216bfd630b6460784982bec98b49fea79d0"
            )
        ),
        plot_public_key=G1Element.from_bytes_unchecked(
            bytes48.from_hexstr(
                "b17d368f5400230b2b01464807825bf4163c5c159bd7d4465f935912e538ac9fb996dd9a9c479bd8aa6256bdca1fed96"
            )
        ),
        height=uint32(5496000),
    ),
)
def test_verify_and_get_quality_string(caplog: pytest.LogCaptureFixture, case: ProofOfSpaceCase) -> None:
    pos = ProofOfSpace(
        challenge=case.pos_challenge,
        pool_public_key=case.pool_public_key,
        pool_contract_puzzle_hash=case.pool_contract_puzzle_hash,
        plot_public_key=case.plot_public_key,
        size=case.plot_size,
        proof=b"1",
    )
    quality_string = verify_and_get_quality_string(
        pos=pos,
        constants=DEFAULT_CONSTANTS,
        original_challenge_hash=bytes32.from_hexstr(
            "0x73490e166d0b88347c37d921660b216c27316aae9a3450933d3ff3b854e5831a"
        ),
        signage_point=bytes32.from_hexstr("0x7b3e23dbd438f9aceefa9827e2c5538898189987f49b06eceb7a43067e77b531"),
        height=case.height,
    )
    assert quality_string is None
    assert len(caplog.text) == 0 if case.expected_error is None else case.expected_error in caplog.text


class TestProofOfSpace:
    @pytest.mark.parametrize("prefix_bits", [DEFAULT_CONSTANTS.NUMBER_ZERO_BITS_PLOT_FILTER, 8, 7, 6, 5, 1, 0])
    def test_can_create_proof(self, prefix_bits: int) -> None:
        """
        Tests that the change of getting a correct proof is exactly 1/target_filter.
        """
        num_trials = 100000
        success_count = 0
        target_filter = 2**prefix_bits
        for _ in range(num_trials):
            challenge_hash = bytes32(token_bytes(32))
            plot_id = bytes32(token_bytes(32))
            sp_output = bytes32(token_bytes(32))

            if passes_plot_filter(prefix_bits, plot_id, challenge_hash, sp_output):
                success_count += 1

        assert abs((success_count * target_filter / num_trials) - 1) < 0.35
