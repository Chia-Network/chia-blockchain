from blspy import PublicKey, PrependSignature
from src.util.cbor_message import cbor_message
from src.util.streamable import List
from src.types.sized_bytes import bytes32
from src.types.proof_of_space import ProofOfSpace
from src.util.ints import uint8
from dataclasses import dataclass

"""
Protocol between plotter and farmer.
"""


@dataclass(frozen=True)
@cbor_message
class PlotterHandshake:
    pool_pubkeys: List[PublicKey]


@dataclass(frozen=True)
@cbor_message
class NewChallenge:
    challenge_hash: bytes32


@dataclass(frozen=True)
@cbor_message
class ChallengeResponse:
    challenge_hash: bytes32
    quality: bytes32
    plot_size: uint8


@dataclass(frozen=True)
@cbor_message
class RequestProofOfSpace:
    quality: bytes32


@dataclass(frozen=True)
@cbor_message
class RespondProofOfSpace:
    quality: bytes32
    proof: ProofOfSpace


@dataclass(frozen=True)
@cbor_message
class RequestHeaderSignature:
    quality: bytes32
    header_hash: bytes32


@dataclass(frozen=True)
@cbor_message
class RespondHeaderSignature:
    quality: bytes32
    header_hash_signature: PrependSignature


@dataclass(frozen=True)
@cbor_message
class RequestPartialProof:
    quality: bytes32
    farmer_target_hash: bytes32


@dataclass(frozen=True)
@cbor_message
class RespondPartialProof:
    quality: bytes32
    farmer_target_signature: PrependSignature
