from dataclasses import dataclass
from blspy import G2Element
from src.types.proof_of_space import ProofOfSpace
from src.types.sized_bytes import bytes32
from src.types.pool_target import PoolTarget
from src.util.cbor_message import cbor_message
from src.util.ints import uint32, uint64, uint128


"""
Protocol between farmer and full node.
"""


@dataclass(frozen=True)
@cbor_message
class ProofOfSpaceFinalized:
    challenge_hash: bytes32
    height: uint32
    weight: uint128
    difficulty: uint64


@dataclass(frozen=True)
@cbor_message
class ProofOfSpaceArrived:
    previous_challenge_hash: bytes32
    weight: uint128
    quality_string: bytes32


@dataclass(frozen=True)
@cbor_message
class RequestHeaderHash:
    challenge_hash: bytes32
    proof_of_space: ProofOfSpace
    pool_target: PoolTarget
    pool_target_signature: G2Element
    farmer_rewards_puzzle_hash: bytes32


@dataclass(frozen=True)
@cbor_message
class HeaderHash:
    pos_hash: bytes32
    header_hash: bytes32


@dataclass(frozen=True)
@cbor_message
class HeaderSignature:
    pos_hash: bytes32
    header_hash: bytes32
    header_signature: G2Element


@dataclass(frozen=True)
@cbor_message
class ProofOfTimeRate:
    pot_estimate_ips: uint64
