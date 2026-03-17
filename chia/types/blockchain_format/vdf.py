from __future__ import annotations

import logging
import traceback
from enum import IntEnum
from functools import lru_cache

from chia_rs import ConsensusConstants, VDFInfo, VDFProof
from chia_rs.sized_bytes import bytes32, bytes100
from chia_rs.sized_ints import uint8, uint64

from chia_vdf_verify import create_discriminant_bytes, verify_n_wesolowski_bytes

from chia.types.blockchain_format.classgroup import ClassgroupElement

log = logging.getLogger(__name__)

__all__ = ["VDFInfo", "VDFProof"]


@lru_cache(maxsize=200)
def get_discriminant_bytes(challenge: bytes32, size_bites: int) -> bytes:
    """Return discriminant as bytes (sign+magnitude). Cached per (challenge, size_bits)."""
    return create_discriminant_bytes(challenge, size_bites)


def verify_vdf(
    disc_bytes: bytes,
    input_el: bytes100,
    output: bytes,
    number_of_iterations: uint64,
    discriminant_size: int,
    witness_type: uint8,
) -> bool:
    """Verify VDF proof. disc_bytes from get_discriminant_bytes (avoids repeated parse)."""
    return verify_n_wesolowski_bytes(  # type:ignore[no-any-return]
        disc_bytes,
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
    target_vdf_info: VDFInfo | None = None,
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
        disc_bytes: bytes = get_discriminant_bytes(info.challenge, constants.DISCRIMINANT_SIZE_BITS)
        # TODO: parallelize somehow, this might included multiple mini proofs (n weso)
        return verify_vdf(
            disc_bytes,
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
