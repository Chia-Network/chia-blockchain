DIFFICULTY_STARTING = 50  # These are in units of 2^32
DIFFICULTY_EPOCH = 10  # The number of blocks per epoch
DIFFICULTY_TARGET = 10  # The target number of seconds per block
DIFFICULTY_FACTOR = 4  # The next difficulty is truncated to range [prev / FACTOR, prev * FACTOR]
DIFFICULTY_WARP_FACTOR = 4  # DELAY divides EPOCH in order to warp efficiently.
DIFFICULTY_DELAY = DIFFICULTY_EPOCH // DIFFICULTY_WARP_FACTOR  # The delay in blocks before the difficulty reset applies
DISCRIMINANT_SIZE_BITS = 1024

# The percentage of the difficulty target that the VDF must be run for, at a minimum
MIN_BLOCK_TIME_PERCENT = 20
MIN_VDF_ITERATIONS = 1  # These are in units of 2^32
