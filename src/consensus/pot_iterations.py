from src.types.proof_of_space import ProofOfSpace
from src.types.sized_bytes import bytes32
from src.util.ints import uint64
from src.consensus.pos_quality import quality_str_to_quality
from src.consensus.constants import ConsensusConstants


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
    return required_iters + extra_iters


def calculate_iterations_quality(
    quality: bytes32,
    size: int,
    difficulty: int,
    min_iterations: int,
) -> uint64:
    """
    Calculates the number of iterations from the quality. The quality is converted to a number
    between 0 and 1, then divided by expected plot size, and finally multiplied by the
    difficulty.
    """
    iters_rounded = (int(difficulty) << 32) // quality_str_to_quality(quality, size)

    iters_final = uint64(min_iterations + iters_rounded)
    assert iters_final >= 1
    return iters_final


def calculate_iterations(
    proof_of_space: ProofOfSpace,
    difficulty: int,
    min_iterations: int,
    num_zero_bits: int,
) -> uint64:
    """
    Convenience function to calculate the number of iterations using the proof instead
    of the quality. The quality must be retrieved from the proof.
    """
    quality: bytes32 = proof_of_space.verify_and_get_quality_string(num_zero_bits)
    assert quality is not None
    return calculate_iterations_quality(quality, proof_of_space.size, difficulty, min_iterations)


def calculate_min_iters_from_iterations(
    proof_of_space: ProofOfSpace,
    difficulty: int,
    iterations: uint64,
    num_zero_bits: int,
) -> uint64:
    """
    Using the total number of iterations on a block (which is encoded in the block) along with
    other details, we can calculate the constant factor in iterations, which is not written into
    the block.
    """
    quality: bytes32 = proof_of_space.verify_and_get_quality_string(num_zero_bits)
    iters_rounded = (int(difficulty) << 32) // quality_str_to_quality(quality, proof_of_space.size)
    min_iterations = uint64(iterations - iters_rounded)
    assert min_iterations >= 1
    return min_iterations
