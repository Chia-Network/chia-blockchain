from deafwave.util.ints import uint64

from .constants import ConsensusConstants

testnet_kwargs = {
    "SLOT_BLOCKS_TARGET": 32,
    # Must be less than half of SLOT_BLOCKS_TARGET
    "MIN_BLOCKS_PER_CHALLENGE_BLOCK": 16,
    "MAX_SUB_SLOT_BLOCKS": 128,  # Must be less than half of SUB_EPOCH_BLOCKS
    "NUM_SPS_SUB_SLOT": 64,  # Must be a power of 2
    "SUB_SLOT_ITERS_STARTING": 2 ** 27,
    # DIFFICULTY_STARTING is the starting difficulty for the first epoch, which is then further
    # multiplied by another factor of DIFFICULTY_CONSTANT_FACTOR, to be used in the VDF iter calculation formula.
    "DIFFICULTY_CONSTANT_FACTOR": 2 ** 67,
    "DIFFICULTY_STARTING": 7,
    "DIFFICULTY_CHANGE_BLOCK": 9216,
    # The next difficulty is truncated to range [prev / FACTOR, prev * FACTOR]
    "DIFFICULTY_CHANGE_MAX_FACTOR": 3,
    # These 3 constants must be changed at the same time
    "SUB_EPOCH_BLOCKS": 384,  # The number of blocks per sub-epoch, mainnet 384
    # The number of blocks per epoch, mainnet 4608. Must be multiple of SUB_EPOCH_SB
    "EPOCH_BLOCKS_INITIAL": 768,
    "EPOCH_BLOCKS": 4608,
    # The number of bits to look at in difficulty and min iters. The rest are zeroed
    "SIGNIFICANT_BITS": 8,
    # Max is 1024 (based on ClassGroupElement int size)
    "DISCRIMINANT_SIZE_BITS": 1024,
    # H(plot signature of the challenge) must start with these many zeroes
    "NUMBER_ZERO_BITS_PLOT_FILTER": 9,
    "MIN_PLOT_SIZE": 32,  # 32 for mainnet
    "MAX_PLOT_SIZE": 50,
    "SUB_SLOT_TIME_TARGET": 600,  # The target number of seconds per slot, mainnet 600
    "NUM_SP_INTERVALS_EXTRA": 3,  # The number of sp intervals to add to the signage point
    # The next block can have a timestamp of at most these many seconds in the future
    "MAX_FUTURE_TIME": 5 * 60,
    "NUMBER_OF_TIMESTAMPS": 11,  # Than the average of the last NUMBER_OF_TIMESTAMPS blocks
    # Used as the initial cc rc challenges, as well as first block back pointers, and first SES back pointer
    # We override this value based on the chain being run (testnet0, testnet1, mainnet, etc)
    # Default used for tests is std_hash(b'')
    "GENESIS_CHALLENGE": bytes.fromhex("15c1626e087d479980667bbdde8464b8cf737066c20622e520feaa096e9f9a3e"),
    # Forks of deafwave should change this value to provide replay attack protection. This is set to mainnet genesis chall
    "AGG_SIG_ME_ADDITIONAL_DATA": bytes.fromhex("299fc7442fd638bc739f7bdcff8ccad332e50f6f91556ad0c5267538f5421baa"),
    "GENESIS_POST_FARM_PUZZLE_HASH": bytes.fromhex(
        "95c259eaf17836095a7bfb5b1254b53c554985364c349f4a6764787c21d425ad"
    ),
    ## TODO: DELETE
    "GENESIS_PRE_FARM_POOL_PUZZLE_HASH": bytes.fromhex(
        "95c259eaf17836095a7bfb5b1254b53c554985364c349f4a6764787c21d425ad"
    ),
    "GENESIS_PRE_FARM_FARMER_PUZZLE_HASH": bytes.fromhex(
        "95c259eaf17836095a7bfb5b1254b53c554985364c349f4a6764787c21d425ad"
    ),
    "MAX_VDF_WITNESS_SIZE": 64,
    # Size of mempool = 50x the size of block
    "MEMPOOL_BLOCK_BUFFER": 50,
    # Max coin amount, fits into 64 bits
    "MAX_COIN_AMOUNT": uint64((1 << 64) - 1),
    # Max block cost in clvm cost units
    "MAX_BLOCK_COST_CLVM": 11000000000,
    # The cost per byte of generator program
    "COST_PER_BYTE": 12000,
    "WEIGHT_PROOF_THRESHOLD": 2,
    "BLOCKS_CACHE_SIZE": 4608 + (128 * 4),
    "WEIGHT_PROOF_RECENT_BLOCKS": 1000,
    "MAX_BLOCK_COUNT_PER_REQUESTS": 32,  # Allow up to 32 blocks per request
    "INITIAL_FREEZE_END_TIMESTAMP": 1620061200,  # Mon May 03 2021 17:00:00 GMT+0000
    "NETWORK_TYPE": 0,
    "MAX_GENERATOR_SIZE": 1000000,
    # Number of references allowed in the block generator ref list
    "MAX_GENERATOR_REF_LIST_SIZE": 512,
}


DEFAULT_CONSTANTS = ConsensusConstants(**testnet_kwargs)  # type: ignore
