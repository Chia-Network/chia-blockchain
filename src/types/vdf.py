from dataclasses import dataclass

from chiavdf import create_discriminant
from src.types.classgroup import ClassgroupElement
from src.types.sized_bytes import bytes32
from src.util.classgroup_utils import ClassGroup, check_proof_of_time_nwesolowski
from src.util.ints import uint16, uint32, uint64
from src.util.streamable import Streamable, streamable
from src.consensus.constants import ConsensusConstants


@dataclass(frozen=True)
@streamable
class VDFInfo(Streamable):
    challenge_hash: bytes32
    number_of_iterations: uint64
    output: ClassgroupElement


@dataclass(frozen=True)
@streamable
class VDFProof(Streamable):
    witness_type: uint16
    witness: bytes

    def is_valid(self, constants: ConsensusConstants, info: VDFInfo):
        try:
            disc: int = int(
                create_discriminant(info.challenge_hash, constants.DISCRIMINANT_SIZE_BITS),
                16,
            )
            x = ClassGroup.from_ab_discriminant(2, 1, disc)
            y = ClassGroup.from_ab_discriminant(info.output.a, info.output.b, disc)
        except Exception:
            return False
        # TODO: parallelize somehow, this might included multiple mini proofs (n weso)
        # TODO: check for maximum witness type
        return check_proof_of_time_nwesolowski(
            disc,
            x,
            y.serialize() + bytes(self.witness),
            info.number_of_iterations,
            constants.DISCRIMINANT_SIZE_BITS,
            self.witness_type,
        )
