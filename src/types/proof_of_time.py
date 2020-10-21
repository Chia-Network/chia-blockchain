from dataclasses import dataclass
from typing import List

from chiavdf import create_discriminant
from src.types.classgroup import ClassgroupElement
from src.types.sized_bytes import bytes32
from src.util.classgroup_utils import ClassGroup, check_proof_of_time_nwesolowski
from src.util.ints import uint16, uint64
from src.util.streamable import Streamable, streamable
from src.consensus.constants import ConsensusConstants


@dataclass(frozen=True)
@streamable
class ProofOfTime(Streamable):
    challenge_hash: bytes32
    number_of_iterations: uint64
    output: ClassgroupElement
    witness_type: uint16
    witness: bytes

    def is_valid(self, discriminant_size_bits):
        try:
            disc: int = int(
                create_discriminant(self.challenge_hash, discriminant_size_bits),
                16,
            )
            x = ClassGroup.from_ab_discriminant(2, 1, disc)
            y = ClassGroup.from_ab_discriminant(self.output.a, self.output.b, disc)
        except Exception:
            return False
        # TODO: parallelize somehow, this might included multiple mini proofs (n weso)
        # TODO: check for maximum witness type
        return check_proof_of_time_nwesolowski(
            disc,
            x,
            y.serialize() + bytes(self.witness),
            self.number_of_iterations,
            discriminant_size_bits,
            self.witness_type,
        )


def validate_composite_proof_of_time(
    constants: ConsensusConstants,
    challenge: bytes32,
    iters: uint64,
    output: ClassgroupElement,
    proof: ProofOfTime,
) -> bool:
    if challenge != proof.challenge_hash:
        return False
    if output != proof.output:
        return False
    if iters != proof.number_of_iterations:
        return False
    if not proof.is_valid(constants.DISCRIMINANT_SIZE_BITS):
        return False
    return True


def combine_proofs_of_time(constants: ConsensusConstants, proofs: List[ProofOfTime]) -> ProofOfTime:
    # proof3 y2 proof2 y1 proof1
    combined_proof: bytes = b""
    for proof in reversed(proofs)[1:]:
        y = ClassGroup.from_ab_discriminant(proof.output.a, proof.output.b, constants.DISCRIMINANT_SIZE_BITS)
        combined_proof += y.serialize() + proof.witness
    combined_proof = proofs[-1].witness + combined_proof
    return ProofOfTime(
        proofs[0].challenge_hash,
        sum(p.number_of_iterations for p in proofs),
        proofs[-1].output,
        uint16(sum(p.witness_type + 1 for p in proofs) - 1),
        combined_proof,
    )
