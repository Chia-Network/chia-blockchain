from src.util.cbor_message import cbor_message
from src.types.sized_bytes import bytes32
from src.util.ints import uint32, uint64
from src.types.proof_of_time import ProofOfTime

"""
Protocol between timelord and full node.
"""

"""
If don't have the unfinished block, ignore
Validate PoT
Call self.Block
"""
@cbor_message(tag=3000)
class ProofOfTimeFinished:
    proof: ProofOfTime


@cbor_message(tag=3001)
class ChallengeStart:
    challenge_hash: bytes32
    height: uint32


@cbor_message(tag=3002)
class ChallengeEnd:
    challenge_hash: bytes32


@cbor_message(tag=3003)
class ProofOfSpaceInfo:
    challenge_hash: bytes32
    iterations_needed: uint64
