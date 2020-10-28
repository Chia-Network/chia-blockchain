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
class InfusionChallengePoint:
    challenge_hash: bytes32
    challenge_chain_icp: bytes32
    reward_chain_icp: bytes32  # TODO(mariano): update bram
    difficulty: uint64
    index: uint64  # TODO(mariano): what is this for?
    ips: uint64


@dataclass(frozen=True)
@cbor_message
class DeclareProofOfSpace:
    challenge_point_hash: bytes32
    quality_string: bytes32
    challenge_chain_icp_sig: G2Element
    reward_chain_icp_sig: G2Element


@dataclass(frozen=True)
@cbor_message
class RequestSignedValues:
    quality_string: bytes32
    reward_block_hash: bytes32
    transaction_block_hash: bytes32


@dataclass(frozen=True)
@cbor_message
class SignedValues:
    quality_string: bytes32
    proof_of_space: ProofOfSpace
    farmer_puzzle_hash: bytes32
    pool_target: PoolTarget
    pool_signature: G2Element
    foliage_signature: G2Element
    transaction_block_signature: G2Element
