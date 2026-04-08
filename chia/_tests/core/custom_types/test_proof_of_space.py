from __future__ import annotations

import logging
import random
from dataclasses import dataclass

import pytest
from chia_rs import AugSchemeMPL, G1Element, PlotParam
from chia_rs.sized_bytes import bytes32, bytes48
from chia_rs.sized_ints import uint8, uint32

from chia._tests.util.misc import Marks, datacases
from chia.consensus.default_constants import DEFAULT_CONSTANTS
from chia.types.blockchain_format.proof_of_space import (
    calculate_base_plot_filter_bits,
    calculate_max_plot_strength,
    calculate_prefix_bits,
    check_plot_param,
    compute_plot_group_id_from_pos,
    is_v1_phased_out,
    make_pos,
    num_phase_out_epochs,
    passes_plot_filter,
    passes_plot_filter_v2,
    verify_and_get_quality_string,
)
from chia.util.hash import std_hash


def _test_pk() -> G1Element:
    return AugSchemeMPL.key_gen(b"\x01" * 32).get_g1()


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
        id="v2 plot strength 0 challenge mismatch",
        pos_challenge=bytes32(b"1" * 32),
        plot_size=PlotParam.make_v2(0, 0, 0),
        pool_contract_puzzle_hash=bytes32(b"1" * 32),
        plot_public_key=G1Element(),
        expected_error="Calculated pos challenge doesn't match the provided one",
    ),
    ProofOfSpaceCase(
        id="v2 plot strength 18",
        pos_challenge=bytes32(b"1" * 32),
        plot_size=PlotParam.make_v2(0, 0, 18),
        pool_contract_puzzle_hash=bytes32(b"1" * 32),
        plot_public_key=G1Element(),
        expected_error="Plot strength (18) is too high (max is 17)",
    ),
    ProofOfSpaceCase(
        id="Not passing the plot filter v2 missing filter_challenge",
        pos_challenge=b32("a66f6a2ed7a1fb5f7c1db936e4a5833e06df80afb63fb13f1f85d72b8a018413"),
        plot_size=PlotParam.make_v2(0, 0, 8),
        pool_contract_puzzle_hash=bytes32(b"1" * 32),
        plot_public_key=g1(
            "879526b4e7b616cfd64984d8ad140d0798b048392a6f11e2faf09054ef467ea44dc0dab5e5edb2afdfa850c5c8b629cc"
        ),
        expected_error="V2 plot requires filter_challenge and signage_point_index",
    ),
    ProofOfSpaceCase(
        id="v2 not activated",
        pos_challenge=bytes32(b"1" * 32),
        plot_size=PlotParam.make_v2(0, 0, 2),
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
        params=case.plot_size,
        proof=b"1",
    )
    quality_string = verify_and_get_quality_string(
        pos=pos,
        constants=DEFAULT_CONSTANTS,
        original_challenge_hash=b32("73490e166d0b88347c37d921660b216c27316aae9a3450933d3ff3b854e5831a"),
        signage_point=b32("0x7b3e23dbd438f9aceefa9827e2c5538898189987f49b06eceb7a43067e77b531"),
        height=case.height,
        prev_transaction_block_height=case.height,
    )
    assert quality_string is None
    assert len(caplog.text) == 0 if case.expected_error is None else case.expected_error in caplog.text


@datacases(
    ProofOfSpaceCase(
        id="v2 missing filter_challenge rejected",
        plot_size=PlotParam.make_v2(0, 0, 2),
        pos_challenge=b32("9483df4e178307ae677d86664daaef4fc52689b2b6cd7825351f2a2ad7075adb"),
        plot_public_key=g1(
            "afa3aaf09c03885154be49216ee7fb2e4581b9c4a4d7e9cc402e27280bf0cfdbdf1b9ba674e301fd1d1450234b3b1868"
        ),
        pool_contract_puzzle_hash=bytes32(b"1" * 32),
        expected_error="V2 plot requires filter_challenge and signage_point_index",
    ),
    # TODO: todo_v2_plots add test case that passes the plot filter with filter_challenge
)
def test_verify_and_get_quality_string_v2(caplog: pytest.LogCaptureFixture, case: ProofOfSpaceCase) -> None:
    pos = make_pos(
        challenge=case.pos_challenge,
        pool_public_key=case.pool_public_key,
        pool_contract_puzzle_hash=case.pool_contract_puzzle_hash,
        plot_public_key=case.plot_public_key,
        params=case.plot_size,
        proof=b"1",
    )
    plot_param = pos.param()
    assert plot_param.strength_v2 is not None
    assert plot_param.size_v1 is None
    quality_string = verify_and_get_quality_string(
        pos=pos,
        constants=DEFAULT_CONSTANTS,
        original_challenge_hash=b32("73490e166d0b88347c37d921660b216c27316aae9a3450933d3ff3b854e5831a"),
        signage_point=b32("0xf7c1bd874da5e709d4713d60c8a70639eb1167b367a9c3787c65c1e582e2e662"),
        height=case.height,
        prev_transaction_block_height=case.height,
    )
    assert quality_string is None
    assert case.expected_error is not None
    assert case.expected_error in caplog.text


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
        (PlotParam.make_v2(0, 0, 0), True),
        (PlotParam.make_v2(0, 0, 1), True),
        (PlotParam.make_v2(0, 0, 2), True),
        (PlotParam.make_v2(0, 0, 3), True),
        (PlotParam.make_v2(0, 0, 17), True),
        (PlotParam.make_v2(0, 0, 18), False),  # strength too high
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


