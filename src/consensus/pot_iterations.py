from src.types.proof_of_space import ProofOfSpace
from src.types.sized_bytes import bytes32
from src.util.ints import uint8, uint64
from src.consensus.pos_quality import quality_str_to_quality


def calculate_iterations_quality(
    quality: bytes32, size: uint8, difficulty: uint64, min_iterations: uint64,
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
    proof_of_space: ProofOfSpace, difficulty: uint64, min_iterations: uint64,
) -> uint64:
    """
    Convenience function to calculate the number of iterations using the proof instead
    of the quality. The quality must be retrieved from the proof.
    """
    quality: bytes32 = proof_of_space.verify_and_get_quality_string()
    return calculate_iterations_quality(
        quality, proof_of_space.size, difficulty, min_iterations
    )


def calculate_min_iters_from_iterations(
    proof_of_space: ProofOfSpace, difficulty: uint64, iterations: uint64,
) -> uint64:
    """
    Using the total number of iterations on a block (which is encoded in the block) along with
    other details, we can calculate the constant factor in iterations, which is not written into
    the block.
    """
    quality: bytes32 = proof_of_space.verify_and_get_quality_string()
    iters_rounded = (int(difficulty) << 32) // quality_str_to_quality(
        quality, proof_of_space.size
    )
    min_iterations = uint64(iterations - iters_rounded)
    assert min_iterations >= 1
    return min_iterations
