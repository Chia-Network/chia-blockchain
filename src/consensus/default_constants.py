from .constants import ConsensusConstants
from ..types.sized_bytes import bytes32

testnet_kwargs = {
    "SLOT_SUB_BLOCKS_TARGET": 32,
    "MIN_SUB_BLOCKS_PER_CHALLENGE_BLOCK": 12,  # Must be less than half of SLOT_SUB_BLOCKS_TARGET
    "MAX_SUB_SLOT_SUB_BLOCKS": 128,  # Must be less than half of SUB_EPOCH_SUB_BLOCKS
    "NUM_SPS_SUB_SLOT": 64,  # Must be a power of 2
    "SUB_SLOT_ITERS_STARTING": 2 ** 25,
    # DIFFICULTY_STARTING is the starting difficulty for the first epoch, which is then further
    # multiplied by another factor of 2^25, to be used in the VDF iter calculation formula.
    "DIFFICULTY_STARTING": 2 ** 24,
    "DIFFICULTY_FACTOR": 3,  # The next difficulty is truncated to range [prev / FACTOR, prev * FACTOR]
    # These 3 constants must be changed at the same time
    "SUB_EPOCH_SUB_BLOCKS": 384,  # The number of sub-blocks per sub-epoch, mainnet 284
    "EPOCH_SUB_BLOCKS": 384 * 2,  # The number of sub-blocks per epoch, mainnet 32256. Must be multiple of SUB_EPOCH_SB
    "SIGNIFICANT_BITS": 12,  # The number of bits to look at in difficulty and min iters. The rest are zeroed
    "DISCRIMINANT_SIZE_BITS": 1024,  # Max is 1024 (based on ClassGroupElement int size)
    "NUMBER_ZERO_BITS_PLOT_FILTER": 9,  # H(plot signature of the challenge) must start with these many zeroes
    "MIN_PLOT_SIZE": 18,  # 32 for mainnet
    "MAX_PLOT_SIZE": 59,
    "SUB_SLOT_TIME_TARGET": 600,  # The target number of seconds per slot, mainnet 600
    "NUM_SP_INTERVALS_EXTRA": 3,  # The number of sp intervals to add to the signage point
    "MAX_FUTURE_TIME": 7200,  # The next block can have a timestamp of at most these many seconds more
    "NUMBER_OF_TIMESTAMPS": 11,  # Than the average of the last NUMBER_OF_TIMESTAMPS blocks
    # Used as the initial cc rc challenges, as well as first block back pointers, and first SES back pointer
    # We override this value based on the chain being run (testnet0, testnet1, mainnet, etc)
    "GENESIS_CHALLENGE": bytes32([0x00] * 32),
    "GENESIS_PRE_FARM_POOL_PUZZLE_HASH": bytes.fromhex(
        "23b039a829f3ed14a260355b9fc55d9ccc4539f05bd4bf529fd2630de1751d52"
    ),
    "GENESIS_PRE_FARM_FARMER_PUZZLE_HASH": bytes.fromhex(
        "23b039a829f3ed14a260355b9fc55d9ccc4539f05bd4bf529fd2630de1751d52"
    ),
    "MAX_VDF_WITNESS_SIZE": 64,
    # Target tx count per sec
    "TX_PER_SEC": 20,
    # Size of mempool = 10x the size of block
    "MEMPOOL_BLOCK_BUFFER": 10,
    # Max coin amount uint(1 << 64)
    "MAX_COIN_AMOUNT": 0xFFFFFFFFFFFFFFFF,
    # Targeting twice bitcoin's block size of 1.3MB per block
    # Raw size per block target = 1,300,000 * 600 / 47 = approx 100 KB
    # Rax TX (single in, single out) = 219 bytes (not compressed)
    # TX = 457 vBytes
    # floor(100 * 1024 / 219) * 457 = 213684 (size in vBytes)
    # Max block cost in virtual bytes
    "MAX_BLOCK_COST": 213684,
    # MAX block cost in clvm cost units = MAX_BLOCK_COST * CLVM_COST_RATIO_CONSTANT
    # 1 vByte = 108 clvm cost units
    "CLVM_COST_RATIO_CONSTANT": 108,
    # Max block cost in clvm cost units (MAX_BLOCK_COST * CLVM_COST_RATIO_CONSTANT)
    "MAX_BLOCK_COST_CLVM": 23077872,
    "WEIGHT_PROOF_THRESHOLD": 2,
    "SUB_BLOCKS_CACHE_SIZE": 5000,  # todo almog SUB_BLOCKS_CACHE_SIZE = EPOCH_SUB_BLOCKS + 3*MAX_SUB_SLOT_SUB_BLOCKS"
    "WEIGHT_PROOF_RECENT_BLOCKS": 800,
    "MAX_BLOCK_COUNT_PER_REQUESTS": 32,  # Allow up to 32 blocks per request
    "INITIAL_FREEZE_PERIOD": 10000,  # Transaction are disabled first 10000 sub blocks
}


DEFAULT_CONSTANTS = ConsensusConstants(**testnet_kwargs)  # type: ignore
