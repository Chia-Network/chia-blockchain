from __future__ import annotations

from chia_rs import ConsensusConstants, PlotParam
from chia_rs.sized_ints import uint64

# The actual space in bytes of a plot, is _expected_plot_size(k) * UI_ACTUAL_SPACE_CONSTANT_FACTO
# This is not used in consensus, only for display purposes
UI_ACTUAL_SPACE_CONSTANT_FACTOR = 0.78

# Reference grouping used to calculate the consensus weight of a v2 plot.
# This is independent of the plot's actual group size.
# Changing this value changes the required proof-of-time iterations.
V2_PLOT_SIZE_CALC_REFERENCE_GROUP_SIZE = 256


def _plot_v2_bits_per_fragment(k: int, reference_group_size: int) -> float:
    """
    Estimate compressed fragment bits.
    At group size 256, the delta in bits per fragment,
    and thus final plot size, is negligible
    """
    assert 0 < reference_group_size < 65536

    # The encoder stores these low bits directly.
    low_bits = k - 8

    # Average costs of encoding the quotient and the FSE remainder.
    quotient_bits = 1.9957
    remainder_bits = 7.4485

    # Each plot contributes about 64 fragments to a chunk.
    fragments_per_chunk = 64 * reference_group_size

    # Estimated extra cost of encoding each chunk separately.
    # This correction was calibrated at k=28.
    extra_bits_per_chunk = 12.8

    # Share that chunk cost among all fragments in the chunk.
    extra_bits_per_fragment = extra_bits_per_chunk / fragments_per_chunk

    return low_bits + quotient_bits + remainder_bits + extra_bits_per_fragment


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
        bpf = _plot_v2_bits_per_fragment(k, V2_PLOT_SIZE_CALC_REFERENCE_GROUP_SIZE)

        return uint64((2**k) * bpf / 8)
