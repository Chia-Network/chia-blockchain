import dataclasses
import logging

from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.byte_types import hexstr_to_bytes
from chia.util.ints import uint8, uint32, uint64, uint128

log = logging.getLogger(__name__)


@dataclasses.dataclass(frozen=True)
class ConsensusConstants:
    SLOT_BLOCKS_TARGET: uint32  # How many blocks to target per sub-slot
    MIN_BLOCKS_PER_CHALLENGE_BLOCK: uint8  # How many blocks must be created per slot (to make challenge sb)
    # Max number of blocks that can be infused into a sub-slot.
    # Note: this must be less than SUB_EPOCH_BLOCKS/2, and > SLOT_BLOCKS_TARGET
    MAX_SUB_SLOT_BLOCKS: uint32
    NUM_SPS_SUB_SLOT: uint32  # The number of signage points per sub-slot (including the 0th sp at the sub-slot start)

    SUB_SLOT_ITERS_STARTING: uint64  # The sub_slot_iters for the first epoch
    DIFFICULTY_CONSTANT_FACTOR: uint128  # Multiplied by the difficulty to get iterations
    DIFFICULTY_STARTING: uint64  # The difficulty for the first epoch
    # The maximum factor by which difficulty and sub_slot_iters can change per epoch
    DIFFICULTY_CHANGE_MAX_FACTOR: uint32
    SUB_EPOCH_BLOCKS: uint32  # The number of blocks per sub-epoch
    EPOCH_BLOCKS: uint32  # The number of blocks per sub-epoch, must be a multiple of SUB_EPOCH_BLOCKS

    SIGNIFICANT_BITS: int  # The number of bits to look at in difficulty and min iters. The rest are zeroed
    DISCRIMINANT_SIZE_BITS: int  # Max is 1024 (based on ClassGroupElement int size)
    NUMBER_ZERO_BITS_PLOT_FILTER: int  # H(plot id + challenge hash + signage point) must start with these many zeroes
    MIN_PLOT_SIZE: int
    MAX_PLOT_SIZE: int
    SUB_SLOT_TIME_TARGET: int  # The target number of seconds per sub-slot
    NUM_SP_INTERVALS_EXTRA: int  # The difference between signage point and infusion point (plus required_iters)
    MAX_FUTURE_TIME: int  # The next block can have a timestamp of at most these many seconds more
    NUMBER_OF_TIMESTAMPS: int  # Than the average of the last NUMBER_OF_TIMESTAMPS blocks
    # Used as the initial cc rc challenges, as well as first block back pointers, and first SES back pointer
    # We override this value based on the chain being run (testnet0, testnet1, mainnet, etc)
    GENESIS_CHALLENGE: bytes32
    # Forks of chia should change this value to provide replay attack protection
    AGG_SIG_ME_ADDITIONAL_DATA: bytes
    GENESIS_PRE_FARM_POOL_PUZZLE_HASH: bytes32  # The block at height must pay out to this pool puzzle hash
    GENESIS_PRE_FARM_FARMER_PUZZLE_HASH: bytes32  # The block at height must pay out to this farmer puzzle hash
    MAX_VDF_WITNESS_SIZE: int  # The maximum number of classgroup elements within an n-wesolowski proof
    # Size of mempool = 10x the size of block
    MEMPOOL_BLOCK_BUFFER: int
    # Max coin amount uint(1 << 64). This allows coin amounts to fit in 64 bits. This is around 18M chia.
    MAX_COIN_AMOUNT: int
    # Max block cost in clvm cost units
    MAX_BLOCK_COST_CLVM: int
    # Cost per byte of generator program
    COST_PER_BYTE: int

    WEIGHT_PROOF_THRESHOLD: uint8
    WEIGHT_PROOF_RECENT_BLOCKS: uint32
    MAX_BLOCK_COUNT_PER_REQUESTS: uint32
    BLOCKS_CACHE_SIZE: uint32
    NETWORK_TYPE: int
    MAX_GENERATOR_SIZE: uint32
    MAX_GENERATOR_REF_LIST_SIZE: uint32
    POOL_SUB_SLOT_ITERS: uint64
    SOFT_FORK_HEIGHT: uint32

    def replace(self, **changes) -> "ConsensusConstants":
        return dataclasses.replace(self, **changes)

    def replace_str_to_bytes(self, **changes) -> "ConsensusConstants":
        """
        Overrides str (hex) values with bytes.
        """

        filtered_changes = {}
        for k, v in changes.items():
            if not hasattr(self, k):
                log.warn(f'invalid key in network configuration (config.yaml) "{k}". Ignoring')
                continue
            if isinstance(v, str):
                filtered_changes[k] = hexstr_to_bytes(v)
            else:
                filtered_changes[k] = v

        return dataclasses.replace(self, **filtered_changes)
