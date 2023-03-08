from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional, cast

from bitstring import BitArray
from blspy import AugSchemeMPL, G1Element, PrivateKey
from chiapos import Verifier

from chia.consensus.constants import ConsensusConstants
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.hash import std_hash
from chia.util.ints import uint8
from chia.util.streamable import Streamable, streamable

log = logging.getLogger(__name__)


@streamable
@dataclass(frozen=True)
class ProofOfSpace(Streamable):
    challenge: bytes32
    pool_public_key: Optional[G1Element]  # Only one of these two should be present
    pool_contract_puzzle_hash: Optional[bytes32]
    plot_public_key: G1Element
    size: uint8
    proof: bytes


def get_plot_id(pos: ProofOfSpace) -> bytes32:
    assert pos.pool_public_key is None or pos.pool_contract_puzzle_hash is None
    if pos.pool_public_key is None:
        assert pos.pool_contract_puzzle_hash is not None
        return calculate_plot_id_ph(pos.pool_contract_puzzle_hash, pos.plot_public_key)
    return calculate_plot_id_pk(pos.pool_public_key, pos.plot_public_key)


def verify_and_get_quality_string(
    pos: ProofOfSpace,
    constants: ConsensusConstants,
    original_challenge_hash: bytes32,
    signage_point: bytes32,
) -> Optional[bytes32]:
    # Exactly one of (pool_public_key, pool_contract_puzzle_hash) must not be None
    if (pos.pool_public_key is None) and (pos.pool_contract_puzzle_hash is None):
        log.error("Fail 1")
        return None
    if (pos.pool_public_key is not None) and (pos.pool_contract_puzzle_hash is not None):
        log.error("Fail 2")
        return None
    if pos.size < constants.MIN_PLOT_SIZE:
        log.error("Fail 3")
        return None
    if pos.size > constants.MAX_PLOT_SIZE:
        log.error("Fail 4")
        return None
    plot_id: bytes32 = get_plot_id(pos)
    new_challenge: bytes32 = calculate_pos_challenge(plot_id, original_challenge_hash, signage_point)

    if new_challenge != pos.challenge:
        log.error("New challenge is not challenge")
        return None

    if not passes_plot_filter(constants, plot_id, original_challenge_hash, signage_point):
        log.error("Fail 5")
        return None

    return get_quality_string(pos, plot_id)


def get_quality_string(pos: ProofOfSpace, plot_id: bytes32) -> Optional[bytes32]:
    quality_str = Verifier().validate_proof(plot_id, pos.size, pos.challenge, bytes(pos.proof))
    if not quality_str:
        return None
    return bytes32(quality_str)


def passes_plot_filter(
    constants: ConsensusConstants,
    plot_id: bytes32,
    challenge_hash: bytes32,
    signage_point: bytes32,
) -> bool:
    plot_filter = BitArray(calculate_plot_filter_input(plot_id, challenge_hash, signage_point))
    # TODO: compensating for https://github.com/scott-griffiths/bitstring/issues/248
    return cast(bool, plot_filter[: constants.NUMBER_ZERO_BITS_PLOT_FILTER].uint == 0)


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
