from __future__ import annotations

import logging
from typing import cast

from bitstring import BitArray
from chia_rs import AugSchemeMPL, ConsensusConstants, G1Element, PlotParam, PrivateKey, ProofOfSpace, validate_proof_v2
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint8, uint16, uint32
from chiapos import Verifier

from chia.util.hash import std_hash

log = logging.getLogger(__name__)


def make_pos(
    challenge: bytes32,
    pool_public_key: G1Element | None,
    pool_contract_puzzle_hash: bytes32 | None,
    plot_public_key: G1Element,
    params: PlotParam,
    proof: bytes,
) -> ProofOfSpace:
    k: int
    if params.size_v1 is not None:
        version = 0
        plot_index = 0
        meta_group = 0
        strength = 0
        k = params.size_v1
    else:
        version = 1
        assert params.strength_v2 is not None
        plot_index = params.plot_index
        meta_group = params.meta_group
        strength = params.strength_v2
        k = 0

    return ProofOfSpace(
        challenge,
        pool_public_key,
        pool_contract_puzzle_hash,
        plot_public_key,
        uint8(version),
        uint16(plot_index),
        uint8(meta_group),
        uint8(strength),
        uint8(k),
        proof,
    )


def check_plot_param(constants: ConsensusConstants, ps: PlotParam) -> bool:
    size_v1 = ps.size_v1
    strength_v2 = ps.strength_v2
    if strength_v2 is not None:
        if strength_v2 < constants.MIN_PLOT_STRENGTH:
            log.error(f"Plot strength ({strength_v2}) is lower than the minimum ({constants.MIN_PLOT_STRENGTH})")
            return False
        if strength_v2 > constants.MAX_PLOT_STRENGTH:
            log.error(f"Plot strength ({strength_v2}) is too high (max is {constants.MAX_PLOT_STRENGTH})")
            return False
        return True

    assert size_v1 is not None
    if size_v1 < constants.MIN_PLOT_SIZE_V1:
        log.error(f"Plot size ({size_v1}) is lower than the minimum ({constants.MIN_PLOT_SIZE_V1})")
        return False
    if size_v1 > constants.MAX_PLOT_SIZE_V1:
        log.error(f"Plot size ({size_v1}) is higher than the maximum ({constants.MAX_PLOT_SIZE_V1})")
        return False
    return True


def num_phase_out_epochs(constants: ConsensusConstants) -> int:
    """
    The number of phase-out epochs is always a power-of-two minus 1. i.e. it
    will also be a mask for the hash of the proof we're checking for phase-out.
    Since the hash of the proof are random bits, the simplest check is just to
    mask and compare the resulting value against the phase-out count down.
    """
    return (1 << constants.PLOT_V1_PHASE_OUT_EPOCH_BITS) - 1


def v1_cut_off_height(constants: ConsensusConstants) -> int:
    """
    returns the height where v1 proofs-of-space are no longer valid. Blocks
    whose previous transaction block is equal to or higher than this may not have a
    v1 proof.
    """
    return constants.HARD_FORK2_HEIGHT + num_phase_out_epochs(constants) * constants.EPOCH_BLOCKS


def is_v1_phased_out(
    proof: bytes,
    prev_transaction_block_height: uint32,  # this is the height of the last tx block before the current block SP
    constants: ConsensusConstants,
) -> bool:
    if prev_transaction_block_height < constants.HARD_FORK2_HEIGHT:
        return False

    # This is a v1 plot and the phase-out period has started
    # The probability of having been phased out is proportional on the
    # number of epochs since hard fork activation
    phase_out_epoch_mask = num_phase_out_epochs(constants)

    # we just look at one byte so the mask can't be bigger than that
    assert phase_out_epoch_mask < 256

    # this counter is counting down to zero
    epoch_counter = (v1_cut_off_height(constants) - prev_transaction_block_height) // constants.EPOCH_BLOCKS

    # if we're past the phase-out, v1 plots are unconditionally invalid
    if epoch_counter < 0:
        return True

    proof_value = std_hash(proof + b"chia proof-of-space v1 phase-out")[0] & phase_out_epoch_mask
    return proof_value >= epoch_counter


def compute_plot_group_id(strength: int, plot_public_key: G1Element, pool_info: G1Element | bytes32) -> bytes32:
    """
    Compute plot_group_id for V2 filter.
    Formula: sha256(strength || plot_pk || pool_info)
    Verified to match chia_rs compute_plot_id_v2 internals.
    """
    return std_hash(bytes([strength]) + bytes(plot_public_key) + bytes(pool_info))