def test_calculate_prefix_bits_rejects_v2() -> None:
    with pytest.raises(AssertionError, match="V2 plots use the predictable filter"):
        calculate_prefix_bits(DEFAULT_CONSTANTS, uint32(0), PlotParam.make_v2(0, 0, 28))


@pytest.mark.parametrize(
    "height,expected",
    [
        (uint32(9_562_000), 8),  # 9 base bits -> max 8
        (uint32(19_663_000), 9),  # 8 base bits -> max 9
        (uint32(60_056_000), 17),  # 0 base bits -> max 17
        (uint32(0), 8),  # before schedule -> 9 bits -> max 8
    ],
)
def test_calculate_max_plot_strength(height: uint32, expected: int) -> None:
    assert calculate_max_plot_strength(height, hard_fork2_height=9_562_000) == expected


def test_base_filter_relative_to_fork_height() -> None:
    assert calculate_base_plot_filter_bits(uint32(1_000_000), hard_fork2_height=1_000_000) == 9
    assert calculate_base_plot_filter_bits(uint32(11_101_000), hard_fork2_height=1_000_000) == 8
    assert calculate_base_plot_filter_bits(uint32(0), hard_fork2_height=1_000_000) == 9  # before fork


def test_v1_phase_out() -> None:
    constants = DEFAULT_CONSTANTS.replace(HARD_FORK2_HEIGHT=uint32(500000))
    rng = random.Random()

    phase_out_epochs = num_phase_out_epochs(constants)
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


class TestV2PlotFilter:
    """Tests for V2 plot filter functions."""

    def test_passes_plot_filter_v2_deterministic(self) -> None:
        """Test that V2 filter is deterministic for same inputs."""
        plot_group_id = bytes32.from_hexstr("0xabcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890")
        filter_challenge = bytes32.from_hexstr("0x1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef")
        meta_group = 42
        group_strength = 8  # base_filter + plot_strength

        result1 = passes_plot_filter_v2(
            plot_group_id=plot_group_id,
            meta_group=meta_group,
            group_strength=group_strength,
            filter_challenge=filter_challenge,
            signage_point_index=5,
        )
        result2 = passes_plot_filter_v2(
            plot_group_id=plot_group_id,
            meta_group=meta_group,
            group_strength=group_strength,
            filter_challenge=filter_challenge,
            signage_point_index=5,
        )
        assert result1 == result2

    def test_passes_plot_filter_v2_changes_with_sp_index(self) -> None:
        """Test that different SP indices can give different results."""
        plot_group_id = bytes32.from_hexstr("0xabcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890")
        filter_challenge = bytes32.from_hexstr("0x1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef")
        meta_group = 42
        group_strength = 4  # Low strength so mask = 0xF (16 values)

        results = []
        for sp_index in range(16):
            result = passes_plot_filter_v2(
                plot_group_id=plot_group_id,
                meta_group=meta_group,
                group_strength=group_strength,
                filter_challenge=filter_challenge,
                signage_point_index=sp_index,
            )
            results.append(result)

        # With group_strength=4 (mask of 16 values), a plot should pass at exactly one
        # challenge_index in a window of 16, because there's exactly one target value
        # that matches (challenge_index ^ meta_group) & mask
        assert sum(results) == 1, f"Expected exactly 1 pass in window of 16, got {sum(results)}"

    def test_passes_plot_filter_v2_window_size(self) -> None:
        """Test that results repeat every window_size SP indices."""
        plot_group_id = bytes32.from_hexstr("0xabcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890")
        filter_challenge = bytes32.from_hexstr("0x1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef")
        meta_group = 42
        group_strength = 8

        # Test with default window_size=16
        for sp_index in range(16):
            result1 = passes_plot_filter_v2(
                plot_group_id=plot_group_id,
                meta_group=meta_group,
                group_strength=group_strength,
                filter_challenge=filter_challenge,
                signage_point_index=sp_index,
            )
            result2 = passes_plot_filter_v2(
                plot_group_id=plot_group_id,
                meta_group=meta_group,
                group_strength=group_strength,
                filter_challenge=filter_challenge,
                signage_point_index=sp_index + 16,  # Next window
            )
            assert result1 == result2, f"Results should match for SP indices {sp_index} and {sp_index + 16}"

    def test_passes_plot_filter_v2_meta_group_affects_pass_index(self) -> None:
        """Test that different meta_groups pass at different SP indices."""
        plot_group_id = bytes32.from_hexstr("0xabcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890")
        filter_challenge = bytes32.from_hexstr("0x1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef")
        group_strength = 4  # mask = 0xF

        # Find which SP index each meta_group passes at
        pass_indices: dict[int, int] = {}
        for meta_group in range(16):  # Only need 16 since mask is 0xF
            for sp_index in range(16):
                if passes_plot_filter_v2(
                    plot_group_id=plot_group_id,
                    meta_group=meta_group,
                    group_strength=group_strength,
                    filter_challenge=filter_challenge,
                    signage_point_index=sp_index,
                ):
                    pass_indices[meta_group] = sp_index
                    break

        # All 16 meta_groups should pass at different indices
        assert len(set(pass_indices.values())) == 16, "Each meta_group should pass at a unique SP index"

    def test_passes_plot_filter_v2_statistical(self, seeded_random: random.Random) -> None:
        """Test that filter passes at expected rate based on group_strength."""
        num_trials = 10000
        group_strength = 8  # 1/256 chance of passing per SP

        pass_count = 0
        for _ in range(num_trials):
            plot_group_id = bytes32.random(seeded_random)
            filter_challenge = bytes32.random(seeded_random)
            meta_group = seeded_random.randint(0, 255)
            sp_index = seeded_random.randint(0, 63)

            if passes_plot_filter_v2(
                plot_group_id=plot_group_id,
                meta_group=meta_group,
                group_strength=group_strength,
                filter_challenge=filter_challenge,
                signage_point_index=sp_index,
            ):
                pass_count += 1

        # Expected pass rate is 1/2^group_strength = 1/256
        expected_rate = 1 / (2**group_strength)
        actual_rate = pass_count / num_trials

        # Allow 50% variance for statistical test
        assert abs(actual_rate - expected_rate) < expected_rate * 0.5, (
            f"Expected pass rate ~{expected_rate:.4f}, got {actual_rate:.4f}"
        )


