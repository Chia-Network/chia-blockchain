from __future__ import annotations

from chia_rs import ConsensusConstants, PlotParam
from chia_rs.sized_ints import uint64

# The actual space in bytes of a plot, is _expected_plot_size(k) * UI_ACTUAL_SPACE_CONSTANT_FACTO
# This is not used in consensus, only for display purposes
UI_ACTUAL_SPACE_CONSTANT_FACTOR = 0.78

# Expected v2 plot sizes in bytes, calculated for a reference group of 256 plots.
# Precomputed to keep floating-point arithmetic out of consensus.
# See _plot_v2_bits_per_fragment in test_pot_iterations.py for the calculation.
# Changing these sizes changes the required proof-of-time iterations.
_EXPECTED_PLOT_SIZES_V2: dict[int, uint64] = {
    18: uint64(637_173),
    20: uint64(2_810_836),
    22: uint64(12_291_922),
    24: uint64(53_361_993),
    26: uint64(230_225_189),
    28: uint64(988_009_621),
}


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
        return _EXPECTED_PLOT_SIZES_V2[constants.PLOT_SIZE_V2]
