from __future__ import annotations

# The actual space in bytes of a plot, is expected_plot_size(k) * UI_ACTUAL_SPACE_CONSTANT_FACTO
# This is not used in consensus, only for display purposes
UI_ACTUAL_SPACE_CONSTANT_FACTOR = 0.78


def expected_plot_size(k: int) -> int:
    """
    Given the plot size parameter k (which is between 32 and 59), computes the
    expected size of the plot in bytes (times a constant factor). This is based on efficient encoding
    of the plot, and aims to be scale agnostic, so larger plots don't
    necessarily get more rewards per byte. The +1 is added to give half a bit more space per entry, which
    is necessary to store the entries in the plot.
    """

    return int(((2 * k) + 1) * (2 ** (k - 1)))
