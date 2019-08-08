from src.util.ints import uint64, uint8
from src.types.sized_bytes import bytes32
from src.types.proof_of_space import ProofOfSpace
from decimal import getcontext, Decimal, ROUND_UP

# Sets a high precision so we can convert a 256 bit has to a decimal, and
# divide by a large number, while not losing any bits of precision.
getcontext().prec = 200


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
    Converts the quality, a 256 bit hash, into a decimal between 0 and 1, by adding
    a radix point. So "01110101..." becomes 0.01110101...
    Full precision is used, so the resulting decimal has 256 decimal places in binary
    representation.
    """
    sum_decimals = Decimal(0)
    multiplier = Decimal(1)
    for byte_index in range(0, 32):
        byte = quality[byte_index]
        for bit_index in range(0, 8):
            multiplier /= 2
            if (byte & (1 << (7 - bit_index))):
                sum_decimals += multiplier
    return sum_decimals


def calculate_iterations_quality(quality: bytes32, size: uint8, difficulty: uint64) -> uint64:
    """
    Calculates the number of iterations from the quality. The quality is converted to a number
    between 0 and 1, then divided by expected plot size, and finally multiplied by the
    difficulty.
    """
    dec_iters = (Decimal(int(difficulty)) *
                 (_quality_to_decimal(quality) / _expected_plot_size(size)))
    return uint64(int(dec_iters.to_integral_exact(rounding=ROUND_UP)))


def calculate_iterations(proof_of_space: ProofOfSpace, challenge_hash: bytes32,
                         difficulty: uint64) -> uint64:
    """
    Convenience function to calculate the number of iterations using the proof instead
    of the quality. The quality must be retrieved from the proof.
    """
    quality: bytes32 = proof_of_space.verify_and_get_quality(challenge_hash)
    return calculate_iterations_quality(quality, proof_of_space.size, difficulty)
