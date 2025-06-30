from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Optional

import pytest
from chia_rs import G1Element, PlotSize, ProofOfSpace
from chia_rs.sized_bytes import bytes32, bytes48
from chia_rs.sized_ints import uint8, uint32

from chia._tests.util.misc import Marks, datacases
from chia.consensus.default_constants import DEFAULT_CONSTANTS
from chia.types.blockchain_format.proof_of_space import (
    calculate_plot_difficulty,
    calculate_prefix_bits,
    passes_plot_filter,
    verify_and_get_quality_string,
)


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


def g1(key: str) -> G1Element:
    return G1Element.from_bytes_unchecked(bytes48.from_hexstr(key))


def b32(key: str) -> bytes32:
    return bytes32.from_hexstr(key)


# TODO: todo_v2_plots more test cases
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
        pos_challenge=b32("08b23cc2844dfb92d2eedaa705a1ce665d571ee753bd81cbb67b92caa6d34722"),
        plot_size=uint8(42),
        pool_public_key=g1(
            "b6449c2c68df97c19e884427e42ee7350982d4020571ead08732615ff39bd216bfd630b6460784982bec98b49fea79d0"
        ),
        plot_public_key=g1(
            "b17d368f5400230b2b01464807825bf4163c5c159bd7d4465f935912e538ac9fb996dd9a9c479bd8aa6256bdca1fed96"
        ),
        height=uint32(5495999),
        expected_error="Did not pass the plot filter",
    ),
    ProofOfSpaceCase(
        id="Passing the plot filter with size 8",
        pos_challenge=b32("08b23cc2844dfb92d2eedaa705a1ce665d571ee753bd81cbb67b92caa6d34722"),
        plot_size=uint8(42),
        pool_public_key=g1(
            "b6449c2c68df97c19e884427e42ee7350982d4020571ead08732615ff39bd216bfd630b6460784982bec98b49fea79d0"
        ),
        plot_public_key=g1(
            "b17d368f5400230b2b01464807825bf4163c5c159bd7d4465f935912e538ac9fb996dd9a9c479bd8aa6256bdca1fed96"
        ),
        height=uint32(5496000),
    ),
    ProofOfSpaceCase(
        id="v2 plot size 0",
        pos_challenge=bytes32(b"1" * 32),
        plot_size=uint8(0x80),
        plot_public_key=G1Element(),
        pool_public_key=G1Element(),
        expected_error="Plot size is lower than the minimum",
    ),
    ProofOfSpaceCase(
        id="v2 plot size 34",
        pos_challenge=bytes32(b"1" * 32),
        plot_size=uint8(0x80 | 34),
        plot_public_key=G1Element(),
        pool_public_key=G1Element(),
        expected_error="Plot size is higher than the maximum",
    ),
    ProofOfSpaceCase(
        id="Not passing the plot filter v2",
        pos_challenge=b32("3d29ea79d19b3f7e99ebf764ae53697cbe143603909873946af6ab1ece606861"),
        plot_size=uint8(0x80 | 32),
        pool_public_key=g1(
            "b6449c2c68df97c19e884427e42ee7350982d4020571ead08732615ff39bd216bfd630b6460784982bec98b49fea79d0"
        ),
        plot_public_key=g1(
            "879526b4e7b616cfd64984d8ad140d0798b048392a6f11e2faf09054ef467ea44dc0dab5e5edb2afdfa850c5c8b629cc"
        ),
        expected_error="Did not pass the plot filter",
    ),
)
def test_verify_and_get_quality_string(caplog: pytest.LogCaptureFixture, case: ProofOfSpaceCase) -> None:
    pos = ProofOfSpace(
        challenge=case.pos_challenge,
        pool_public_key=case.pool_public_key,
        pool_contract_puzzle_hash=case.pool_contract_puzzle_hash,
        plot_public_key=case.plot_public_key,
        version_and_size=case.plot_size,
        proof=b"1",
    )
    quality_string = verify_and_get_quality_string(
        pos=pos,
        constants=DEFAULT_CONSTANTS,
        original_challenge_hash=b32("0x73490e166d0b88347c37d921660b216c27316aae9a3450933d3ff3b854e5831a"),
        signage_point=b32("0x7b3e23dbd438f9aceefa9827e2c5538898189987f49b06eceb7a43067e77b531"),
        height=case.height,
    )
    assert quality_string is None
    assert len(caplog.text) == 0 if case.expected_error is None else case.expected_error in caplog.text


