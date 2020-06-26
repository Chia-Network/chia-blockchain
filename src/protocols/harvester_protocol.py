from dataclasses import dataclass
from typing import List

from blspy import PublicKey, InsecureSignature

from src.types.proof_of_space import ProofOfSpace
from src.types.sized_bytes import bytes32
from src.util.cbor_message import cbor_message
from src.util.ints import uint8


"""
Protocol between harvester and farmer.
"""


@dataclass(frozen=True)
@cbor_message
class HarvesterHandshake:
    farmer_public_keys: List[PublicKey]
    pool_public_keys: List[PublicKey]


@dataclass(frozen=True)
@cbor_message
class NewChallenge:
    challenge_hash: bytes32


@dataclass(frozen=True)
@cbor_message
class ChallengeResponse:
    challenge_hash: bytes32
    plot_id: str
    response_number: uint8
    quality_string: bytes32
    plot_size: uint8


@dataclass(frozen=True)
@cbor_message
class RequestProofOfSpace:
    challenge_hash: bytes32
    plot_id: str
    response_number: uint8


@dataclass(frozen=True)
@cbor_message
class RespondProofOfSpace:
    plot_id: str
    response_number: uint8
    proof: ProofOfSpace


@dataclass(frozen=True)
@cbor_message
class RequestSignature:
    plot_id: str
    message: bytes32


@dataclass(frozen=True)
@cbor_message
class RespondSignature:
    plot_id: str
    message: bytes32
    harvester_pk: PublicKey
    farmer_pk: PublicKey
    message_signature: InsecureSignature
