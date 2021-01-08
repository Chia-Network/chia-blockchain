import dataclasses

from src.types.sized_bytes import bytes32
from src.util.ints import uint64, uint32, uint8


@dataclasses.dataclass(frozen=True)
class ConsensusConstants:
    SLOT_SUB_BLOCKS_TARGET: uint32  # How many sub-blocks to target per sub-slot
    MIN_SUB_BLOCKS_PER_CHALLENGE_BLOCK: uint8  # How many sub-blocks must be created per slot (to make challenge sb)
    # Max number of sub-blocks that can be infused into a sub-slot.
    # Note: this must be less than SUB_EPOCH_SUB_BLOCKS/2, and > SLOT_SUB_BLOCKS_TARGET
    MAX_SUB_SLOT_SUB_BLOCKS: uint32
    NUM_SPS_SUB_SLOT: uint32  # The number of signage points per sub-slot (including the 0th sp at the sub-slot start)

    SUB_SLOT_ITERS_STARTING: uint64  # The sub_slot_iters for the first epoch
    DIFFICULTY_STARTING: uint64  # The difficulty for the first epoch
    DIFFICULTY_FACTOR: uint32  # The maximum factor by which difficulty and sub_slot_iters can change per epoch
    SUB_EPOCH_SUB_BLOCKS: uint32  # The number of sub-blocks per sub-epoch
    EPOCH_SUB_BLOCKS: uint32  # The number of sub-blocks per sub-epoch, must be a multiple of SUB_EPOCH_SUB_BLOCKS

    SIGNIFICANT_BITS: int  # The number of bits to look at in difficulty and min iters. The rest are zeroed
    DISCRIMINANT_SIZE_BITS: int  # Max is 1024 (based on ClassGroupElement int size)
    NUMBER_ZERO_BITS_PLOT_FILTER: int  # H(plot id + challenge hash + signage point) must start with these many zeroes
    MIN_PLOT_SIZE: int
    MAX_PLOT_SIZE: int
    SUB_SLOT_TIME_TARGET: int  # The target number of seconds per sub-slot
    NUM_SP_INTERVALS_EXTRA: int  # The difference between signage point and infusion point (plus required_iters)
    MAX_FUTURE_TIME: int  # The next block can have a timestamp of at most these many seconds more
    NUMBER_OF_TIMESTAMPS: int  # Than the average of the last NUMBER_OF_TIMESTAMPS blocks
    FIRST_CC_CHALLENGE: bytes32  # The "hash" of the "challenge chain end of slot" for the sub-slot before the 1st one
    FIRST_RC_CHALLENGE: bytes32  # The "hash" of the "reward chain end of slot" for the sub-slot before the 1st one
    GENESIS_PRE_FARM_POOL_PUZZLE_HASH: bytes32  # The block at height must pay out to this pool puzzle hash
    GENESIS_PREV_HASH: bytes32  # The prev sub-block and prev block of the genesis block
    GENESIS_SES_HASH: bytes32  # The sub epoch summary "hash" of the sub-epoch that end at height -
    MAX_VDF_WITNESS_SIZE: int  # The maximum number of classgroup elements within an n-wesolowski proof
    # Target tx count per sec
    TX_PER_SEC: int
    # Size of mempool = 10x the size of block
    MEMPOOL_BLOCK_BUFFER: int
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

    WEIGHT_PROOF_THRESHOLD: uint8
    WEIGHT_PROOF_RECENT_BLOCKS: uint32
    MAX_BLOCK_COUNT_PER_REQUESTS: uint32

    def replace(self, **changes):
        return dataclasses.replace(self, **changes)
