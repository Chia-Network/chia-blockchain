from dataclasses import dataclass

from blspy import PrependSignature, PublicKey

from src.types.proof_of_space import ProofOfSpace
from src.types.sized_bytes import bytes32
from src.util.cbor_message import cbor_message
from src.util.ints import uint8
from src.util.streamable import List


"""
Protocol between harvester and farmer.
"""


@dataclass(frozen=True)
@cbor_message
class HarvesterHandshake:
    pool_pubkeys: List[PublicKey]


@dataclass(frozen=True)
@cbor_message
class NewChallenge:
    challenge_hash: bytes32


@dataclass(frozen=True)
@cbor_message
class ChallengeResponse:
    challenge_hash: bytes32
    quality_string: bytes32
    plot_size: uint8


@dataclass(frozen=True)
@cbor_message
class RequestProofOfSpace:
    quality_string: bytes32


@dataclass(frozen=True)
@cbor_message
class RespondProofOfSpace:
    quality_string: bytes32
    proof: ProofOfSpace


@dataclass(frozen=True)
@cbor_message
class RequestHeaderSignature:
    quality_string: bytes32
    header_hash: bytes32


@dataclass(frozen=True)
@cbor_message
class RespondHeaderSignature:
    quality_string: bytes32
    header_hash_signature: PrependSignature


@dataclass(frozen=True)
@cbor_message
class RequestPartialProof:
    quality_string: bytes32
    farmer_target_hash: bytes32


@dataclass(frozen=True)
@cbor_message
class RespondPartialProof:
    quality_string: bytes32
    farmer_target_signature: PrependSignature
