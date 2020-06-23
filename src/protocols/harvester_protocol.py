from dataclasses import dataclass
from typing import List, Tuple

from blspy import PrependSignature, PublicKey, InsecureSignature

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
    farmer_pubkeys: List[PublicKey]


@dataclass(frozen=True)
@cbor_message
class NewChallenge:
    challenge_hash: bytes32
    farmer_challenge_signatures: List[Tuple[PublicKey, InsecureSignature]]


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
    harvester_pk: PublicKey
    proof_of_possession: PrependSignature


@dataclass(frozen=True)
@cbor_message
class RequestSignature:
    challenge_hash: bytes32
    plot_id: str
    response_number: uint8
    message: bytes32


@dataclass(frozen=True)
@cbor_message
class RespondSignature:
    challenge_hash: bytes32
    plot_id: str
    response_number: uint8
    message_signature: InsecureSignature
