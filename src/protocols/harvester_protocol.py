from dataclasses import dataclass
from typing import List, Tuple

from blspy import G1Element, G2Element

from src.types.proof_of_space import ProofOfSpace
from src.types.sized_bytes import bytes32
from src.util.cbor_message import cbor_message
from src.util.ints import uint64

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
    difficulty: uint64
    slot_iterations: uint64


@dataclass(frozen=True)
@cbor_message
class ChallengeResponse:
    plot_identifier: str
    proof: ProofOfSpace


@dataclass(frozen=True)
@cbor_message
class RequestSignatures:
    plot_identifier: str
    challenge_hash: bytes32
    messages: List[bytes32]


@dataclass(frozen=True)
@cbor_message
class RespondSignatures:
    plot_identifier: str
    challenge_hash: bytes32
    local_pk: G1Element
    farmer_pk: G1Element
    message_signatures: List[Tuple[bytes32, G2Element]]
