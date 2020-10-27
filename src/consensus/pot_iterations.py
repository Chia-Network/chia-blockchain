from src.types.proof_of_space import ProofOfSpace
from src.types.sized_bytes import bytes32
from src.util.ints import uint64, uint128
from src.consensus.pos_quality import quality_str_to_quality
from src.consensus.constants import ConsensusConstants


def is_overflow_sub_block(constants: ConsensusConstants, ips: uint64, required_iters: uint64) -> bool:
    slot_iters: uint64 = calculate_slot_iters(constants, ips)
    if required_iters >= slot_iters:
        raise ValueError(f"Required iters {required_iters} is not below the slot iterations")
    extra_iters: uint64 = uint64(int(float(ips) * constants.EXTRA_ITERS_TIME_TARGET))
    return required_iters + extra_iters >= slot_iters


def calculate_slot_iters(constants: ConsensusConstants, ips: uint64) -> uint64:
    return ips * constants.SLOT_TIME_TARGET


def calculate_icp_iters(constants: ConsensusConstants, ips: uint64, required_iters: uint64) -> uint64:
    slot_iters: uint64 = calculate_slot_iters(constants, ips)
    if required_iters >= slot_iters:
        raise ValueError(f"Required iters {required_iters} is not below the slot iterations")
    checkpoint_size: uint64 = uint64(slot_iters // constants.NUM_CHECKPOINTS_PER_SLOT)
    checkpoint_index: int = required_iters // checkpoint_size

    if checkpoint_index >= constants.NUM_CHECKPOINTS_PER_SLOT:
        # Checkpoints don't divide slot_iters cleanly, so we return the last checkpoint
        return required_iters - required_iters % checkpoint_size - checkpoint_size
    else:
        return required_iters - required_iters % checkpoint_size


def calculate_ip_iters(constants: ConsensusConstants, ips: uint64, required_iters: uint64) -> uint64:
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
    iters = uint64(uint128(int(difficulty) << 32) // quality_str_to_quality(quality, size))
    return max(iters, uint64(1))


def calculate_iterations(
    constants: ConsensusConstants,
    proof_of_space: ProofOfSpace,
    difficulty: int,
) -> uint64:
    """
    Convenience function to calculate the number of iterations using the proof instead
    of the quality. The quality must be retrieved from the proof.
    """
    quality: bytes32 = proof_of_space.verify_and_get_quality_string(constants)
    assert quality is not None
    return calculate_iterations_quality(quality, proof_of_space.size, difficulty)
