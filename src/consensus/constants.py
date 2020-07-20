import dataclasses

from src.util.ints import uint64


@dataclasses.dataclass(frozen=True)
class ConsensusConstants:
    NUMBER_OF_HEADS: int
    DIFFICULTY_STARTING: int
    DIFFICULTY_FACTOR: int
    DIFFICULTY_EPOCH: int
    DIFFICULTY_WARP_FACTOR: int
    DIFFICULTY_DELAY: int  # EPOCH / WARP_FACTOR
    SIGNIFICANT_BITS: int  # The number of bits to look at in difficulty and min iters. The rest are zeroed
    DISCRIMINANT_SIZE_BITS: int  # Max is 1024 (based on ClassGroupElement int size)
    NUMBER_ZERO_BITS_CHALLENGE_SIG: int  # H(plot signature of the challenge) must start with these many zeroes
    BLOCK_TIME_TARGET: int  # The target number of seconds per block
    # The proportion (denominator) of the total time that that the VDF must be run for, at a minimum
    # (1/min_iters_proportion). For example, if this is two, approximately half of the iterations
    # will be contant and required for all blocks.
    MIN_ITERS_PROPORTION: int
    # For the first epoch, since we have no previous blocks, we can't estimate vdf iterations per second
    MIN_ITERS_STARTING: uint64
    MAX_FUTURE_TIME: int  # The next block can have a timestamp of at most these many seconds more
    NUMBER_OF_TIMESTAMPS: int  # Than the average of the last NUMBEBR_OF_TIMESTAMPS blocks
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

    def __post_init__(self):
        assert (
            self.DIFFICULTY_EPOCH == self.DIFFICULTY_DELAY * self.DIFFICULTY_WARP_FACTOR
        )

    def replace(self, **changes):
        return dataclasses.replace(self, **changes)


