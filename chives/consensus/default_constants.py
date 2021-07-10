from chives.util.ints import uint64

from .constants import ConsensusConstants

testnet_kwargs = {
    "SLOT_BLOCKS_TARGET": 32,
    "MIN_BLOCKS_PER_CHALLENGE_BLOCK": 16,  # Must be less than half of SLOT_BLOCKS_TARGET
    "MAX_SUB_SLOT_BLOCKS": 128,  # Must be less than half of SUB_EPOCH_BLOCKS
    "NUM_SPS_SUB_SLOT": 64,  # Must be a power of 2
    "SUB_SLOT_ITERS_STARTING": 2 ** 27,
    # DIFFICULTY_STARTING is the starting difficulty for the first epoch, which is then further
    # multiplied by another factor of DIFFICULTY_CONSTANT_FACTOR, to be used in the VDF iter calculation formula.
    "DIFFICULTY_CONSTANT_FACTOR": 2 ** 57,
    "DIFFICULTY_STARTING": 7,
    "DIFFICULTY_CHANGE_MAX_FACTOR": 3,  # The next difficulty is truncated to range [prev / FACTOR, prev * FACTOR]
    # These 3 constants must be changed at the same time
    "SUB_EPOCH_BLOCKS": 384,  # The number of blocks per sub-epoch, mainnet 384
    "EPOCH_BLOCKS": 4608,  # The number of blocks per epoch, mainnet 4608. Must be multiple of SUB_EPOCH_SB
    "SIGNIFICANT_BITS": 8,  # The number of bits to look at in difficulty and min iters. The rest are zeroed
    "DISCRIMINANT_SIZE_BITS": 1024,  # Max is 1024 (based on ClassGroupElement int size)
    "NUMBER_ZERO_BITS_PLOT_FILTER": 9,  # H(plot signature of the challenge) must start with these many zeroes
    "MIN_PLOT_SIZE": 29,  # 32 for mainnet
    "MAX_PLOT_SIZE": 31,
    "SUB_SLOT_TIME_TARGET": 600,  # The target number of seconds per slot, mainnet 600
    "NUM_SP_INTERVALS_EXTRA": 3,  # The number of sp intervals to add to the signage point
    "MAX_FUTURE_TIME": 5 * 60,  # The next block can have a timestamp of at most these many seconds in the future
    "NUMBER_OF_TIMESTAMPS": 11,  # Than the average of the last NUMBER_OF_TIMESTAMPS blocks
    # Used as the initial cc rc challenges, as well as first block back pointers, and first SES back pointer
    # We override this value based on the chain being run (testnet0, testnet1, mainnet, etc)
    # Default used for tests is std_hash(b'')
    "GENESIS_CHALLENGE": bytes.fromhex("e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"),
    # Forks of chives should change this value to provide replay attack protection. This is set to mainnet genesis chall
    "AGG_SIG_ME_ADDITIONAL_DATA": bytes.fromhex("69cfa80789667c51428eaf2f2126e6be944462ee5b59b8128e90b9a650f865c1"),
    "GENESIS_PRE_FARM_POOL_PUZZLE_HASH": bytes.fromhex(
        "6d13b5296e6e7e2307c79294053b2fc49899cdc0e105beb7d2d4fac875c94bd1"
    ),
    "GENESIS_PRE_FARM_FARMER_PUZZLE_HASH": bytes.fromhex(
        "8fc4ed983203c84ec9f15eedafc96cb8646825bc1049e05209005453285135a5"
    ),
    "GENESIS_PRE_FARM_COMMUNITY_PUZZLE_HASH": bytes.fromhex(
        "4e7d87c3752c0b4a1f25ec7ac5c10f347c39406e6753220043f28e5a450e0388"
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
    "INITIAL_FREEZE_END_TIMESTAMP": 1625600000,  # 2021-07-07 03:33:20 GMT+8000
    "NETWORK_TYPE": 0,
    "MAX_GENERATOR_SIZE": 1000000,
    "MAX_GENERATOR_REF_LIST_SIZE": 512,  # Number of references allowed in the block generator ref list
}


DEFAULT_CONSTANTS = ConsensusConstants(**testnet_kwargs)  # type: ignore