from typing import Tuple

from chiavdf import prove

from src.consensus.constants import ConsensusConstants
from src.types.classgroup import ClassgroupElement
from src.types.sized_bytes import bytes32
from src.types.vdf import VDFProof, VDFInfo
from src.util.ints import uint64, int512, uint8


def get_vdf_info_and_proof(
    constants: ConsensusConstants,
    vdf_input: ClassgroupElement,
    challenge_hash: bytes32,
    number_iters: uint64,
) -> Tuple[VDFInfo, VDFProof]:
    int_size = (constants.DISCRIMINANT_SIZE_BITS + 16) >> 4
    result: bytes = prove(
        bytes(challenge_hash),
        str(vdf_input.a),
        str(vdf_input.b),
        constants.DISCRIMINANT_SIZE_BITS,
        number_iters,
    )

    output = ClassgroupElement(
        int512(
            int.from_bytes(
                result[0:int_size],
                "big",
                signed=True,
            )
        ),
        int512(
            int.from_bytes(
                result[int_size : 2 * int_size],
                "big",
                signed=True,
            )
        ),
    )
    proof_bytes = result[2 * int_size : 4 * int_size]
    return VDFInfo(challenge_hash, number_iters, output), VDFProof(uint8(0), proof_bytes)
