from dataclasses import dataclass
from blspy import PrependSignature
from src.types.coin import Coin
from src.types.BLSSignature import BLSSignature
from src.types.proof_of_space import ProofOfSpace
from src.types.sized_bytes import bytes32
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
    coinbase: Coin
    coinbase_signature: BLSSignature
    fees_target_puzzle_hash: bytes32
    proof_of_space: ProofOfSpace


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
    header_signature: PrependSignature


@dataclass(frozen=True)
@cbor_message
class ProofOfTimeRate:
    pot_estimate_ips: uint64
