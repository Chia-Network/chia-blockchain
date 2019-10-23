from typing import List
from dataclasses import dataclass
from src.types.sized_bytes import bytes32
from src.util.streamable import streamable, Streamable
from src.types.classgroup import ClassgroupElement
from src.util.ints import uint8, uint64
from lib.chiavdf.inkfish.proof_of_time import check_proof_of_time_nwesolowski
from lib.chiavdf.inkfish.create_discriminant import create_discriminant
from lib.chiavdf.inkfish.classgroup import ClassGroup


@dataclass(frozen=True)
@streamable
class ProofOfTimeOutput(Streamable):
    challenge_hash: bytes32
    number_of_iterations: uint64
    output: ClassgroupElement


@dataclass(frozen=True)
@streamable
class ProofOfTime(Streamable):
    output: ProofOfTimeOutput
    witness_type: uint8
    witness: List[uint8]

    def is_valid(self, discriminant_size_bits):
        disc: int = create_discriminant(self.output.challenge_hash,
                                        discriminant_size_bits)
        x = ClassGroup.from_ab_discriminant(2, 1, disc)
        y = ClassGroup.from_ab_discriminant(self.output.output.a,
                                            self.output.output.b, disc)
        return check_proof_of_time_nwesolowski(disc, x, y.serialize() + bytes(self.witness),
                                               self.output.number_of_iterations,
                                               discriminant_size_bits,
                                               self.witness_type)
