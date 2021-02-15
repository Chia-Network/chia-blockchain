from src.util.ints import uint64
from src.types.blockchain_format.sized_bytes import bytes32


# The actual space in bytes of a plot, is _expected_plot_size(k) * UI_ACTUAL_SPACE_CONSTANT_FACTO
# This is not used in consensus, only for display purposes
UI_ACTUAL_SPACE_CONSTANT_FACTOR = 0.762


def _expected_plot_size(k: int) -> uint64:
    """
    Given the plot size parameter k (which is between 32 and 59), computes the
    expected size of the plot in bytes (times a constant factor). This is based on efficient encoding
    of the plot, and aims to be scale agnostic, so larger plots don't
    necessarily get more rewards per byte. The +1 is added to give half a bit more space per entry, which
    is necessary to store the entries in the plot.
    """

    return ((2 * k) + 1) * (2 ** (k - 1))


def quality_str_to_quality(quality_str: bytes32, k: int) -> uint64:
    """
    Takes a 256 bit quality string, converts it to an integer between 0 and 2**256,
    representing a decimal d=0.xxxxx..., where x are the bits of the quality.
    Then we perform 1/d, and multiply by the plot size and the
    This is a very good approximation for x when x is close to 1. However, we only
    work with big ints, to avoid using decimals. Finally, we divide by the plot size,
    to make bigger plots have a proportionally higher change to win.
    """
    t = pow(2, 256)
    xt = t - int.from_bytes(quality_str, "big")
    return t * _expected_plot_size(k) // xt
