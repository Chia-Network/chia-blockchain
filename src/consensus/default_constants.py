from .constants import ConsensusConstants


testnet_kwargs = {
    # TODO(mariano): write comments here
    "SLOT_SUB_BLOCKS_TARGET": 32,
    "MIN_SUB_BLOCKS_PER_CHALLENGE_BLOCK": 16,
    "MAX_SUB_SLOT_SUB_BLOCKS": 128,
    "NUM_SPS_SUB_SLOT": 8,
    "SUB_SLOT_ITERS_STARTING": 2 ** 22,
    # DIFFICULTY_STARTING is the starting difficulty for the first epoch, which is then further
    # multiplied by another factor of 2^25, to be used in the VDF iter calculation formula.
    "DIFFICULTY_STARTING": 2 ** 14,
    "DIFFICULTY_FACTOR": 3,  # The next difficulty is truncated to range [prev / FACTOR, prev * FACTOR]
    # These 3 constants must be changed at the same time
    "SUB_EPOCH_SUB_BLOCKS": 128,  # The number of sub-blocks per sub-epoch, mainnet 284
    "EPOCH_SUB_BLOCKS": 256,  # The number of sub-blocks per epoch, mainnet 32256
    "SIGNIFICANT_BITS": 12,  # The number of bits to look at in difficulty and min iters. The rest are zeroed
    "DISCRIMINANT_SIZE_BITS": 1024,  # Max is 1024 (based on ClassGroupElement int size)
    "NUMBER_ZERO_BITS_PLOT_FILTER": 9,  # H(plot signature of the challenge) must start with these many zeroes
    "SUB_SLOT_TIME_TARGET": 600,  # The target number of seconds per slot, mainnet 600
    "NUM_SP_INTERVALS_EXTRA": 3,  # The number of sp intervals to add to the signage point
    "MAX_FUTURE_TIME": 7200,  # The next block can have a timestamp of at most these many seconds more
    "NUMBER_OF_TIMESTAMPS": 11,  # Than the average of the last NUMBER_OF_TIMESTAMPS blocks
    "FIRST_CC_CHALLENGE": bytes([0x00] * 32),
    "FIRST_RC_CHALLENGE": bytes([0x00] * 32),
    "GENESIS_PRE_FARM_POOL_PUZZLE_HASH": bytes.fromhex(
        "7a916bdc50d3d0337b0998668a4f439670339467d7e9039b8650ba7b1d4fc1a0"
    ),
    "GENESIS_PREV_HASH": bytes([0] * 32),
    "GENESIS_SES_HASH": bytes([0] * 32),
    "MAX_VDF_WITNESS_SIZE": 64,
    # Target tx count per sec
    "TX_PER_SEC": 20,
    # Size of mempool = 10x the size of block
    "MEMPOOL_BLOCK_BUFFER": 10,
    # Coinbase rewards are not spendable for 200 blocks
    "COINBASE_FREEZE_PERIOD": 200,
    # Max coin amount uint(1 << 64)
    "MAX_COIN_AMOUNT": 0xFFFFFFFFFFFFFFFF,
    # Raw size per block target = 1,000,000 bytes
    # Rax TX (single in, single out) = 219 bytes (not compressed)
    # TX = 457 vBytes
    # floor(1,000,000 / 219) * 457 = 2086662 (size in vBytes)
    # Max block cost in virtual bytes
    "MAX_BLOCK_COST": 2086662,
    # MAX block cost in clvm cost units = MAX_BLOCK_COST * CLVM_COST_RATIO_CONSTANT
    # 1 vByte = 108 clvm cost units
    "CLVM_COST_RATIO_CONSTANT": 108,
    # Max block cost in clvm cost units (MAX_BLOCK_COST * CLVM_COST_RATIO_CONSTANT)
    "MAX_BLOCK_COST_CLVM": 225359496,
    "WEIGHT_PROOF_THRESHOLD": 2,
}


DEFAULT_CONSTANTS = ConsensusConstants(**testnet_kwargs)  # type: ignore
