from src.util.streamable import streamable, StreamableList
from src.types.sized_bytes import bytes32
from src.types.classgroup import ClassgroupElement
from src.util.ints import uint8, uint64


@streamable
class ProofOfTimeOutput:
    challenge_hash: bytes32
    number_of_iterations: uint64
    output: ClassgroupElement


@streamable
class ProofOfTime:
    output: ProofOfTimeOutput
    witness_type: uint8
    witness: StreamableList(ClassgroupElement)