def compute_plot_group_id_from_pos(pos: ProofOfSpace) -> bytes32:
    pool_info = pos.pool_contract_puzzle_hash if pos.pool_contract_puzzle_hash else pos.pool_public_key
    assert pool_info is not None
    return compute_plot_group_id(pos.strength, pos.plot_public_key, pool_info)


def verify_and_get_quality_string(
    pos: ProofOfSpace,
    constants: ConsensusConstants,
    original_challenge_hash: bytes32,
    signage_point: bytes32,
    *,
    height: uint32,
    prev_transaction_block_height: uint32,  # this is the height of the last tx block before the current block SP
    height_agnostic: bool = False,
    filter_challenge: bytes32 | None = None,  # For V2 plot filter
    signage_point_index: int | None = None,  # For V2 plot filter
) -> bytes32 | None:
    plot_param = pos.param()

    if not height_agnostic:
        if plot_param.size_v1 is not None and is_v1_phased_out(pos.proof, prev_transaction_block_height, constants):
            log.info("v1 proof has been phased-out and is no longer valid")
            return None

        if plot_param.strength_v2 is not None and prev_transaction_block_height < constants.HARD_FORK2_HEIGHT:
            log.info("v2 proof support has not yet activated")
            return None

    # Exactly one of (pool_public_key, pool_contract_puzzle_hash) must not be None
    if (pos.pool_public_key is None) and (pos.pool_contract_puzzle_hash is None):
        log.error("Expected pool public key or pool contract puzzle hash but got neither")
        return None
    if (pos.pool_public_key is not None) and (pos.pool_contract_puzzle_hash is not None):
        log.error("Expected pool public key or pool contract puzzle hash but got both")
        return None

    if not check_plot_param(constants, plot_param):
        return None

    if plot_param.strength_v2 is not None and not height_agnostic:
        max_strength = calculate_max_plot_strength(height, constants.HARD_FORK2_HEIGHT)
        if plot_param.strength_v2 > max_strength:
            log.error(f"Plot strength ({plot_param.strength_v2}) exceeds max ({max_strength}) at height {height}")
            return None

    plot_id: bytes32 = pos.compute_plot_id()
    new_challenge: bytes32 = calculate_pos_challenge(plot_id, original_challenge_hash, signage_point)

    if new_challenge != pos.challenge:
        log.error(f"Calculated pos challenge doesn't match the provided one {new_challenge}")
        return None

    if plot_param.strength_v2 is not None:
        # V2 plots always use the predictable filter — no fallback to prefix-bits
        if filter_challenge is None or signage_point_index is None:
            log.error("V2 plot requires filter_challenge and signage_point_index")
            return None
        plot_group_id = compute_plot_group_id_from_pos(pos)
        group_strength = calculate_base_plot_filter_bits(height, constants.HARD_FORK2_HEIGHT) + plot_param.strength_v2

        if not passes_plot_filter_v2(
            plot_group_id, pos.meta_group, group_strength, filter_challenge, signage_point_index
        ):
            log.error(f"Did not pass the V2 plot filter. group_strength: {group_strength}")
            return None
    else:
        # V1 plots use the original prefix-bits filter
        prefix_bits = calculate_prefix_bits(constants, height, plot_param)
        if not passes_plot_filter(prefix_bits, plot_id, original_challenge_hash, signage_point):
            log.error(f"Did not pass the plot filter. prefix bits: {prefix_bits}")
            return None

    if plot_param.size_v1 is not None:
        # === V1 plots ===
        assert plot_param.strength_v2 is None

        if not height_agnostic and prev_transaction_block_height >= constants.SOFT_FORK9_HEIGHT:
            if len(pos.proof) >= 2000:
                log.error(f"Proof of space too large: {len(pos.proof)} bytes")
                return None

        quality_str = Verifier().validate_proof(plot_id, plot_param.size_v1, pos.challenge, bytes(pos.proof))
        if not quality_str:
            return None
        return bytes32(quality_str)
    else:
        # === V2 plots ===
        assert plot_param.strength_v2 is not None

        return validate_proof_v2(
            plot_id,
            constants.PLOT_SIZE_V2,
            pos.challenge,
            plot_param.strength_v2,
            pos.proof,
        )


def passes_plot_filter(
    prefix_bits: int,
    plot_id: bytes32,
    challenge_hash: bytes32,
    signage_point: bytes32,
) -> bool:
    # this is possible when using non-mainnet constants with a low
    # NUMBER_ZERO_BITS_PLOT_FILTER constant and activating sufficient plot
    # filter reductions
    if prefix_bits == 0:
        return True

    plot_filter = BitArray(calculate_plot_filter_input(plot_id, challenge_hash, signage_point))
    # TODO: compensating for https://github.com/scott-griffiths/bitstring/issues/248
    return cast(bool, plot_filter[:prefix_bits].uint == 0)


