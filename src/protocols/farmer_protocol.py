from dataclasses import dataclass
from typing import Optional

from blspy import G2Element
from src.types.proof_of_space import ProofOfSpace
from src.types.sized_bytes import bytes32
from src.types.pool_target import PoolTarget
from src.util.cbor_message import cbor_message
from src.util.ints import uint64, uint8

"""
Protocol between farmer and full node.
"""


@dataclass(frozen=True)
@cbor_message
class NewSignagePoint:
    challenge_hash: bytes32
    challenge_chain_sp: bytes32
    reward_chain_sp: bytes32
    difficulty: uint64
    sub_slot_iters: uint64
    signage_point_index: uint8


@dataclass(frozen=True)
@cbor_message
class DeclareProofOfSpace:
    challenge_hash: bytes32
    challenge_chain_sp: bytes32
    signage_point_index: uint8
    reward_chain_sp: bytes32
    proof_of_space: ProofOfSpace
    challenge_chain_sp_signature: G2Element
    reward_chain_sp_signature: G2Element
    farmer_puzzle_hash: bytes32
    pool_target: Optional[PoolTarget]
    pool_signature: Optional[G2Element]


@dataclass(frozen=True)
@cbor_message
class RequestSignedValues:
    quality_string: bytes32
    foliage_sub_block_hash: bytes32
    foliage_block_hash: bytes32


@dataclass(frozen=True)
@cbor_message
class SignedValues:
    quality_string: bytes32
    foliage_sub_block_signature: G2Element
    foliage_block_signature: G2Element
