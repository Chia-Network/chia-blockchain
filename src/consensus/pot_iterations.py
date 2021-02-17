from src.types.blockchain_format.sized_bytes import bytes32
from src.util.hash import std_hash
from src.util.ints import uint64, uint128, uint8
from src.consensus.pos_quality import quality_str_to_quality
from src.consensus.constants import ConsensusConstants


def is_overflow_block(constants: ConsensusConstants, signage_point_index: uint8) -> bool:
    if signage_point_index >= constants.NUM_SPS_SUB_SLOT:
        raise ValueError("SP index too high")
    return signage_point_index >= constants.NUM_SPS_SUB_SLOT - constants.NUM_SP_INTERVALS_EXTRA


def calculate_sp_interval_iters(constants: ConsensusConstants, sub_slot_iters: uint64) -> uint64:
    assert sub_slot_iters % constants.NUM_SPS_SUB_SLOT == 0
    return uint64(sub_slot_iters // constants.NUM_SPS_SUB_SLOT)


def calculate_sp_iters(constants: ConsensusConstants, sub_slot_iters: uint64, signage_point_index: uint8) -> uint64:
    if signage_point_index >= constants.NUM_SPS_SUB_SLOT:
        raise ValueError("SP index too high")
    return uint64(calculate_sp_interval_iters(constants, sub_slot_iters) * signage_point_index)


def calculate_ip_iters(
    constants: ConsensusConstants,
    sub_slot_iters: uint64,
    signage_point_index: uint8,
    required_iters: uint64,
) -> uint64:
    # Note that the SSI is for the block passed in, which might be in the previous epoch
    sp_iters = calculate_sp_iters(constants, sub_slot_iters, signage_point_index)
    sp_interval_iters: uint64 = calculate_sp_interval_iters(constants, sub_slot_iters)
    if sp_iters % sp_interval_iters != 0 or sp_iters >= sub_slot_iters:
        raise ValueError(f"Invalid sp iters {sp_iters} for this ssi {sub_slot_iters}")

    if required_iters >= sp_interval_iters or required_iters == 0:
        raise ValueError(
            f"Required iters {required_iters} is not below the sp interval iters {sp_interval_iters} "
            f"{sub_slot_iters} or not >0."
        )

    return uint64((sp_iters + constants.NUM_SP_INTERVALS_EXTRA * sp_interval_iters + required_iters) % sub_slot_iters)


def calculate_iterations_quality(
    difficulty_constant_factor: uint128,
    quality_string: bytes32,
    size: int,
    difficulty: uint64,
    cc_sp_output_hash: bytes32,
) -> uint64:
    """
    Calculates the number of iterations from the quality. The quality is converted to a number
    between 0 and 1, then divided by expected plot size, and finally multiplied by the
    difficulty.
    """
    sp_quality_string: bytes32 = std_hash(quality_string + cc_sp_output_hash)
    iters = uint64(
        uint128(int(difficulty) * int(difficulty_constant_factor)) // quality_str_to_quality(sp_quality_string, size)
    )
    return max(iters, uint64(1))
