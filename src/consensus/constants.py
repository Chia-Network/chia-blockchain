import dataclasses


@dataclasses.dataclass(frozen=True)
class ConsensusConstants:
    SLOT_SUB_BLOCKS_TARGET: int
    MIN_SUB_BLOCKS_PER_CHALLENGE_BLOCK: int
    MAX_SLOT_SUB_BLOCKS: int
    NUM_CHECKPOINTS_PER_SLOT: int
    IPS_STARTING: int

    DIFFICULTY_STARTING: int
    DIFFICULTY_FACTOR: int
    SUB_EPOCH_SUB_BLOCKS: int
    EPOCH_SUB_BLOCKS: int

    SIGNIFICANT_BITS: int  # The number of bits to look at in difficulty and min iters. The rest are zeroed
    DISCRIMINANT_SIZE_BITS: int  # Max is 1024 (based on ClassGroupElement int size)
    NUMBER_ZERO_BITS_PLOT_FILTER: int  # H(plot signature of the challenge) must start with these many zeroes
    NUMBER_ZERO_BITS_ICP_FILTER: int  # H(plot signature of the sp) must start with these many zeroes
    SLOT_TIME_TARGET: int  # The target number of seconds per block
    EXTRA_ITERS_TIME_TARGET: float
    MAX_FUTURE_TIME: int  # The next block can have a timestamp of at most these many seconds more
    NUMBER_OF_TIMESTAMPS: int  # Than the average of the last NUMBER_OF_TIMESTAMPS blocks
    # If an unfinished block is more than these many seconds slower than the best unfinished block,
    # don't propagate it.
    PROPAGATION_THRESHOLD: int
    # If the expected time is more than these seconds, slightly delay the propagation of the unfinished
    # block, to allow better leaders to be released first. This is a slow block.
    PROPAGATION_DELAY_THRESHOLD: int
    # Hardcoded genesis block, generated using tests/block_tools.py
    # Replace this any time the constants change.
    FIRST_CC_CHALLENGE: bytes
    FIRST_RC_CHALLENGE: bytes
    GENESIS_PRE_FARM_PUZZLE_HASH: bytes
    MAX_VDF_WITNESS_SIZE: int
    # Target tx count per sec
    TX_PER_SEC: int
    # Size of mempool = 10x the size of block
    MEMPOOL_BLOCK_BUFFER: int
    # Coinbase rewards are not spendable for 200 blocks
    COINBASE_FREEZE_PERIOD: int
    # Max coin amount uint(1 << 64)
    MAX_COIN_AMOUNT: int
    # Raw size per block target = 1,000,000 bytes
    # Rax TX (single in, single out) = 219 bytes (not compressed)
    # TX = 457 vBytes
    # floor(1,000,000 / 219) * 457 = 2086662 (size in vBytes)
    # Max block cost in virtual bytes
    MAX_BLOCK_COST: int
    # MAX block cost in clvm cost units = MAX_BLOCK_COST * CLVM_COST_RATIO_CONSTANT
    # 1 vByte = 108 clvm cost units
    CLVM_COST_RATIO_CONSTANT: int
    # Max block cost in clvm cost units (MAX_BLOCK_COST * CLVM_COST_RATIO_CONSTANT)
    MAX_BLOCK_COST_CLVM: int

    def replace(self, **changes):
        return dataclasses.replace(self, **changes)
