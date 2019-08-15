DIFFICULTY_STARTING = 1
DIFFICULTY_EPOCH = 2016  # The number of blocks per epoch
DIFFICULTY_TARGET = 200  # The target number of seconds per block
DIFFICULTY_FACTOR = 4  # The next difficulty is truncated to range [prev / FACTOR, prev * FACTOR]
DIFFICULTY_WARP_FACTOR = 4  # DELAY divides EPOCH in order to warp efficiently.
DIFFICULTY_DELAY = DIFFICULTY_EPOCH // DIFFICULTY_WARP_FACTOR  # The delay in blocks before the difficulty reset applies.
DISCRIMINANT_SIZE_BITS = 1024
MIN_BLOCK_TIME_PERCENT = 20
