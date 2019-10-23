from src.util.streamable import streamable, Streamable
from src.types.sized_bytes import bytes32
from src.util.ints import uint32, uint64
from dataclasses import dataclass


@dataclass(frozen=True)
@streamable
class Challenge(Streamable):
    proof_of_space_hash: bytes32
    proof_of_time_output_hash: bytes32
    height: uint32
    total_weight: uint64  # Total weight up to this point, counting this one
    total_iters: uint64  # Total iterations done up to this point, counting new PoT
