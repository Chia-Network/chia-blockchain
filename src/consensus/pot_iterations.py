from src.types.proof_of_space import ProofOfSpace
from src.types.sized_bytes import bytes32
from src.util.ints import uint8, uint64
from src.consensus.pos_quality import quality_str_to_quality


def calculate_iterations_quality(
    quality: bytes32,
    size: uint8,
    difficulty: uint64,
    vdf_ips: uint64,
    min_block_time: uint64,
) -> uint64:
    """
    Calculates the number of iterations from the quality. The quality is converted to a number
    between 0 and 1, then divided by expected plot size, and finally multiplied by the
    difficulty.
    """
    min_iterations = min_block_time * vdf_ips
    iters_rounded = (int(difficulty) << 32) // quality_str_to_quality(quality, size)

    iters_final = uint64(min_iterations + iters_rounded)
    assert iters_final >= 1
    return iters_final


def calculate_iterations(
    proof_of_space: ProofOfSpace,
    difficulty: uint64,
    vdf_ips: uint64,
    min_block_time: uint64,
) -> uint64:
    """
    Convenience function to calculate the number of iterations using the proof instead
    of the quality. The quality must be retrieved from the proof.
    """
    quality: bytes32 = proof_of_space.verify_and_get_quality_string()
    return calculate_iterations_quality(
        quality, proof_of_space.size, difficulty, vdf_ips, min_block_time
    )


def calculate_ips_from_iterations(
    proof_of_space: ProofOfSpace,
    difficulty: uint64,
    iterations: uint64,
    min_block_time: uint64,
) -> uint64:
    """
    Using the total number of iterations on a block (which is encoded in the block) along with
    other details, we can calculate the VDF speed (iterations per second) used to compute the
    constant factor in iterations, which is not written into the block.
    """
    quality: bytes32 = proof_of_space.verify_and_get_quality_string()
    iters_rounded = (int(difficulty) << 32) // quality_str_to_quality(
        quality, proof_of_space.size
    )
    min_iterations = uint64(iterations - iters_rounded)
    ips = min_iterations / min_block_time
    assert ips >= 1
    assert uint64(int(ips)) == ips
    return uint64(int(ips))
