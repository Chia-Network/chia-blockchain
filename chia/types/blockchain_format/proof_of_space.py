from __future__ import annotations

import logging
from typing import Optional, cast

from bitstring import BitArray
from chia_rs import AugSchemeMPL, ConsensusConstants, G1Element, PlotSize, PrivateKey, ProofOfSpace, validate_proof_v2
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint8, uint32
from chiapos import Verifier

from chia.util.hash import std_hash

log = logging.getLogger(__name__)


def make_pos(
    challenge: bytes32,
    pool_public_key: Optional[G1Element],
    pool_contract_puzzle_hash: Optional[bytes32],
    plot_public_key: G1Element,
    version_and_size: PlotSize,
    proof: bytes,
) -> ProofOfSpace:
    k: int
    if version_and_size.size_v1 is not None:
        k = version_and_size.size_v1
    else:
        assert version_and_size.size_v2 is not None
        k = version_and_size.size_v2
        assert k is not None
        k |= 0x80

    return ProofOfSpace(
        challenge,
        pool_public_key,
        pool_contract_puzzle_hash,
        plot_public_key,
        uint8(k),
        proof,
    )


def get_plot_id(pos: ProofOfSpace) -> bytes32:
    assert pos.pool_public_key is None or pos.pool_contract_puzzle_hash is None
    if pos.pool_public_key is None:
        assert pos.pool_contract_puzzle_hash is not None
        return calculate_plot_id_ph(pos.pool_contract_puzzle_hash, pos.plot_public_key)
    return calculate_plot_id_pk(pos.pool_public_key, pos.plot_public_key)


def check_plot_size(constants: ConsensusConstants, ps: PlotSize) -> bool:
    size_v1 = ps.size_v1
    if size_v1 is not None:
        assert ps.size_v2 is None
        if size_v1 < constants.MIN_PLOT_SIZE_V1:
            log.error(f"Plot size ({size_v1}) is lower than the minimum ({constants.MIN_PLOT_SIZE_V1})")
            return False
        if size_v1 > constants.MAX_PLOT_SIZE_V1:
            log.error(f"Plot size ({size_v1}) is higher than the maximum ({constants.MAX_PLOT_SIZE_V1})")
            return False
        return True

    size_v2 = ps.size_v2
    assert size_v2 is not None
    if size_v2 < constants.MIN_PLOT_SIZE_V2:
        log.error(f"Plot size ({size_v2}) is lower than the minimum ({constants.MIN_PLOT_SIZE_V2})")
        return False
    if size_v2 > constants.MAX_PLOT_SIZE_V2:
        log.error(f"Plot size ({size_v2}) is higher than the maximum ({constants.MAX_PLOT_SIZE_V2})")
        return False
    if (size_v2 & 1) == 1:
        log.error("Plot size is odd")
        return False
    return True


def verify_and_get_quality_string(
    pos: ProofOfSpace,
    constants: ConsensusConstants,
    original_challenge_hash: bytes32,
    signage_point: bytes32,
    *,
    height: uint32,
) -> Optional[bytes32]:
    # Exactly one of (pool_public_key, pool_contract_puzzle_hash) must not be None
    if (pos.pool_public_key is None) and (pos.pool_contract_puzzle_hash is None):
        log.error("Expected pool public key or pool contract puzzle hash but got neither")
        return None
    if (pos.pool_public_key is not None) and (pos.pool_contract_puzzle_hash is not None):
        log.error("Expected pool public key or pool contract puzzle hash but got both")
        return None

    plot_size = pos.size()
    if not check_plot_size(constants, plot_size):
        return None

    plot_id: bytes32 = get_plot_id(pos)
    new_challenge: bytes32 = calculate_pos_challenge(plot_id, original_challenge_hash, signage_point)

    if new_challenge != pos.challenge:
        log.error(f"Calculated pos challenge doesn't match the provided one {new_challenge}")
        return None

    # we use different plot filter prefix sizes depending on v1 or v2 plots
    prefix_bits = calculate_prefix_bits(constants, height, plot_size)
    if not passes_plot_filter(prefix_bits, plot_id, original_challenge_hash, signage_point):
        log.error("Did not pass the plot filter")
        return None

    if plot_size.size_v1 is not None:
        # === V1 plots ===
        assert plot_size.size_v2 is None

        quality_str = Verifier().validate_proof(plot_id, plot_size.size_v1, pos.challenge, bytes(pos.proof))
        if not quality_str:
            return None
        return bytes32(quality_str)
    else:
        # === V2 plots ===
        assert plot_size.size_v2 is not None

        return validate_proof_v2(
            plot_id,
            plot_size.size_v2,
            pos.challenge,
            constants.PLOT_STRENGTH_INITIAL,
            constants.QUALITY_PROOF_SCAN_FILTER,
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


def calculate_prefix_bits(constants: ConsensusConstants, height: uint32, plot_size: PlotSize) -> int:
    if plot_size.size_v2 is not None:
        if height >= constants.PLOT_FILTER_V2_THIRD_ADJUSTMENT_HEIGHT:
            return constants.NUMBER_ZERO_BITS_PLOT_FILTER_V2 + 3
        if height >= constants.PLOT_FILTER_V2_SECOND_ADJUSTMENT_HEIGHT:
            return constants.NUMBER_ZERO_BITS_PLOT_FILTER_V2 + 2
        if height >= constants.PLOT_FILTER_V2_FIRST_ADJUSTMENT_HEIGHT:
            return constants.NUMBER_ZERO_BITS_PLOT_FILTER_V2 + 1
        return constants.NUMBER_ZERO_BITS_PLOT_FILTER_V2

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
