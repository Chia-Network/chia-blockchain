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
        assert self.DIFFICULTY_EPOCH == self.DIFFICULTY_DELAY * self.DIFFICULTY_WARP_FACTOR

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
    "MIN_ITERS_STARTING": (2 ** 15),
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
    "GENESIS_BLOCK": b'\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x08fc\x9e\xd4w,K\x91v\xf61:\xbe\x9a\x0b\xe9w\xb9\x01\x19\xb0\xd4\x8d\x9f\x0b\xac\r;km\xc2\x04}Y\xbd\x86\x82s\xca`A\xc6\xbc\xc3\x0b\xbb\xb7\x85\x84\xf6\x1e\xc6\x9f\xf8\xbb\xc9\xd6]\xd1\xc5\xd1\x98\xff\x84\x92:\xe2\xad\xb8\x05\xf9m\xfb/\xfc)\x0bh\x13\xff\xa8N\x1e=qVU\x8e\xd0C\xea\xcd\xa7\xf4I\x14\x00\x00\x00\xa0\x08\xdco\xa4\xb5\x04\xde\x0ec\xac\xc9\x182Vf>|\x1c\x9e\x19\xb8\x93\x8bK\xf5i\xc9\x0f\xec\x01\xf6\x11\x87\xb0\x93o8\xdfM\x9f\x9e\x18\x9f 6\r\xfd8\x00\x01\xa3\xcbT]\xbc^C Yan\xeb\xe7O\x07\xf1\x8b\x9a\x91s!\x1c\xa2\xbdY\x89\xdb\xde\x9e"\xd4\x9d\x06\x0cI\xae\x81t)\xc6\xb8\xef1\xb7X\xf8\x98\xc1#\xdc\xab\xd1v\x93\x80\x1c\x19\xff\x0e\xa318!v\x14\x92\xb1\xa9M\x06yc\xd2<\x1dZ\x90Vr\xa8\x0f[;\xa6*o:\x8d@\xc2[\x8e7G\xd2\xae8\xf3\xa1\xca\xc3TM@y\xdc\x88\xd9\x1aa\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x07\xc4\xc0\x00G\x8a\x98L}\x020}}<\xfc\x19\xc3\xb7\xf4\xa6\xf6\x15\xd3\x94\x87\xac,\xa0\x17\xf9v\xcb\xdd\xa7*)\x03\xf7\x0b\xb5\xd2\x00\xda\'\xdba\xd4\xd5\rl\x01P/\x06\xe3\xa8\xf3wU5\xef\x06N\xc5o\xbb\x18g\xff\xbb\x93\x9a\x9bZ\x96\xcc\xf5\x90\xa3?\xc9\xf9t\xc0\xc4S|{\xb3\x8b\x0f1K$\xc1\x01\x93\xbe\x80\xb6u\xae`\xe8rz\xffl\xbb\x1d\x0e\xa4\x9a#\r\xf1\x17+U\xe9\x8eto\x03\xf5\xcbn\xa4\x04\xbc\rd\xdd\x00\x00\x00\x00\x82\x00KZ3&\xe0\xf4}\x7f\x01w\x12+\xa1\xad\x19\xa8\x9d\x1f\xd1f\x06\x8c\x90g<\x1b\xad\xae\x81\x07}\xffR\x1a*\xc5\xdcj3\xf19\x84\x05\x96B\xa7\xf5\xc7\xcc\x1d\x95\x1f1G\xd8\xda\xf6\xca\xd8w\xd4\xbfG\xb0\xff\xd3\xa8J\x9c\x85\x88Z}\xfa\x19\xdc\xcc\xc5\xef@\xd0\xe4\xd7\xce\x1fV&}\x82\xe5s\xde\xfe\xf5 W\x89u\xf2\xd0p\xfbp\x03\xf8\xa4\x0b\xfa\x08\xe5\xed\xe3\xd1\x99\x0c\xfbZ3I\x99\xc7\x01>\x06\xbadC\x96\x0b\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00^\xf89\xe2\xd8)\x8e\x0e\xe4\xe4_Ac\xc1\x9d\x16z\x13[\xd4\\*Fy\xd6\xa7Z\xfb\xea\x9b[\x8d\x185Q\xa0r\xcb8\x150\x18P\x94\xdf\xda:M@\xe4pi=\x9b*\xba{M]\xdbQ\x81\x80_\xc4\xdc\x00\\\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x08\x00\x00\x00\x00\x00\x00\x00\x07\xc4\xc0\xab\x80\xcb\xf0\x0b\xf3w\xe1\x14\xe4\xef\x85o\x82\xa6\x97\x0b\xa8\x1e\x94S\xa4\xb9D\xa2\xe5`l\xaeL\xbbz\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x000\x94B\x19af\x95\xe4\x8fz\x9bT\xb3\x88w\x10J\x1f_\xbe\x85\xc6\x1d\xa2\xfb\xe3RuA\x8ad\xbc\x00\x00\x01\xd1\xa9J \x000\x94B\x19af\x95\xe4\x8fz\x9bT\xb3\x88w\x10J\x1f_\xbe\x85\xc6\x1d\xa2\xfb\xe3RuA\x8ad\xbc\x00\x00\x00\x00Y\xe6\xb2@\x86t\xd0\x01vq\x8al\x93y\x85\x8f\xb6\xdcb\xd6d\x89@\xda\x8eD"\x10u\x1a\x82o\xe5\x1e\xe3\xc7\x0ceb\xbc\xb7_&\x87\xb4\r\x9d\xe2\t\xe4\xe9\xbe$\t\x19|\x95N\xb2\xeaU\xf0\xb9\x02\xe3\xbc\xe34Z1\xb2\xa6rM\xf24G\xa2\x14\xe9\xc4\xd0\xea\x1c\xdd\xf1\xc1\xb1\x04p?\x89\xa8\x1c8\xf2\x00\x00\x00\x00\x00\x00\x00\x00\xe7F\x850\xc5\xc2\x8f\x82S\x9e\t\xa8\x85\xd0\xd9\xa6\xec\x1b\n\xc6`\xaa\x14\x90\xf7M%\xd8\xc6~L\xd7\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\xceq\xd7\xa7\x03\x95\xcb\x10\x9b\xc6\xd1\xf8d\x05\x97\xcb\x9e\xc4\x8b\xbb+\xfe\x13\xb8bH\xd7\xc0\x84v?\xf6\xa6\xb8m9\xd2o`\x9a*\xb6\xba\x0b\xe5\xa1eg\r\xe8\xb5\x93\xad\xee\xc1\xd5\xe8\x12\xd4\xd9\xa3Z\x83\xc3\x10\xf5v\xe3\xf6\x89\xc26\xe8G\xc6\xcaFp\x910\xff\x1a\xcf\xa4F\xb2\xc9~\xc1N\x1f\xedU@\xf5\x19\x00\x00\x00\x00\x04\x01@\x02\x18',  # noqa: E501
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
