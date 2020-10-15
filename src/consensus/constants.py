import dataclasses

from src.util.ints import uint64


@dataclasses.dataclass(frozen=True)
class ConsensusConstants:
    SLOT_SUB_BLOCKS_TARGET: int
    MIN_SUB_BLOCKS_PER_CHALLENGE_BLOCK: int
    MAX_SLOT_SUB_BLOCKS: int
    NUM_CHECKPOINTS_PER_SLOT: int
    EXTRA_ITERS_SLOT_FACTOR: int
    SLOT_ITERS_STARTING: int

    DIFFICULTY_STARTING: int
    DIFFICULTY_FACTOR: int
    SUB_EPOCH_SUB_BLOCKS: int
    EPOCH_SUB_BLOCKS: int

    SIGNIFICANT_BITS: int  # The number of bits to look at in difficulty and min iters. The rest are zeroed
    DISCRIMINANT_SIZE_BITS: int  # Max is 1024 (based on ClassGroupElement int size)
    NUMBER_ZERO_BITS_CHALLENGE_SIG: int  # H(plot signature of the challenge) must start with these many zeroes
    SLOT_TIME_TARGET: int  # The target number of seconds per block
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
    GENESIS_BLOCK: bytes
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


testnet_kwargs = {
    "SLOT_SUB_BLOCKS_TARGET": 16,
    "MIN_SUB_BLOCKS_PER_CHALLENGE_BLOCK": 5,
    "MAX_SLOT_SUB_BLOCKS": 64,
    "NUM_CHECKPOINTS_PER_SLOT": 32,
    "EXTRA_ITERS_SLOT_FACTOR": 8,
    "SLOT_ITERS_STARTING": 180000000,
    # DIFFICULTY_STARTING is the starting difficulty for the first epoch, which is then further
    # multiplied by another factor of 2^32, to be used in the VDF iter calculation formula.
    "DIFFICULTY_STARTING": 2 ** 20,
    "DIFFICULTY_FACTOR": 3,  # The next difficulty is truncated to range [prev / FACTOR, prev * FACTOR]
    # These 3 constants must be changed at the same time
    "SUB_EPOCH_SUB_BLOCKS": 128,  # The number of sub-blocks per sub-epoch, mainnet 284
    "EPOCH_SUB_BLOCKS": 4096,  # The number of sub-blocks per epoch, mainnet 32256
    "SIGNIFICANT_BITS": 12,  # The number of bits to look at in difficulty and min iters. The rest are zeroed
    "DISCRIMINANT_SIZE_BITS": 1024,  # Max is 1024 (based on ClassGroupElement int size)
    "NUMBER_ZERO_BITS_CHALLENGE_SIG": 8,  # H(plot signature of the challenge) must start with these many zeroes
    "SLOT_TIME_TARGET": 300,  # The target number of seconds per slot
    "MAX_FUTURE_TIME": 7200,  # The next block can have a timestamp of at most these many seconds more
    "NUMBER_OF_TIMESTAMPS": 11,  # Than the average of the last NUMBER_OF_TIMESTAMPS blocks
    # If an unfinished block is more than these many seconds slower than the best unfinished block,
    # don't propagate it.
    "PROPAGATION_THRESHOLD": 300,
    # If the expected time is more than these seconds, slightly delay the propagation of the unfinished
    # block, to allow better leaders to be released first. This is a slow block.
    "PROPAGATION_DELAY_THRESHOLD": 1500,
    # Hardcoded genesis block, generated using tests/block_tools.py
    # Replace this any time the constants change.
    "GENESIS_BLOCK": b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x81\x8f\x0c\xec\x97\x85V`C\xfc\xe4\xf9A\xb6\xa1\xa8-@\x82`\r[v\x8f,\x86\xf1X\xc2?\xf6q\xf8\xfb\x8e\rnZ\xbaw\x11CN\xb1\xa9\xf9\xbb0\x93\x10\x8fc\xc3f&\x9b\x07>H\xf1\xa5\x841\xc8\xd9\xcaO\xd4\xb8\x93\x11\xa3\xd9\xfa\xb2U\x10\xcd\xec\x92*AA\xd9\xfd7\xcc\xf7]\xaf\x91V\xe3\x10\x1aa\x17\x00\x00\x00\xb8`\xbfL[I\x16\xd5\x01>\tw>S\xf0#8\xed\xc6\x88\xc5#=i2\x0c\x8d\xbe\x85\xeb\x8f\xee\x1b\x06a\x99\x1c\xba\xfa\xcba\xe6\x04Q\xf4\xc7\xe92RrU l\x01\xee 7)\xff\xa5\xa68\xb5\x10\xbbrQb\xb0\x01'K\xf1\x07).Z.')\xee`b\xab\x01\xa9\x82S\x91\x16\x9c\x96\x95\xaf\xe5\xe5\xca\xb7@\x03\xf4$\x87\xe6N\xd3\xfb\xd39Y4D\x91\xed\x14\xda4\xa8\xbfO@\xb4\xd3\x8d\xa9\x9f\xc5\xd4\xf1`o\x9bg\x81\x12\xb0i\xdfJ\xeb*\xd2*`\x95\xf0\xd0j\xa4\x8e\xa6\xcf\xaaHn\xd9\xfe_\xc9\xd9\x85\x8a\xa5\xe8\x1c\x9dk\xc5\xf0\xda\xfe\xd7R\xb5\xbe\x1e\xe0qw\x7f}x\xa7\xa6[\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00P\xa2\xa9\x00cN 4\xf5\xb9]\xefu\t\x1a\x92\x85\xd0,\x8e\xca5\xff7N\xb3N-\x94-\xb4\xa3q[\xfd\xf0\x0b4\x8a/&#v\x19Y\\\xf8\x83o\x1b\x1b\x85\xe18\xbd\xce\xd5\x98\x11r\xaa\xd8\x1d8\xbe<Q\x9e\x00\x17sy\x96\x19\x86Go<\x1a\xa1\x94\xc6\xd2\xea\xe1~\xc4\xc8\xf6 \x83}(\xce\x86\xea\xbd\xc0\xe0\xc8_9\xe1`S\xbeZ\xc4y\x1d\xebx\xa1\x1e\"g\x16\xbbC\x0b\rhkU\x13\xf2i^[\xa8t(\x95\x00\x00\x00\x00\x82\x00F\x129)\x8a>[/\x8b\xbb\xa4\xf0\x86\x10\x93\x9b\x05\xd1\x1c$\xfc\xae\xbbI\xa8\x835Qj\xba\x87E\xf8a5t\x81i\xa6Lm\x82\xc5#C!\\f\xc5\x18\x80\x97y\xd5P\xe42\xa0\x15\x8b 6\x19l\x00\x18\xb9-\x85\x15\x9c\xed\xe4\xf2\x83j\x8d^\xca&/\xf6X@P\x8eC,\xaea\x85\x0c\xa66\x16,F\xf8\x07V\xf8\x83\xd3\x18\xd2R\xdf\xf8:\x8f\n\x85\xa6'\xb5\x8bt%\xf5\xbaz\x03\x01\x1a\xa5\xd6m\x10\xcb\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00_Y\xda\xc6Z\xb0?\x8fN^\x06\\w#Y\xc3n\xb4\x083\x1d\x01\xb4\xd8Y\xbb\xcf\xa9\xd8\t\x8a8N\xe5a\xa2\x0e\x0cM\xe8Kj\xfb99\xd4\x02\xca\xa2\x14\n\xf4\xafB%\xbf\xf8;\x83\xd7\xee&RS\x8e\x0b\xab\xfc\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x10\x00\x00\x00\x00\x00\x00\x00P\xa2\xa9\x8c-\x02\x9a\xb0\x08s^m1Z\xf5\x0f\xa7\x1d\x87`|\x92\xeb\x07\xb9\xaa\x90\xc1\xefz\xa2\x10\xf4\xf2\x8d\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00z\x91k\xdcP\xd3\xd03{\t\x98f\x8aOC\x96p3\x94g\xd7\xe9\x03\x9b\x86P\xba{\x1dO\xc1\xa0\x00\x00\x01\xd1\xa9J \x00z\x91k\xdcP\xd3\xd03{\t\x98f\x8aOC\x96p3\x94g\xd7\xe9\x03\x9b\x86P\xba{\x1dO\xc1\xa0\x00\x00\x00\x00\xa8\x81\xb2#\xdf'\xe1\x14\x94p\xa6\xd2\xa4\xe6\x0c\xf7\xd3\x0b9\xdf3C\xf8'\x98\xeb\xaf\xe8\xeef\xe5\xa8w\xd2\x94h?\x00\xe1\xb0\xd6\xee\x9a\xcb\xbeNM\x80\x17\xca(?o\xf5J\xa8\x9c\xf1\xb7\xd2\x87/\x9f\xb6\x18\xee\xf2\xf6\xcb*\xbc\xb7D\xb7\xf8\xaf\x9b\x99\xe1Z\xb0\x05\xbe\xdf\x85\x10\x0eS\x98\xd1\x14\x1b\xcf\xfe\xa5\xe0\x00\x00\x00\x00\x00\x00\x00\x00\xa1\x999\xae\xe9\xf1n\xc1\xc1\xc6q<\xe97%_\x1e\x1b\xd0>\xcd\xa8\x94\xd8;\xe4\x9f\xa7\xb1V\xa5Q\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x92.\xa5X;>\x8d\x90!Op[q\x90g\xdc,\xee\x1b!\xb7hI\x06q\xf9mq3\xd7,\xb6\x1f,qf\xa3\xdf \x8ac\xbf\x91p\xb1\xd6\xe0\x87\x0cJ\xa0\xb22z?X\x90\x0e\xa9\x85@\x0b\x90\t\x84\xd1e\xd9f\xb9U\x11\xfa+\xa2\xc8+\xa3\x0e\xdf\xcc\x04\x94\xdaC\x1c\xea\xf6\xd5\x18n\x00\x15\xa5S\x11\x00\x00\x00\x00\x04\x01A\xbap",  # noqa: E501
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
}


constants = ConsensusConstants(**testnet_kwargs)  # type: ignore
