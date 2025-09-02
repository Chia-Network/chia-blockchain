from __future__ import annotations

from chia_rs import PlotSize
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint64

# The actual space in bytes of a plot, is _expected_plot_size(k) * UI_ACTUAL_SPACE_CONSTANT_FACTO
# This is not used in consensus, only for display purposes
UI_ACTUAL_SPACE_CONSTANT_FACTOR = 0.78

# TODO: todo_v2_plots these values prelimenary. When the plotter is complete,
# replace this table with a closed form formula
v2_plot_sizes: dict[int, uint64] = {
    16: uint64(222_863),
    18: uint64(1_048_737),
    20: uint64(4_824_084),
    22: uint64(21_812_958),
    24: uint64(97_318_160),
    26: uint64(429_539_960),
    28: uint64(1_879_213_114),
    30: uint64(8_161_097_549),
    32: uint64(35_221_370_574),
}


def quality_for_partial_proof(partial_proof: bytes, challenge: bytes32) -> bytes32:
    # TODO todo_v2_plots real implementaion
    return challenge


def _expected_plot_size(size: PlotSize) -> uint64:
    """
    Given the plot size parameter k (which is between 32 and 59), computes the
    expected size of the plot in bytes (times a constant factor). This is based on efficient encoding
    of the plot, and aims to be scale agnostic, so larger plots don't
    necessarily get more rewards per byte. The +1 is added to give half a bit more space per entry, which
    is necessary to store the entries in the plot.
    """

    k: int
    if size.size_v1 is not None:
        k = size.size_v1
        return uint64(((2 * k) + 1) * (2 ** (k - 1)))
    else:
        assert size.size_v2 is not None
        k = size.size_v2
        if k in v2_plot_sizes:
            return v2_plot_sizes[k]
        else:
            # TODO: todo_v2_plots support test plots with lower k-values
            return uint64(0)
