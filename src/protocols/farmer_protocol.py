from blspy import PrependSignature
from src.util.cbor_message import cbor_message
from src.types.sized_bytes import bytes32
from src.util.ints import uint64, uint32
from src.types.proof_of_space import ProofOfSpace
from src.types.coinbase import CoinbaseInfo
from dataclasses import dataclass

"""
Protocol between farmer and full node.
"""


@dataclass(frozen=True)
@cbor_message(tag=2000)
class ProofOfSpaceFinalized:
    challenge_hash: bytes32
    height: uint32
    quality: bytes32
    difficulty: uint64


@dataclass(frozen=True)
@cbor_message(tag=2001)
class ProofOfSpaceArrived:
    height: uint32
    quality: bytes32


@dataclass(frozen=True)
@cbor_message(tag=2002)
class DeepReorgNotification:
    pass


@dataclass(frozen=True)
@cbor_message(tag=2003)
class RequestHeaderHash:
    challenge_hash: bytes32
    coinbase: CoinbaseInfo
    coinbase_signature: PrependSignature
    fees_target_puzzle_hash: bytes32
    proof_of_space: ProofOfSpace


@dataclass(frozen=True)
@cbor_message(tag=2004)
class HeaderHash:
    pos_hash: bytes32
    header_hash: bytes32


@dataclass(frozen=True)
@cbor_message(tag=2005)
class HeaderSignature:
    pos_hash: bytes32
    header_hash: bytes32
    header_signature: PrependSignature


@dataclass(frozen=True)
@cbor_message(tag=2006)
class ProofOfTimeRate:
    pot_estimate_ips: uint64