@datacases(
    ProofOfSpaceCase(
        id="v2 plot are not implemented",
        plot_size=uint8(0x80 | 30),
        pos_challenge=b32("47deb938e145d25d7b3b3c85ca9e3972b76c01aeeb78a02fe5d3b040d282317e"),
        plot_public_key=g1(
            "afa3aaf09c03885154be49216ee7fb2e4581b9c4a4d7e9cc402e27280bf0cfdbdf1b9ba674e301fd1d1450234b3b1868"
        ),
        pool_public_key=g1(
            "b6449c2c68df97c19e884427e42ee7350982d4020571ead08732615ff39bd216bfd630b6460784982bec98b49fea79d0"
        ),
        expected_error="NotImplementedError",
    ),
)
def test_verify_and_get_quality_string_v2(caplog: pytest.LogCaptureFixture, case: ProofOfSpaceCase) -> None:
    pos = ProofOfSpace(
        challenge=case.pos_challenge,
        pool_public_key=case.pool_public_key,
        pool_contract_puzzle_hash=case.pool_contract_puzzle_hash,
        plot_public_key=case.plot_public_key,
        version_and_size=case.plot_size,
        proof=b"1",
    )
    size = pos.size()
    assert size.size_v2 is not None
    assert size.size_v1 is None
    try:
        quality_string = verify_and_get_quality_string(
            pos=pos,
            constants=DEFAULT_CONSTANTS,
            original_challenge_hash=b32("0x73490e166d0b88347c37d921660b216c27316aae9a3450933d3ff3b854e5831a"),
            signage_point=b32("0x7b3e23dbd438f9aceefa9827e2c5538898189987f49b06eceb7a43067e77b531"),
            height=case.height,
        )
    except NotImplementedError as e:
        assert case.expected_error is not None
        assert case.expected_error in repr(e)
    else:
        assert quality_string is None
        assert len(caplog.text) == 0 if case.expected_error is None else case.expected_error in caplog.text


@pytest.mark.parametrize(
    "height, difficulty",
    [
        (0, 2),
        (DEFAULT_CONSTANTS.HARD_FORK_HEIGHT, 2),
        (DEFAULT_CONSTANTS.HARD_FORK2_HEIGHT, 2),
        (DEFAULT_CONSTANTS.PLOT_DIFFICULTY_4_HEIGHT - 1, 2),
        (DEFAULT_CONSTANTS.PLOT_DIFFICULTY_4_HEIGHT, 4),
        (DEFAULT_CONSTANTS.PLOT_DIFFICULTY_5_HEIGHT - 1, 4),
        (DEFAULT_CONSTANTS.PLOT_DIFFICULTY_5_HEIGHT, 5),
        (DEFAULT_CONSTANTS.PLOT_DIFFICULTY_6_HEIGHT - 1, 5),
        (DEFAULT_CONSTANTS.PLOT_DIFFICULTY_6_HEIGHT, 6),
        (DEFAULT_CONSTANTS.PLOT_DIFFICULTY_7_HEIGHT - 1, 6),
        (DEFAULT_CONSTANTS.PLOT_DIFFICULTY_7_HEIGHT, 7),
        (DEFAULT_CONSTANTS.PLOT_DIFFICULTY_8_HEIGHT - 1, 7),
        (DEFAULT_CONSTANTS.PLOT_DIFFICULTY_8_HEIGHT, 8),
        (DEFAULT_CONSTANTS.PLOT_DIFFICULTY_8_HEIGHT + 1000000, 8),
    ],
)
def test_calculate_plot_difficulty(height: uint32, difficulty: uint8) -> None:
    assert calculate_plot_difficulty(DEFAULT_CONSTANTS, height) == difficulty


class TestProofOfSpace:
    @pytest.mark.parametrize("prefix_bits", [DEFAULT_CONSTANTS.NUMBER_ZERO_BITS_PLOT_FILTER_V1, 8, 7, 6, 5, 1, 0])
    def test_can_create_proof(self, prefix_bits: int, seeded_random: random.Random) -> None:
        """
        Tests that the change of getting a correct proof is exactly 1/target_filter.
        """
        num_trials = 100000
        success_count = 0
        target_filter = 2**prefix_bits
        for _ in range(num_trials):
            challenge_hash = bytes32.random(seeded_random)
            plot_id = bytes32.random(seeded_random)
            sp_output = bytes32.random(seeded_random)

            if passes_plot_filter(prefix_bits, plot_id, challenge_hash, sp_output):
                success_count += 1

        assert abs((success_count * target_filter / num_trials) - 1) < 0.35


@pytest.mark.parametrize("height,expected", [(0, 3), (5496000, 2), (10542000, 1), (15592000, 0), (20643000, 0)])
@pytest.mark.parametrize("plot_size", [PlotSize.make_v1(32), PlotSize.make_v2(28)])
def test_calculate_prefix_bits_clamp_zero(height: uint32, expected: int, plot_size: PlotSize) -> None:
    constants = DEFAULT_CONSTANTS.replace(NUMBER_ZERO_BITS_PLOT_FILTER_V1=uint8(3))
    if plot_size.size_v2 is not None:
        expected = constants.NUMBER_ZERO_BITS_PLOT_FILTER_V2
    assert calculate_prefix_bits(constants, height, plot_size) == expected


@pytest.mark.parametrize(
    argnames=["height", "expected"],
    argvalues=[
        (0, 9),
        (5495999, 9),
        (5496000, 8),
        (10541999, 8),
        (10542000, 7),
        (15591999, 7),
        (15592000, 6),
        (20642999, 6),
        (20643000, 5),
    ],
)
@pytest.mark.parametrize("plot_size", [PlotSize.make_v1(32), PlotSize.make_v2(28)])
def test_calculate_prefix_bits_default(height: uint32, expected: int, plot_size: PlotSize) -> None:
    constants = DEFAULT_CONSTANTS
    if plot_size.size_v2 is not None:
        expected = DEFAULT_CONSTANTS.NUMBER_ZERO_BITS_PLOT_FILTER_V2
    assert calculate_prefix_bits(constants, height, plot_size) == expected
