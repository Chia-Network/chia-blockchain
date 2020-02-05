from dataclasses import dataclass

from src.types.sized_bytes import bytes32
from src.util.ints import uint64
from src.util.streamable import Streamable, streamable


@dataclass(frozen=True)
@streamable
class Challenge(Streamable):
    prev_challenge_hash: bytes32
    proof_of_space_hash: bytes32
    proof_of_time_output_hash: bytes32
    total_weight: uint64  # Total weight up to this point, counting this one
    total_iters: uint64  # Total iterations done up to this point, counting new PoT
