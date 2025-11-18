from __future__ import annotations

import logging
import random
from dataclasses import dataclass

import pytest
from chia_rs import G1Element, PlotParam
from chia_rs.sized_bytes import bytes32, bytes48
from chia_rs.sized_ints import uint8, uint32

from chia._tests.util.misc import Marks, datacases
from chia.consensus.default_constants import DEFAULT_CONSTANTS
from chia.types.blockchain_format.proof_of_space import (
    calculate_prefix_bits,
    check_plot_param,
    is_v1_phased_out,
    make_pos,
    passes_plot_filter,
    verify_and_get_quality_string,
)


@dataclass
class ProofOfSpaceCase:
    id: str
    pos_challenge: bytes32
    plot_size: PlotParam
    plot_public_key: G1Element
    pool_public_key: G1Element | None = None
    pool_contract_puzzle_hash: bytes32 | None = None
    height: uint32 = DEFAULT_CONSTANTS.HARD_FORK2_HEIGHT
    expected_error: str | None = None
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
        plot_size=PlotParam.make_v1(0),
        plot_public_key=G1Element(),
        expected_error="Expected pool public key or pool contract puzzle hash but got neither",
    ),
    ProofOfSpaceCase(
        id="Both pool public key and pool contract puzzle hash",
        pos_challenge=bytes32(b"1" * 32),
        plot_size=PlotParam.make_v1(0),
        plot_public_key=G1Element(),
        pool_public_key=G1Element(),
        pool_contract_puzzle_hash=bytes32(b"1" * 32),
        expected_error="Expected pool public key or pool contract puzzle hash but got both",
    ),
    ProofOfSpaceCase(
        id="Lower than minimum plot size",
        pos_challenge=bytes32(b"1" * 32),
        plot_size=PlotParam.make_v1(31),
        plot_public_key=G1Element(),
        pool_public_key=G1Element(),
        expected_error="Plot size (31) is lower than the minimum (32)",
    ),
    ProofOfSpaceCase(
        id="Higher than maximum plot size",
        pos_challenge=bytes32(b"1" * 32),
        plot_size=PlotParam.make_v1(51),
        plot_public_key=G1Element(),
        pool_public_key=G1Element(),
        expected_error="Plot size (51) is higher than the maximum (50)",
    ),
    ProofOfSpaceCase(
        id="Different challenge",
        pos_challenge=bytes32(b"1" * 32),
        plot_size=PlotParam.make_v1(42),
        pool_public_key=G1Element(),
        plot_public_key=G1Element(),
        expected_error="Calculated pos challenge doesn't match the provided one",
    ),
    ProofOfSpaceCase(
        id="Not passing the plot filter with size 9",
        pos_challenge=b32("08b23cc2844dfb92d2eedaa705a1ce665d571ee753bd81cbb67b92caa6d34722"),
        plot_size=PlotParam.make_v1(42),
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
        plot_size=PlotParam.make_v1(42),
        pool_public_key=g1(
            "b6449c2c68df97c19e884427e42ee7350982d4020571ead08732615ff39bd216bfd630b6460784982bec98b49fea79d0"
        ),
        plot_public_key=g1(
            "b17d368f5400230b2b01464807825bf4163c5c159bd7d4465f935912e538ac9fb996dd9a9c479bd8aa6256bdca1fed96"
        ),
        height=uint32(5496000),
    ),
    ProofOfSpaceCase(
        id="v2 plot strength 0",
        pos_challenge=bytes32(b"1" * 32),
        plot_size=PlotParam.make_v2(0),
        pool_contract_puzzle_hash=bytes32(b"1" * 32),
        plot_public_key=G1Element(),
        expected_error="Plot strength (0) is lower than the minimum (2)",
    ),
    ProofOfSpaceCase(
        id="v2 plot strength 33",
        pos_challenge=bytes32(b"1" * 32),
        plot_size=PlotParam.make_v2(33),
        pool_contract_puzzle_hash=bytes32(b"1" * 32),
        plot_public_key=G1Element(),
        expected_error="Plot strength (33) is too high (max is 32)",
    ),
    ProofOfSpaceCase(
        id="Not passing the plot filter v2",
        pos_challenge=b32("2b76a5fe5d4ae062ba9e80b5bcb0e9c1301f3a2787b8f3141e3fb458d1c1864c"),
        plot_size=PlotParam.make_v2(32),
        pool_contract_puzzle_hash=bytes32(b"1" * 32),
        plot_public_key=g1(
            "879526b4e7b616cfd64984d8ad140d0798b048392a6f11e2faf09054ef467ea44dc0dab5e5edb2afdfa850c5c8b629cc"
        ),
        expected_error="Did not pass the plot filter",
    ),
    ProofOfSpaceCase(
        id="v2 not activated",
        pos_challenge=bytes32(b"1" * 32),
        plot_size=PlotParam.make_v2(2),
        pool_contract_puzzle_hash=bytes32(b"1" * 32),
        plot_public_key=G1Element(),
        height=uint32(DEFAULT_CONSTANTS.HARD_FORK2_HEIGHT - 1),
        expected_error="v2 proof support has not yet activated",
    ),
)
def test_verify_and_get_quality_string(caplog: pytest.LogCaptureFixture, case: ProofOfSpaceCase) -> None:
    caplog.set_level(logging.INFO)
    pos = make_pos(
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
        prev_transaction_block_height=case.height,
    )
    assert quality_string is None
    assert len(caplog.text) == 0 if case.expected_error is None else case.expected_error in caplog.text


