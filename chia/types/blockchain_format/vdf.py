from __future__ import annotations

import logging
import traceback
from enum import IntEnum
from functools import lru_cache
from typing import Optional

from chia_rs import VDFInfo, VDFProof
from chiavdf import create_discriminant, verify_n_wesolowski

from chia.consensus.constants import ConsensusConstants
from chia.types.blockchain_format.classgroup import ClassgroupElement
from chia.types.blockchain_format.sized_bytes import bytes32, bytes100
from chia.util.ints import uint8, uint64

log = logging.getLogger(__name__)

__all__ = ["VDFInfo", "VDFProof"]


@lru_cache(maxsize=200)
def get_discriminant(challenge: bytes32, size_bites: int) -> int:
    return int(
        create_discriminant(challenge, size_bites),
        16,
    )


@lru_cache(maxsize=1000)
def verify_vdf(
    disc: int,
    input_el: bytes100,
    output: bytes,
    number_of_iterations: uint64,
    discriminant_size: int,
    witness_type: uint8,
) -> bool:
    # TODO: chiavdf needs hinted
    return verify_n_wesolowski(  # type:ignore[no-any-return]
        str(disc),
        input_el,
        output,
        number_of_iterations,
        discriminant_size,
        witness_type,
    )


def validate_vdf(
    proof: VDFProof,
    constants: ConsensusConstants,
    input_el: ClassgroupElement,
    info: VDFInfo,
    target_vdf_info: Optional[VDFInfo] = None,
) -> bool:
    """
    If target_vdf_info is passed in, it is compared with info.
    """
    if target_vdf_info is not None and info != target_vdf_info:
        tb = traceback.format_stack()
        log.error(f"{tb} INVALID VDF INFO. Have: {info} Expected: {target_vdf_info}")
        return False
    if proof.witness_type + 1 > constants.MAX_VDF_WITNESS_SIZE:
        return False
    try:
        disc: int = get_discriminant(info.challenge, constants.DISCRIMINANT_SIZE_BITS)
        # TODO: parallelize somehow, this might included multiple mini proofs (n weso)
        return verify_vdf(
            disc,
            input_el.data,
            info.output.data + bytes(proof.witness),
            info.number_of_iterations,
            constants.DISCRIMINANT_SIZE_BITS,
            proof.witness_type,
        )
    except Exception:
        return False


# Stores, for a given VDF, the field that uses it.
class CompressibleVDFField(IntEnum):
    CC_EOS_VDF = 1
    ICC_EOS_VDF = 2
    CC_SP_VDF = 3
    CC_IP_VDF = 4
