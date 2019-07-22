from ..util.streamable import streamable
from .sized_bytes import bytes32
from .classgroup import ClassgroupElement


@streamable
class ProofOfTimeOutput:
    challenge_hash: bytes32
    number_of_iterations: int
    output: ClassgroupElement
