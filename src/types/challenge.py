from src.util.streamable import streamable
from src.types.sized_bytes import bytes32
from src.util.ints import uint32, uint64


@streamable
class Challenge:
    proof_of_space_hash: bytes32
    proof_of_time_output_hash: bytes32
    height: uint32
    total_weight: uint64
    total_iters: uint64
