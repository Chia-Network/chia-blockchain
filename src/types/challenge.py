from ..util.streamable import streamable
from .sized_bytes import bytes32


@streamable
class Challenge:
    proof_of_time_output_hash: bytes32
    proof_of_space_hash: bytes32
    height: int
    total_weight: int
