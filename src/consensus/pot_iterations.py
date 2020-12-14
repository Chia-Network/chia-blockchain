from src.types.proof_of_space import ProofOfSpace
from src.types.sized_bytes import bytes32
from src.util.ints import uint64
from src.consensus.pos_quality import quality_str_to_quality
from src.consensus.constants import ConsensusConstants


def is_overflow_sub_block(constants: ConsensusConstants, ips: uint64, required_iters: uint64) -> bool:
    slot_iters: uint64 = calculate_slot_iters(constants, ips)
    extra_iters: uint64 = uint64(int(float(ips) * constants.EXTRA_ITERS_TIME_TARGET))
    return required_iters + extra_iters >= slot_iters


def calculate_slot_iters(constants: ConsensusConstants, ips: uint64) -> uint64:
    return ips * constants.SLOT_TIME_TARGET


def calculate_infusion_challenge_point_iters(
    constants: ConsensusConstants, ips: uint64, required_iters: uint64
) -> uint64:
    slot_iters: uint64 = calculate_slot_iters(constants, ips)
    if required_iters >= slot_iters:
        raise ValueError(f"Required iters {required_iters} is not below the slot iterations")
    checkpoint_size: uint64 = uint64(slot_iters // constants.NUM_CHECKPOINTS_PER_SLOT)
    return required_iters - required_iters % checkpoint_size


def calculate_infusion_point_iters(constants: ConsensusConstants, ips: uint64, required_iters: uint64) -> uint64:
    # Note that the IPS is for the block passed in, which might be in the previous epoch
    slot_iters: uint64 = calculate_slot_iters(constants, ips)
    if required_iters >= slot_iters:
        raise ValueError(f"Required iters {required_iters} is not below the slot iterations")
    extra_iters: uint64 = uint64(int(float(ips) * constants.EXTRA_ITERS_TIME_TARGET))
    return (required_iters + extra_iters) % slot_iters


def calculate_iterations_quality(
    quality: bytes32,
    size: int,
    difficulty: int,
) -> uint64:
    """
    Calculates the number of iterations from the quality. The quality is converted to a number
    between 0 and 1, then divided by expected plot size, and finally multiplied by the
    difficulty.
    """
    iters = uint64(int(difficulty) << 32) // quality_str_to_quality(quality, size)
    assert iters >= 1
    return iters


def calculate_iterations(
    proof_of_space: ProofOfSpace,
    difficulty: int,
    num_zero_bits: int,
) -> uint64:
    """
    Convenience function to calculate the number of iterations using the proof instead
    of the quality. The quality must be retrieved from the proof.
    """
    quality: bytes32 = proof_of_space.verify_and_get_quality_string(num_zero_bits)
    assert quality is not None
    return calculate_iterations_quality(quality, proof_of_space.size, difficulty)