class TestComputePlotGroupId:
    """Tests for compute_plot_group_id_from_pos().

    Verified to match chia_rs compute_plot_id_v2 internals:
    plot_group_id = sha256(strength || plot_pk || pool_info)
    plot_id = sha256(plot_group_id || plot_index || meta_group)
    """

    def test_compute_plot_group_id_deterministic(self) -> None:
        plot_pk = _test_pk()
        pool_ph = bytes32.from_hexstr("0x" + "cd" * 32)

        pos = make_pos(
            challenge=bytes32.zeros,
            pool_public_key=None,
            pool_contract_puzzle_hash=pool_ph,
            plot_public_key=plot_pk,
            params=PlotParam.make_v2(0, 0, 2),
            proof=b"",
        )

        assert compute_plot_group_id_from_pos(pos) == compute_plot_group_id_from_pos(pos)

    def test_compute_plot_group_id_formula(self) -> None:
        plot_pk = _test_pk()
        pool_ph = bytes32.from_hexstr("0x" + "cd" * 32)
        strength = 3

        pos = make_pos(
            challenge=bytes32.zeros,
            pool_public_key=None,
            pool_contract_puzzle_hash=pool_ph,
            plot_public_key=plot_pk,
            params=PlotParam.make_v2(0, 0, strength),
            proof=b"",
        )

        result = compute_plot_group_id_from_pos(pos)
        expected = std_hash(bytes([strength]) + bytes(plot_pk) + bytes(pool_ph))
        assert result == expected

    def test_compute_plot_group_id_derives_plot_id(self) -> None:
        """Verify that sha256(group_id || plot_index || meta_group) == compute_plot_id."""
        plot_pk = _test_pk()
        pool_ph = bytes32.from_hexstr("0x" + "cd" * 32)

        pos = make_pos(
            challenge=bytes32.zeros,
            pool_public_key=None,
            pool_contract_puzzle_hash=pool_ph,
            plot_public_key=plot_pk,
            params=PlotParam.make_v2(7, 42, 3),
            proof=b"",
        )

        group_id = compute_plot_group_id_from_pos(pos)
        derived_plot_id = std_hash(group_id + (7).to_bytes(2, "big") + bytes([42]))
        assert derived_plot_id == pos.compute_plot_id()

    def test_compute_plot_group_id_different_strength(self) -> None:
        plot_pk = _test_pk()
        pool_ph = bytes32.from_hexstr("0x" + "cd" * 32)

        results = []
        for strength in [2, 3, 4, 5]:
            pos = make_pos(
                challenge=bytes32.zeros,
                pool_public_key=None,
                pool_contract_puzzle_hash=pool_ph,
                plot_public_key=plot_pk,
                params=PlotParam.make_v2(0, 0, strength),
                proof=b"",
            )
            results.append(compute_plot_group_id_from_pos(pos))

        assert len(set(results)) == 4, "Different strengths should produce different plot_group_ids"
