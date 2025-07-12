from __future__ import annotations

from typing import Optional

from chia_rs import ConsensusConstants, PlotSize, ProofOfSpace
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint8, uint32, uint64

from chia.consensus.pos_quality import _expected_plot_size
from chia.types.blockchain_format.proof_of_space import verify_and_get_quality_string
from chia.util.hash import std_hash

# TODO: todo_v2_plots add to chia_rs and get from constants
PHASE_OUT_PERIOD = uint32(10000000)


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


def calculate_phase_out(
    constants: ConsensusConstants,
    sub_slot_iters: uint64,
    prev_transaction_block_height: uint32,
) -> uint64:
    if prev_transaction_block_height <= constants.HARD_FORK2_HEIGHT:
        return uint64(0)
    elif uint32(prev_transaction_block_height - constants.HARD_FORK2_HEIGHT) >= PHASE_OUT_PERIOD:
        return uint64(calculate_sp_interval_iters(constants, sub_slot_iters))

    return uint64(
        (
            uint32(prev_transaction_block_height - constants.HARD_FORK2_HEIGHT)
            * calculate_sp_interval_iters(constants, sub_slot_iters)
        )
        // PHASE_OUT_PERIOD
    )


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


def validate_pospace_and_get_required_iters(
    constants: ConsensusConstants,
    proof_of_space: ProofOfSpace,
    challenge: bytes32,
    cc_sp_hash: bytes32,
    height: uint32,
    difficulty: uint64,
    sub_slot_iters: uint64,
    prev_transaction_block_height: uint32,  # this is the height of the last tx block before the current block SP
) -> Optional[uint64]:
    q_str: Optional[bytes32] = verify_and_get_quality_string(
        proof_of_space, constants, challenge, cc_sp_hash, height=height
    )
    if q_str is None:
        return None

    return calculate_iterations_quality(
        constants,
        q_str,
        proof_of_space.size(),
        difficulty,
        cc_sp_hash,
        sub_slot_iters,
        prev_transaction_block_height,
    )


def calculate_iterations_quality(
    constants: ConsensusConstants,
    quality_string: bytes32,
    size: PlotSize,
    difficulty: uint64,
    cc_sp_output_hash: bytes32,
    ssi: uint64,
    prev_transaction_block_height: uint32,  # this is the height of the last tx block before the current block SP
) -> uint64:
    """
    Calculates the number of iterations from the quality. This is derives as the difficulty times the constant factor
    times a random number between 0 and 1 (based on quality string), divided by plot size.
    """
    if size.size_v1 is not None:
        assert size.size_v2 is None
        sp_quality_string: bytes32 = std_hash(quality_string + cc_sp_output_hash)
        phase_out = calculate_phase_out(constants, ssi, prev_transaction_block_height)
        iters = uint64(
            (
                int(difficulty)
                * int(constants.DIFFICULTY_CONSTANT_FACTOR)
                * int.from_bytes(sp_quality_string, "big", signed=False)
                // (int(pow(2, 256)) * int(_expected_plot_size(size.size_v1)))
            )
            + phase_out
        )
        return max(iters, uint64(1))
    else:
        raise NotImplementedError
