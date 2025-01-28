from __future__ import annotations

from chia.consensus.pos_quality import _expected_plot_size
from chia.util.hash import std_hash
from chia.util.ints import uint64, uint128


def calculate_iterations_quality(
    difficulty_constant_factor: uint128,
    quality_string: bytes32,
    size: int,
    difficulty: uint64,
    cc_sp_output_hash: bytes32,
) -> uint64:
    """
    Calculates the number of iterations from the quality. This is derives as the difficulty times the constant factor
    times a random number between 0 and 1 (based on quality string), divided by plot size.
    """
    sp_quality_string: bytes32 = std_hash(quality_string + cc_sp_output_hash)

    iters = uint64(
        int(difficulty)
        * int(difficulty_constant_factor)
        * int.from_bytes(sp_quality_string, "big", signed=False)
        // (int(pow(2, 256)) * int(_expected_plot_size(size)))
    )
    return max(iters, uint64(1))