testnet_kwargs = {
    "NUMBER_OF_HEADS": 3,  # The number of tips each full node keeps track of and propagates
    # DIFFICULTY_STARTING is the starting difficulty for the first epoch, which is then further
    # multiplied by another factor of 2^32, to be used in the VDF iter calculation formula.
    "DIFFICULTY_STARTING": 2 ** 19,
    "DIFFICULTY_FACTOR": 3,  # The next difficulty is truncated to range [prev / FACTOR, prev * FACTOR]
    # These 3 constants must be changed at the same time
    "DIFFICULTY_EPOCH": 256,  # The number of blocks per epoch
    "DIFFICULTY_WARP_FACTOR": 4,  # DELAY divides EPOCH in order to warp efficiently.
    "DIFFICULTY_DELAY": 64,  # EPOCH / WARP_FACTOR
    "SIGNIFICANT_BITS": 12,  # The number of bits to look at in difficulty and min iters. The rest are zeroed
    "DISCRIMINANT_SIZE_BITS": 1024,  # Max is 1024 (based on ClassGroupElement int size)
    "NUMBER_ZERO_BITS_CHALLENGE_SIG": 8,  # H(plot signature of the challenge) must start with these many zeroes
    "BLOCK_TIME_TARGET": 300,  # The target number of seconds per block
    # The proportion (denominator) of the total time that that the VDF must be run for, at a minimum
    # (1/min_iters_proportion). For example, if this is two, approximately half of the iterations
    # will be contant and required for all blocks.
    "MIN_ITERS_PROPORTION": 10,
    # For the first epoch, since we have no previous blocks, we can't estimate vdf iterations per second
    "MIN_ITERS_STARTING": (2 ** 22),
    "MAX_FUTURE_TIME": 7200,  # The next block can have a timestamp of at most these many seconds more
    "NUMBER_OF_TIMESTAMPS": 11,  # Than the average of the last NUMBEBR_OF_TIMESTAMPS blocks
    # If an unfinished block is more than these many seconds slower than the best unfinished block,
    # don't propagate it.
    "PROPAGATION_THRESHOLD": 300,
    # If the expected time is more than these seconds, slightly delay the propagation of the unfinished
    # block, to allow better leaders to be released first. This is a slow block.
    "PROPAGATION_DELAY_THRESHOLD": 1500,
    # Hardcoded genesis block, generated using tests/block_tools.py
    # Replace this any time the constants change.
    "GENESIS_BLOCK": b'\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x95\xa4\xa44`\nqY(\xd5\xfc|\x17\xcfMX\xf0\xab\x87z\xbd\xc6/\x0c\x90\xa2n\xa0\x1dDQ1\x11\x874\xcaH\x85nX\x99\xb2\xf0:\xea\xcc1z\x8c(zk\xfd;\x19\xd5%\xae\xb5?S\xbc\xb4$\x8cm\xb1\x87U\x1d\xc1\xf7y\x90\xdb\x99H\xe7x\xa7h\xa8\x8c\x81\xf1\x91\xa7\xae\x92\xde\x8eN\xdf7\xb9\x89\x17\x00\x00\x00\xb8\xbb<\x1a\xc9\xdav\xf3U\xee\x81\xe1\x93\x14\xedn\xb1\xb1\xc2\xd1Xz\x0e\x8f\xff<.\xb4y\xaa\xbbT\x07\x04\xe2\xb4<\xeb\xff1\xdc\xe9o9\xcb\x7f\xd51l\xc4\xf0\xb7Vu\xc4^\xb0{\xb6\xa8\x90+-\xedK\xf0\xe4\xd6&\x96H\xce\x931\x9f\xba\x01\x026\xef\xb4-\xe3V>\xa8Sr\x1e\x05L\xbc\x00N\xddU$\xad\x88,Z\xa4\xd7\xf1+\xc1\x0b\x9d\xd1\x84krS\x9e>J\x12\x9c\x83T\x10\x1d:\x15\xc4\x84\xe7\x988+NgM\xd9\xeaa\x1a\xd8l\xcd\xc78rT\xeb.\xf2\xde\xb1\xf8\x03a\xb3)+Z\x95\xdd\xc4\xf7{M\xd4!\xe2\xd2\x01\x04t\xb8\x85\x9f#\x84h=\' \xad\xcb\xecW\x1a\xc4\x06\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00@&}\x00\x1f\xca&E\xb4\x8b\x12O1\xae\xa5\xe7nn\x9e\xe2\xb6\xb2\xf8|n\xb9O\xca\xe7\xe1o\xf7\xee^\x05B\xb3\x0c?S\xa7\xc7\xd3\x0b\xcf\xe2\x9e#\x94*\xac<\x05\xab\xc0\x99\xd5\xc3\x87l\xe8n\x8f^\x7f#\xe8\x9c\x00\x04[\x80\xda\x03f\xec1\xa4W\xe7Q\xd4\xdd\x92\x0c\xb9\xc4?:\x0f\xcc\xb3 \xc7@v^J\xbar\x10\x99\x12\xf0\xfd\xbc\xbc\x060\x9a\x9e\xee\nP\x8e\x98dQ\xc2\xa8?\xd5LN.\x02\x925\x91\x13\x83q\xe5\x00\x00\x00\x00\x82\x00n\x0b\x02\xab3\x98\xf5\xd8b\x99^\xb5\xa8\xf5\x1a\x8b"\xfc\x8bs\xb2\xa8\xa9\xc2\x97\xcb3\xbdEK^\xf8\x98\x0f\xa7\xbf\xa9\x16\xe5a\xf4O4z\x11\xd0\xf4\xb7Nn\x01\xed\xdc\xd4K\x8e?g)\x12\x1f\x82\xa7!\x00"\xb7=\xb3_h\xaf\xeb\x02\x9c\x82\xe0\xf4\xa7\xf1\xa4*\xe9\xa2\xf0\xdfN\x85L\x95\x00\xfa7\x14U\xb2&\xa8~\xafV\x1a\xa0P*\xb0\xa8\x05*)\x90\x9f\xae)J\r\xc1\xd8\xea\xcf\xac\x93\x8b\xf3\x99\x8a\t\x12\x8b\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00_\r\xe8Ox0\xd0\xc5\x07\xf578\xb3\xb1\x94\x06u\x9b\xe2\xe4\xd1\x8dy\xe9\xf9\xd9\xe0@\xc5\x94Rra\xc9\xdb\xb9\xdb\xa7\x90I\x1a& \xba!\xc4\x15\xc7\r\xb4\xebm\x02\xe2-\xb5@\x10\x1b\x99\x9fKM\x92\x03f/0\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x08\x00\x00\x00\x00\x00\x00\x00@&}\x02/\x0c}QHy\xe0\xb4>S\x0f-u6\xb9\xf8\x14l\xc4\xaf\xde5Y\xace\xafm\x9e\xe1@\'\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\xb2\x01\x07(\xde3\xeb<\xc8M\x7f\xd9{R\x0f\xf0\x87\x92\x89\x99\xd4{\xa3\xb4\xc9\x052\xe9\r\xb9T\xcb\x00\x00\x01\xd1\xa9J \x00\xb2\x01\x07(\xde3\xeb<\xc8M\x7f\xd9{R\x0f\xf0\x87\x92\x89\x99\xd4{\xa3\xb4\xc9\x052\xe9\r\xb9T\xcb\x00\x00\x00\x00\x81\x94\xcb\x15@w27\x92\x055\x15\xc6\xa6\x15\xbf\xb4H6\x1cmi\x9d\x1a\x04\xc3\x12z\xfd\xc3\xb8\xbb\xf5\x00[>\x89P\x82K:\x17\xa0\x83\xc3\xeb\xae\x91\x02\xb8\xb5!\x96\x92\xa0:\x8b\xbc\x0cs\x1fT\x80\xa8(\x12\xa4Y\x14t\xc3M\xc7\xf4\xa6\xb6\xf2\xfbd\xbf\xd7 Z\rsCB\xdd\xf5\xf1S4\xa80\xc6\xc5\x00\x00\x00\x00\x00\x00\x00\x00x\nA\x07\xb3\xd1\xc5H\xfb[\xd2]\xc7sI5\x82Tlp\x14\x17\x8a\xe4h\x05\x9d%\xf6AH\xbd\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x87\xde.\xeb\xe7Z\xe4\x97\xfd\xff\xe5\xdc\xbf\xe33\x9b\xe4N\xaa\xc1\xda5"\xac\x9an\xeaf8\x00\xc2*\x14\x95\x00B>!\x0e\xb5\xff\x97)y\xf3k \xbc\x01\xca^\xae\xae\x11\x15\xa40\xe1A\xa4PI\x05\x04\xbe\x0c\x04W{\x0b\x83k>\xd1\xd4\xadq\xf2Y\xb0W\xfc\xe1H\xb6\xc2Dy\xa0\xe6\x0e\xe6\x9e\xcd\xde\x0f\x00\x00\x00\x00\x04\x01sq\xa8',  # noqa: E501
    # Target tx count per sec
    "TX_PER_SEC": 20,
    # Size of mempool = 10x the size of block
    "MEMPOOL_BLOCK_BUFFER": 10,
    # Coinbase rewards are not spendable for 200 blocks
    "COINBASE_FREEZE_PERIOD": 200,
    # Max coin amount uint(1 << 64)
    "MAX_COIN_AMOUNT": 0xffffffffffffffff,
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
