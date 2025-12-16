from __future__ import annotations

from chia_rs import ConsensusConstants, PlotParam
from chia_rs.sized_ints import uint64

# The actual space in bytes of a plot, is _expected_plot_size(k) * UI_ACTUAL_SPACE_CONSTANT_FACTO
# This is not used in consensus, only for display purposes
UI_ACTUAL_SPACE_CONSTANT_FACTOR = 0.78


def _expected_plot_size(size: PlotParam, constants: ConsensusConstants) -> uint64:
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
        k = constants.PLOT_SIZE_V2
        # TODO: todo_v2_plots this formula may change slightly before the
        # final version of the plotter. Revisit this when the plotter is complete
        return uint64((2**k) * (k + 1.46) / 8)
