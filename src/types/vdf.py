import logging
from dataclasses import dataclass
from typing import Optional

from chiavdf import create_discriminant
from src.types.classgroup import ClassgroupElement
from src.types.sized_bytes import bytes32
from src.util.classgroup_utils import ClassGroup, check_proof_of_time_nwesolowski
from src.util.ints import uint8, uint64
from src.util.streamable import Streamable, streamable
from src.consensus.constants import ConsensusConstants

log = logging.getLogger(__name__)


@dataclass(frozen=True)
@streamable
class VDFInfo(Streamable):
    challenge: bytes32  # Used to generate the discriminant (VDF group)
    number_of_iterations: uint64
    output: ClassgroupElement


@dataclass(frozen=True)
@streamable
class VDFProof(Streamable):
    witness_type: uint8
    witness: bytes

    def is_valid(
        self,
        constants: ConsensusConstants,
        input_el: ClassgroupElement,
        info: VDFInfo,
        target_vdf_info: Optional[VDFInfo] = None,
    ):
        """
        If target_vdf_info is passed in, it is compared with info.
        """
        if target_vdf_info is not None and info != target_vdf_info:
            log.error(f"INVALID VDF INFO. Have: {info} Expected: {target_vdf_info}")
            return False
        if self.witness_type + 1 > constants.MAX_VDF_WITNESS_SIZE:
            log.error(f"WITNESS SIZE TO BIG {constants.MAX_VDF_WITNESS_SIZE}")
            return False
        try:
            disc: int = int(
                create_discriminant(info.challenge, constants.DISCRIMINANT_SIZE_BITS),
                16,
            )
            x = ClassGroup.from_ab_discriminant(input_el.a, input_el.b, disc)
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
