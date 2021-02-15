from typing import Tuple

from chiavdf import prove

from src.consensus.constants import ConsensusConstants
from src.types.blockchain_format.classgroup import ClassgroupElement
from src.types.blockchain_format.sized_bytes import bytes32
from src.types.blockchain_format.vdf import VDFProof, VDFInfo
from src.util.ints import uint64, uint8


def get_vdf_info_and_proof(
    constants: ConsensusConstants,
    vdf_input: ClassgroupElement,
    challenge_hash: bytes32,
    number_iters: uint64,
) -> Tuple[VDFInfo, VDFProof]:
    form_size = ClassgroupElement.get_size(constants)
    result: bytes = prove(
        bytes(challenge_hash),
        vdf_input.data,
        constants.DISCRIMINANT_SIZE_BITS,
        number_iters,
    )

    output = ClassgroupElement.from_bytes(result[:form_size])
    proof_bytes = result[form_size : 2 * form_size]
    return VDFInfo(challenge_hash, number_iters, output), VDFProof(uint8(0), proof_bytes)
