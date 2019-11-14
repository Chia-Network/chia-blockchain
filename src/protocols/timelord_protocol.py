from src.util.cbor_message import cbor_message
from src.types.sized_bytes import bytes32
from src.util.ints import uint64
from src.types.proof_of_time import ProofOfTime
from dataclasses import dataclass

"""
Protocol between timelord and full node.
"""

"""
If don't have the unfinished block, ignore
Validate PoT
Call self.Block
"""
@dataclass(frozen=True)
@cbor_message
class ProofOfTimeFinished:
    proof: ProofOfTime


@dataclass(frozen=True)
@cbor_message
class ChallengeStart:
    challenge_hash: bytes32
    weight: uint64


@dataclass(frozen=True)
@cbor_message
class ProofOfSpaceInfo:
    challenge_hash: bytes32
    iterations_needed: uint64
