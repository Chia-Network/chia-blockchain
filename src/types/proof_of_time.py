from dataclasses import dataclass

from chiavdf import create_discriminant
from src.types.classgroup import ClassgroupElement
from src.types.sized_bytes import bytes32
from src.util.classgroup_utils import ClassGroup, check_proof_of_time_nwesolowski
from src.util.ints import uint8, uint64
from src.util.streamable import Streamable, streamable


@dataclass(frozen=True)
@streamable
class ProofOfTime(Streamable):
    challenge_hash: bytes32
    number_of_iterations: uint64
    output: ClassgroupElement
    witness_type: uint8
    witness: bytes

    def is_valid(self, discriminant_size_bits):
        try:
            disc: int = int(
                create_discriminant(self.challenge_hash, discriminant_size_bits), 16,
            )
            x = ClassGroup.from_ab_discriminant(2, 1, disc)
            y = ClassGroup.from_ab_discriminant(self.output.a, self.output.b, disc)
        except Exception:
            return False
        return check_proof_of_time_nwesolowski(
            disc,
            x,
            y.serialize() + bytes(self.witness),
            self.number_of_iterations,
            discriminant_size_bits,
            self.witness_type,
        )