@datacases(
    ProofOfSpaceCase(
        id="not passing the plot filter v2",
        plot_size=PlotParam.make_v2(28),
        pos_challenge=b32("be7ac7436520a3fa259a618a2c54de4ca8b8d2319c1ec5b11a2ef4c025c2e0a6"),
        plot_public_key=g1(
            "afa3aaf09c03885154be49216ee7fb2e4581b9c4a4d7e9cc402e27280bf0cfdbdf1b9ba674e301fd1d1450234b3b1868"
        ),
        pool_contract_puzzle_hash=bytes32(b"1" * 32),
        expected_error="Did not pass the plot filter",
    ),
    # TODO: todo_v2_plots add test case that passes the plot filter
)
def test_verify_and_get_quality_string_v2(caplog: pytest.LogCaptureFixture, case: ProofOfSpaceCase) -> None:
    pos = make_pos(
        challenge=case.pos_challenge,
        pool_public_key=case.pool_public_key,
        pool_contract_puzzle_hash=case.pool_contract_puzzle_hash,
        plot_public_key=case.plot_public_key,
        version_and_size=case.plot_size,
        proof=b"1",
    )
    plot_param = pos.param()
    assert plot_param.strength_v2 is not None
    assert plot_param.size_v1 is None
    try:
        quality_string = verify_and_get_quality_string(
            pos=pos,
            constants=DEFAULT_CONSTANTS,
            original_challenge_hash=b32("0x73490e166d0b88347c37d921660b216c27316aae9a3450933d3ff3b854e5831a"),
            signage_point=b32("0x7b3e23dbd438f9aceefa9827e2c5538898189987f49b06eceb7a43067e77b531"),
            height=case.height,
            prev_transaction_block_height=case.height,
        )
    except NotImplementedError as e:
        assert case.expected_error is not None
        assert case.expected_error in repr(e)
    else:
        assert quality_string is None
        assert len(caplog.text) == 0 if case.expected_error is None else case.expected_error in caplog.text


@pytest.mark.parametrize(
    "plot_param, valid",
    [
        (PlotParam.make_v1(31), False),  # too small
        (PlotParam.make_v1(32), True),
        (PlotParam.make_v1(33), True),
        (PlotParam.make_v1(34), True),
        (PlotParam.make_v1(35), True),
        (PlotParam.make_v1(36), True),
        (PlotParam.make_v1(37), True),
        (PlotParam.make_v1(49), True),
        (PlotParam.make_v1(50), True),
        (PlotParam.make_v1(51), False),  # too large
        (PlotParam.make_v2(1), False),  # too small
        (PlotParam.make_v2(2), True),
        (PlotParam.make_v2(3), True),
        (PlotParam.make_v2(32), True),
        (PlotParam.make_v2(33), False),  # strength too high
    ],
)
def test_check_plot_param(plot_param: PlotParam, valid: bool) -> None:
    assert check_plot_param(DEFAULT_CONSTANTS, plot_param) == valid


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
def test_calculate_prefix_bits_clamp_zero_v1(height: uint32, expected: int) -> None:
    constants = DEFAULT_CONSTANTS.replace(NUMBER_ZERO_BITS_PLOT_FILTER_V1=uint8(3))
    assert calculate_prefix_bits(constants, height, PlotParam.make_v1(32)) == expected


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
def test_calculate_prefix_bits_v1(height: uint32, expected: int) -> None:
    assert calculate_prefix_bits(DEFAULT_CONSTANTS, height, PlotParam.make_v1(32)) == expected


@pytest.mark.parametrize(
    argnames=["height", "expected"],
    argvalues=[
        (0, 5),
        (0xFFFFFFFA, 5),
        (0xFFFFFFFB, 6),
        (0xFFFFFFFC, 7),
        (0xFFFFFFFD, 8),
        (0xFFFFFFFF, 8),
    ],
)
def test_calculate_prefix_bits_v2(height: uint32, expected: int) -> None:
    assert calculate_prefix_bits(DEFAULT_CONSTANTS, height, PlotParam.make_v2(28)) == expected


def test_v1_phase_out() -> None:
    constants = DEFAULT_CONSTANTS.replace(HARD_FORK2_HEIGHT=uint32(500000))
    rng = random.Random()

    phase_out_epochs = 1 << constants.PLOT_V1_PHASE_OUT_EPOCH_BITS
    print(f"phase-out epochs: {phase_out_epochs}")

    for epoch in range(-5, phase_out_epochs + 5):
        prev_tx_height = uint32(constants.HARD_FORK2_HEIGHT + epoch * constants.EPOCH_BLOCKS)
        num_phased_out = 0
        rng.seed(1337)
        for i in range(1000):
            proof = rng.randbytes(32)
            if is_v1_phased_out(proof, prev_tx_height, constants):
                num_phased_out += 1

        expect = min(1.0, max(0.0, epoch / phase_out_epochs))

        print(
            f"height: {prev_tx_height} "
            f"epoch: {epoch} "
            f"phased-out: {num_phased_out / 10:0.2f}% "
            f"expect: {expect * 100.0:0.2f}%"
        )
        assert abs((num_phased_out / 1000) - expect) < 0.05
