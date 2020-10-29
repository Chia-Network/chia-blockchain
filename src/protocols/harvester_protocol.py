from dataclasses import dataclass
from typing import List, Tuple

from blspy import G1Element, G2Element

from src.types.proof_of_space import ProofOfSpace
from src.types.sized_bytes import bytes32
from src.util.cbor_message import cbor_message


"""
Protocol between harvester and farmer.
"""


@dataclass(frozen=True)
@cbor_message
class HarvesterHandshake:
    farmer_public_keys: List[G1Element]
    pool_public_keys: List[G1Element]


@dataclass(frozen=True)
@cbor_message
class NewChallenge:
    challenge_hash: bytes32


@dataclass(frozen=True)
@cbor_message
class ChallengeResponse:
    challenge_hash: bytes32
    plot_id: str
    proof: ProofOfSpace


@dataclass(frozen=True)
@cbor_message
class RequestSignatures:
    plot_id: str
    challenge_hash: bytes32
    messages: List[bytes32]


@dataclass(frozen=True)
@cbor_message
class RespondSignatures:
    plot_id: str
    challenge_hash: bytes32
    local_pk: G1Element
    farmer_pk: G1Element
    message_signatures: List[Tuple[bytes32, G2Element]]
