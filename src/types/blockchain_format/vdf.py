import logging
import traceback
from dataclasses import dataclass
from typing import Optional, Tuple, Dict

from chiavdf import create_discriminant
from src.types.blockchain_format.classgroup import ClassgroupElement
from src.types.blockchain_format.sized_bytes import bytes32
from chiavdf import verify_n_wesolowski
from src.util.ints import uint8, uint64
from src.util.streamable import Streamable, streamable
from src.consensus.constants import ConsensusConstants

log = logging.getLogger(__name__)

discriminant_cache: Dict[Tuple[bytes32, int], int] = {}


def add_to_cache(challenge_size, dsc):
    if len(discriminant_cache.keys()) > 10:
        keys = list(discriminant_cache.keys())
        for i in range(0, 5):
            discriminant_cache.pop(keys[i])
    discriminant_cache[challenge_size] = dsc


def get_discriminant(challenge, size_bites):
    if (challenge, size_bites) in discriminant_cache:
        return discriminant_cache[(challenge, size_bites)]
    else:
        dsc = int(
            create_discriminant(challenge, size_bites),
            16,
        )
        add_to_cache((challenge, size_bites), dsc)
        return dsc


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
            tb = traceback.format_stack()
            log.error(f"{tb} INVALID VDF INFO. Have: {info} Expected: {target_vdf_info}")
            return False
        if self.witness_type + 1 > constants.MAX_VDF_WITNESS_SIZE:
            return False
        try:
            disc: int = get_discriminant(info.challenge, constants.DISCRIMINANT_SIZE_BITS)
            # TODO: parallelize somehow, this might included multiple mini proofs (n weso)
            return verify_n_wesolowski(
                str(disc),
                input_el.data,
                info.output.data + bytes(self.witness),
                info.number_of_iterations,
                constants.DISCRIMINANT_SIZE_BITS,
                self.witness_type,
            )
        except Exception:
            return False
