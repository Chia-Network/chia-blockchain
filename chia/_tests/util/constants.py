from __future__ import annotations

from chia.consensus.default_constants import DEFAULT_CONSTANTS
from chia.util.ints import uint8, uint16, uint32, uint64, uint128

test_constants = DEFAULT_CONSTANTS.replace(
    MIN_PLOT_SIZE=uint8(18),
    MIN_BLOCKS_PER_CHALLENGE_BLOCK=uint8(12),
    DIFFICULTY_STARTING=uint64(2**9),
    DISCRIMINANT_SIZE_BITS=uint16(16),
    SUB_EPOCH_BLOCKS=uint32(170),
    WEIGHT_PROOF_THRESHOLD=uint8(2),
    WEIGHT_PROOF_RECENT_BLOCKS=uint32(380),
    DIFFICULTY_CONSTANT_FACTOR=uint128(33554432),
    NUM_SPS_SUB_SLOT=uint32(16),  # Must be a power of 2
    MAX_SUB_SLOT_BLOCKS=uint32(50),
    EPOCH_BLOCKS=uint32(340),
    SUB_SLOT_ITERS_STARTING=uint64(2**10),  # Must be a multiple of 64
    NUMBER_ZERO_BITS_PLOT_FILTER=uint8(1),  # H(plot signature of the challenge) must start with these many zeroes
)
