from src.util.ints import uint8, uint64
from src.types.sized_bytes import bytes32


def _expected_plot_size(k: uint8) -> uint64:
    """
    Given the plot size parameter k (which is between 30 and 59), computes the
    expected size of the plot in bytes. This is based on efficient encoding
    of the plot, and aims to be scale agnostic, so larger plots don't
    necessarily get more rewards per byte.
    """
    # The following line is the formula for total number of bytes. Instead we can use a formula
    # for number of kilobytes, to prevent decimal usage.
    # return 0.762 * k * pow(2, k)

    return 780 * k * pow(2, k - 10)


def quality_str_to_quality(quality_str: bytes32, k: uint8) -> uint64:
    """
    Takes a 256 bit quality string, converts it to an integer between 0 and 2**256,
    representing a decimal d=0.xxxxx..., where x are the bits of the quality.
    Then we perform -log(d), using a Pade approximation for log:
    log(1+x) = x(6+x)/(6+4x)
    This is a very good approximation for x when x is close to 1. However, we only
    work with big ints, to avoid using decimals. Finally, we divide by the plot size,
    to make bigger plots have a proportionally higher change to win.
    """
    t = pow(2, 256)

    # xt is (dec(quality_str) - 1) * 2^256. That is, the 0.xxxxx representation of the hash,
    # minus 1 (so that we can input it into the approximation for log(1+x)), times 2^256, since
    # we want to work with big ints and not decimals
    xt = int.from_bytes(quality_str, "big") - t
    numerator = xt * xt + 6 * (xt) * t
    denominator = 6 * t + 4 * (xt)

    # To get the output of log(x), you would do the following
    # log(1+x) = - (numerator / denominator / t)

    # Instead, here we rearrange the terms to only have one division, which we can use bigints for
    return -(t * _expected_plot_size(k) * denominator) // numerator
