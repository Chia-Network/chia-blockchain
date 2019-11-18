from decimal import ROUND_UP, Decimal, getcontext

from src.types.proof_of_space import ProofOfSpace
from src.types.sized_bytes import bytes32
from src.util.ints import uint8, uint64

# Sets a high precision so we can convert a 256 bit has to a decimal, and
# divide by a large number, while not losing any bits of precision.
getcontext().prec = 600


def _expected_plot_size(k: uint8) -> Decimal:
    """
    Given the plot size parameter k (which is between 30 and 59), computes the
    expected size of the plot in bytes. This is based on efficient encoding
    of the plot, and aims to be scale agnostic, so larger plots don't
    necessarily get more rewards per byte.
    """
    return Decimal(Decimal(0.762) * k * pow(2, k))


def _quality_to_decimal(quality: bytes32) -> Decimal:
    """
    Takes a 256 bit quality, converts it to an integer between 0 and 2**256,
    representing a decimal d=0.xxxxx..., where x are the bits of the quality.
    Then we perform -log(d), using a Pade approximation for log:
    log(1+x) = x(6+x)/(6+4x)
    This is a very good approximation for x when x is close to 1. However, we only
    work with big ints, to avoid using decimals.
    """
    t = pow(2, 256)
    xt = int.from_bytes(quality, "big") - t
    numerator = xt * xt + 6 * (xt) * t
    denominator = 6 * t + 4 * (xt)
    # Performs big integer division, and then turns it into a decimal
    return -Decimal(numerator // denominator) / Decimal(t)


def calculate_iterations_quality(quality: bytes32, size: uint8, difficulty: uint64,
                                 vdf_ips: uint64, min_block_time: uint64) -> uint64:
    """
    Calculates the number of iterations from the quality. The quality is converted to a number
    between 0 and 1, then divided by expected plot size, and finally multiplied by the
    difficulty.
    """
    min_iterations = min_block_time * vdf_ips
    dec_iters = (Decimal(int(difficulty) << 32) *
                 (_quality_to_decimal(quality) / _expected_plot_size(size)))
    iters_final = uint64(int(min_iterations + dec_iters.to_integral_exact(rounding=ROUND_UP)))
    assert iters_final >= 1
    return iters_final


def calculate_iterations(proof_of_space: ProofOfSpace, difficulty: uint64, vdf_ips: uint64,
                         min_block_time: uint64) -> uint64:
    """
    Convenience function to calculate the number of iterations using the proof instead
    of the quality. The quality must be retrieved from the proof.
    """
    quality: bytes32 = proof_of_space.verify_and_get_quality()
    return calculate_iterations_quality(quality, proof_of_space.size, difficulty, vdf_ips, min_block_time)


def calculate_ips_from_iterations(proof_of_space: ProofOfSpace, difficulty: uint64,
                                  iterations: uint64, min_block_time: uint64) -> uint64:
    """
    Using the total number of iterations on a block (which is encoded in the block) along with
    other details, we can calculate the VDF speed (iterations per second) used to compute the
    constant factor in iterations, which is not written into the block.
    """
    quality: bytes32 = proof_of_space.verify_and_get_quality()
    dec_iters = (Decimal(int(difficulty) << 32) *
                 (_quality_to_decimal(quality) / _expected_plot_size(proof_of_space.size)))
    iters_rounded = int(dec_iters.to_integral_exact(rounding=ROUND_UP))
    min_iterations = uint64(iterations - iters_rounded)
    ips = min_iterations / min_block_time
    assert ips >= 1
    assert uint64(int(ips)) == ips
    return uint64(int(ips))
