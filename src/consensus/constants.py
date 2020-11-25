import dataclasses

from src.types.sized_bytes import bytes32
from src.util.ints import uint64, uint32


@dataclasses.dataclass(frozen=True)
class ConsensusConstants:
    SLOT_SUB_BLOCKS_TARGET: uint32
    MIN_SUB_BLOCKS_PER_CHALLENGE_BLOCK: uint32
    MAX_SLOT_SUB_BLOCKS: uint32
    NUM_SPS_SUB_SLOT: uint32
    SUB_SLOT_ITERS_STARTING: uint64

    DIFFICULTY_STARTING: uint64
    DIFFICULTY_FACTOR: uint32
    SUB_EPOCH_SUB_BLOCKS: uint32
    EPOCH_SUB_BLOCKS: uint32

    SIGNIFICANT_BITS: int  # The number of bits to look at in difficulty and min iters. The rest are zeroed
    DISCRIMINANT_SIZE_BITS: int  # Max is 1024 (based on ClassGroupElement int size)
    NUMBER_ZERO_BITS_PLOT_FILTER: int  # H(plot signature of the challenge) must start with these many zeroes
    SLOT_TIME_TARGET: int  # The target number of seconds per block
    NUM_SP_INTERVALS_EXTRA: int
    MAX_FUTURE_TIME: int  # The next block can have a timestamp of at most these many seconds more
    NUMBER_OF_TIMESTAMPS: int  # Than the average of the last NUMBER_OF_TIMESTAMPS blocks
    FIRST_CC_CHALLENGE: bytes
    FIRST_RC_CHALLENGE: bytes
    GENESIS_PRE_FARM_POOL_PUZZLE_HASH: bytes32
    GENESIS_PREV_HASH: bytes32
    GENESIS_SES_HASH: bytes32
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