def calculate_prefix_bits(constants: ConsensusConstants, height: uint32, plot_param: PlotParam) -> int:
    assert plot_param.strength_v2 is None, "V2 plots use the predictable filter, not prefix bits"

    prefix_bits = int(constants.NUMBER_ZERO_BITS_PLOT_FILTER_V1)
    if height >= constants.PLOT_FILTER_32_HEIGHT:
        prefix_bits -= 4
    elif height >= constants.PLOT_FILTER_64_HEIGHT:
        prefix_bits -= 3
    elif height >= constants.PLOT_FILTER_128_HEIGHT:
        prefix_bits -= 2
    elif height >= constants.HARD_FORK_HEIGHT:
        prefix_bits -= 1

    return max(0, prefix_bits)


def calculate_plot_filter_input(plot_id: bytes32, challenge_hash: bytes32, signage_point: bytes32) -> bytes32:
    return std_hash(plot_id + challenge_hash + signage_point)


# V2 Plot Filter Constants
# TODO: Move to ConsensusConstants in chia_rs
FILTER_SP_LOOKBACK: int = 4  # SPs before window start to sample filter_challenge
FILTER_WINDOW_SIZE: int = 16  # SPs per filter window (64 SPs / 4 windows)

# Base plot filter reduction schedule — offsets from HARD_FORK2_HEIGHT
# Starts at 9 bits (512), reduces every 3-6 years until 0 bits (1)
_BASE_FILTER_OFFSETS: list[tuple[int, int]] = [
    (50_494_000, 0),  # +~31 years
    (45_444_000, 1),  # +~28 years
    (40_394_000, 2),  # +~25 years
    (35_343_000, 3),  # +~21 years
    (30_298_000, 4),  # +~18 years
    (25_247_000, 5),  # +~15 years
    (20_197_000, 6),  # +~12 years
    (15_146_000, 7),  # +~9 years
    (10_101_000, 8),  # +~6 years
    (0, 9),  # at hard fork
]


def calculate_max_plot_strength(height: uint32, hard_fork2_height: int) -> int:
    return 17 - calculate_base_plot_filter_bits(height, hard_fork2_height)


def calculate_base_plot_filter_bits(height: uint32, hard_fork2_height: int) -> int:
    relative_height = int(height) - hard_fork2_height
    if relative_height < 0:
        return 9
    for offset, bits in _BASE_FILTER_OFFSETS:
        if relative_height >= offset:
            return bits
    return 9


def passes_plot_filter_v2(
    plot_group_id: bytes32,
    meta_group: int,
    group_strength: int,
    filter_challenge: bytes32,
    signage_point_index: int,
    window_size: int = FILTER_WINDOW_SIZE,
) -> bool:
    """
    V2 plot filter - predictable passage.

    passes = (effective_filter == target)
    Where:
        effective_filter = hash(plot_group_id + filter_challenge)[:4] & mask
        target = (challenge_index ^ meta_group) & mask
        mask = (1 << group_strength) - 1
    """
    challenge_index = signage_point_index % window_size
    mask = (1 << group_strength) - 1
    effective_filter = int.from_bytes(std_hash(plot_group_id + filter_challenge)[:4], "big") & mask
    target = (challenge_index ^ meta_group) & mask
    return effective_filter == target


def calculate_pos_challenge(plot_id: bytes32, challenge_hash: bytes32, signage_point: bytes32) -> bytes32:
    return std_hash(calculate_plot_filter_input(plot_id, challenge_hash, signage_point))


def calculate_plot_id_pk(
    pool_public_key: G1Element,
    plot_public_key: G1Element,
) -> bytes32:
    return std_hash(bytes(pool_public_key) + bytes(plot_public_key))


def calculate_plot_id_ph(
    pool_contract_puzzle_hash: bytes32,
    plot_public_key: G1Element,
) -> bytes32:
    return std_hash(bytes(pool_contract_puzzle_hash) + bytes(plot_public_key))


def generate_taproot_sk(local_pk: G1Element, farmer_pk: G1Element) -> PrivateKey:
    taproot_message: bytes = bytes(local_pk + farmer_pk) + bytes(local_pk) + bytes(farmer_pk)
    taproot_hash: bytes32 = std_hash(taproot_message)
    return AugSchemeMPL.key_gen(taproot_hash)


def generate_plot_public_key(local_pk: G1Element, farmer_pk: G1Element, include_taproot: bool = False) -> G1Element:
    if include_taproot:
        taproot_sk: PrivateKey = generate_taproot_sk(local_pk, farmer_pk)
        return local_pk + farmer_pk + taproot_sk.get_g1()
    else:
        return local_pk + farmer_pk
