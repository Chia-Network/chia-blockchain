import dataclasses


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
    MIN_ITERS_STARTING: int
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
    MAX_COIN_AMOUNT: bytes
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

    def __getitem__(self, key):
        # TODO: remove this
        # temporary, for compatibility
        v = getattr(self, key, None)
        return v

    def copy(self):
        # TODO: remove this
        # temporary, for compatibility
        return dataclasses.asdict(self)

    def replace(self, **changes):
        return dataclasses.replace(self, **changes)


testnet_kwargs = {
    "NUMBER_OF_HEADS": 3,  # The number of tips each full node keeps track of and propagates
    # DIFFICULTY_STARTING is the starting difficulty for the first epoch, which is then further
    # multiplied by another factor of 2^32, to be used in the VDF iter calculation formula.
    "DIFFICULTY_STARTING": 2 ** 15,
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
    "MIN_ITERS_STARTING": (2 ** 20),
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
    "GENESIS_BLOCK": b'\x00\x00Q\x16\x16\x16\x16\x16\x16\x16\x16\x16\x16\x16\x16\x16\x16\x16\x16\x16\x16\x16\x16\x16\x16\x16\x16\x16\x16\x16\x16\x16\x8d\xd5D\xaf\xf6\x90\xf7Ac\xff\x00[9\x1b\x8dI\xeb\xcb\xf5\xa9\xb2qK\\\xfb\x01\xb4R\xff\x07|a\xae\x03\xee/(\xb0\xe5\x01\x98\x01\xa7\xe6\xeb\xfd\xf2.\xa6\t_\xd9\xe4\x00\xa9_\xe3\x9a\xfc[M\x04\xd3\xa82\x94\xe1H\xd7;Q\xb4\x9c"i?\xd9\xf9\xa95\xb8\xd2j\xe1\x11\x11\x06\x16l\xf6I\xd1\xedl\x8c\xa9\x12\x00\x00\x00\x90\xb5=\xe9\r\xe8\x01#\xac\xaa\x04\xdd\xf7RF\xcc"[\x91\x93\xad0\x14\xe2\xb8(\x1a\xe8Z\xa0\xad\x07\xcb]\xd8\x05uu\t0\xfc\xc8\x8a\xf1\xab*\xe8\x05-l\x98]\xd9g\x81\xa8\xd1\x96{\x009)\xf0\x9c\x04b\xef\xach\x851\x90\x15KT\\\xe4\x9f\xf5\x82:$\xde\x13\xe8j\x12\xae\x878N\x8dN\xa4(\xff]\xf65:.\xcaH\x1f\xec\xc6\xde\x14\t\t\xb9\x8e\xa5\x16\x93\xe9\xae\x01ibh\xff\x06\xefXr\x93\xa8#\xb40\x05-\x07\xfdu3\xb309\x00\xbf|"\x83\x01\x00\x00Q\x16\x16\x16\x16\x16\x16\x16\x16\x16\x16\x16\x16\x16\x16\x16\x16\x16\x16\x16\x16\x16\x16\x16\x16\x16\x16\x16\x16\x16\x00\x00\x00\x00\x00\xd5\xc9\x82\x00\x14\xe9\xd0\x16\x83a\xf6$6\xc2\x92o\xc3\xdf\xda~J\xcae\x06\x00b\xde\x1b[\xb8>>\xc1\xc8\xfc1\xe2\xeff1\x1e\xeed\xaa\xc4\xa2\xf3\x94\xd4W\xec\xe8\x8f\xc3u\xdd\xddp\x97\xa5\xd9o"\xad\xbf;\xcap\xff\xef\xe3U\xad\xaa\xb1!\xc5&g\xd6,\xd4\x16\xdd\x7f\xf5\xd5\\\xdf\xd3\x80,\xaba\x98\xa6@\xa2A\x8c\tD\xe6`\x8c\xb8\x1b\x84\xa1\x18A!a\x13\x96\xce\x18\x92\xbbm\xc8\x9f\xcc\xb7\xa9|7\xa0\xefY\x9bQ\xad\x00\x00\x00\x00\x82\x004\xeb\xa5\xfc\x12Y\x95\x0bl\xf8\xcd\xe3Vy\xd83\xb0\r\xd3h\xea1J\x88\xe1\x1d\x18\xccv\x1dp\'p\xa2\xec\x16\xca\x8a\xc6\x08ab\xd7\'\xfc\xd0\x9ax\xe8\x90T"\xe9\xaf\xe7&-\x15\xd8\xcb\xaa\x04\x92\x0c\xff\xe2\xae5\xb9\x0b\x95\x11C\xe7\x86cY\x86:\x86Uu\xc4aK\x1b\x98\x9c\xb3`\xc5ur\x0c\xec\xf0G\x1f\x9d\xbb\x86jO\xe7]D7U,\xccu\x83\xb1\x9a\x8bX\xa3\xfb\xf4D\x00V\x9a\xf1\x1aP\xc4Te\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00_\x0cy\xbc\xd8)\x8e\x0e\xe4\xe4_Ac\xc1\x9d\x16z\x13[\xd4\\*Fy\xd6\xa7Z\xfb\xea\x9b[\x8d\x185Q\xa0FMz\xcf\x9ay\xb9\xcaT\x8bW}\xa7F\x9b\xc8\x9b_,\xb4s\xdb\x15\xb5\xa4k\x82%\x97\xec\xb6\xd1\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x80\x00\x00\x00\x00\x00\x00\xd5\xc9\x82\xab\x80\xcb\xf0\x0b\xf3w\xe1\x14\xe4\xef\x85o\x82\xa6\x97\x0b\xa8\x1e\x94S\xa4\xb9D\xa2\xe5`l\xaeL\xbbz\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x000\x94B\x19af\x95\xe4\x8fz\x9bT\xb3\x88w\x10J\x1f_\xbe\x85\xc6\x1d\xa2\xfb\xe3RuA\x8ad\xbc\x00\x00\x01\xd1\xa9J \x000\x94B\x19af\x95\xe4\x8fz\x9bT\xb3\x88w\x10J\x1f_\xbe\x85\xc6\x1d\xa2\xfb\xe3RuA\x8ad\xbc\x00\x00\x00\x00\xa4_\xca9\x18\x13l\x8d>\xc9\xb3n\xac2?\xf9\xb7\t\xf1\xe1\xaa:\xe9\x01[\\\xfb\xce\x91\xa4@\xc4\xd6\xf3\x0f\xc5\x06\xdc\xd8I\x1f$k\x0e\xf4\x05\x8c\x9f\xb9\x9bD[\xbc\x90e0\x17m+z\xd6\x84b9\xa6\xcb\xa56\xcf\xacj\x02\xf3D\x7f:^\x9c\x8e\x96,\xd7\x83\xee\xf1\\\xce9\xf3\x8a\x1f\x96\x16\x9c\x1d3\x00\x00\x00\x00\x00\x00\x00\x00(\xfc\xe5\xe3\x17\x8e\'\xb3\xb4\xc8T\xd6+\x0e\xbe0S\xc8\xd6^--\xbeD\x8a-c\x8f\xb4\xc0\xda\x08\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\xaa\x96Ae\xaa3\x92\xe6t\xa6~\x83\x7fh\xaf\x16\xfc-X2#w~\x17\x94-j\xb9\x82\xa6\x1b>\x80u\x1bb\xea\xf7\x94&`zN\xf4yK\xf4\xff\xa6\xaf\xa8zv\x1c\xa7\x87n\xd7f2\xb8\xda\xfdv~\xb6\xae\xe0\x18\x9d\xb0g\xf4\xea\x96ozN\x1c\xb8\xc9\xa1\x97\x8d#\xfe\xfe\xbe\x94|\x1e\xc3;\xbak\x05\x00\x00\x00\x00\x04\x01@\x02\x18',  # noqa: E501
    # Target tx count per sec
    "TX_PER_SEC": 20,
    # Size of mempool = 10x the size of block
    "MEMPOOL_BLOCK_BUFFER": 10,
    # Coinbase rewards are not spendable for 200 blocks
    "COINBASE_FREEZE_PERIOD": 200,
    # Max coin amount uint(1 << 64)
    "MAX_COIN_AMOUNT": b"\xFF\xFF\xFF\xFF\xFF\xFF\xFF\xFF\xFF\xFF\xFF\xFF\xFF\xFF\xFF\xFF",
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
