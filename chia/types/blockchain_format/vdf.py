import logging
import traceback
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from enum import IntEnum
from typing import Optional
from functools import lru_cache

from chiavdf import (
    create_discriminant,
    verify_n_wesolowski,
    verify_n_wesolowski_with_b,
    get_b_from_n_wesolowski,
)

from chia.consensus.constants import ConsensusConstants
from chia.types.blockchain_format.classgroup import ClassgroupElement, CompressedClassgroupElement
from chia.types.blockchain_format.sized_bytes import bytes32, bytes100
from chia.util.ints import uint8, uint64
from chia.util.streamable import Streamable, streamable

log = logging.getLogger(__name__)


@lru_cache(maxsize=200)
def get_discriminant(challenge, size_bites) -> int:
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
):

    return verify_n_wesolowski(
        str(disc),
        input_el,
        output,
        number_of_iterations,
        discriminant_size,
        witness_type,
    )


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
    normalized_to_identity: bool

    def is_valid(
        self,
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
        if self.witness_type + 1 > constants.MAX_VDF_WITNESS_SIZE:
            return False
        try:
            return verify_vdf(
                get_discriminant(info.challenge, constants.DISCRIMINANT_SIZE_BITS),
                input_el.data,
                info.output.data + bytes(self.witness),
                info.number_of_iterations,
                constants.DISCRIMINANT_SIZE_BITS,
                self.witness_type,
            )
        except Exception:
            return False


# Stores, for a given VDF, the field that uses it.
class CompressibleVDFField(IntEnum):
    CC_EOS_VDF = 1
    ICC_EOS_VDF = 2
    CC_SP_VDF = 3
    CC_IP_VDF = 4



def compress_future(
    disc: str,
    output: bytes,
    input: bytes,
    proof: bytes,
    number_of_iterations: uint64,
    proof_type: int,
):
    return get_b_from_n_wesolowski(
        disc,
        input,
        output + proof,
        number_of_iterations,
        proof_type,
    )

def compress_output(
    disc_size: int,
    challenge: bytes32,
    input: ClassgroupElement,
    output: ClassgroupElement,
    proof: VDFProof,
    number_of_iterations: uint64,
    executor: ProcessPoolExecutor,
):


    future = executor.submit(
        compress_future,
        str(get_discriminant(challenge, disc_size)),
        bytes(output.data),
        bytes(input.data),
        bytes(proof.witness),
        number_of_iterations,
        proof.witness_type,
    )

    return future


def verify_compressed_vdf(
    constants: ConsensusConstants,
    challenge: bytes32,
    vdf_input: ClassgroupElement,
    vdf_output: CompressedClassgroupElement,
    proof: VDFProof,
    number_of_iterations: uint64,
):
    if proof.witness_type + 1 > constants.MAX_VDF_WITNESS_SIZE:
        raise Exception(f"invalid witness type")
    x, y = verify_n_wesolowski_with_b(
        str(get_discriminant(challenge, constants.DISCRIMINANT_SIZE_BITS)),
        f"0x{vdf_output.data.hex()}",
        bytes(vdf_input.data),
        bytes(proof.witness),
        number_of_iterations,
        proof.witness_type,
    )
    return x, ClassgroupElement.from_bytes(y)
