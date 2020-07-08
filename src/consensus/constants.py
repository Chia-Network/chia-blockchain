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
    "DIFFICULTY_STARTING": 2 ** 31,
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
    "GENESIS_BLOCK": b"\x04\x04\x04\x04\x04\x04\x04\x04\x04\x04\x04\x04\x04\x04\x04\x04\x04\x04\x04\x04\x04\x04\x04\x04\x04\x04\x04\x04\x04\x04\x04\x04\t\xf7\xfc\x05m\x8d\xcb\xecv\x1f\x1e\xfa\xba\xf3x\xebVy\x87\xd2\x85\x9d\xd26\xee&\xdd\xe8\xbb\xe6\xe2'1\xf04TJ3\xf8O\x85\xf0A:\xedM\xad\xff\x14\x06Z\xf9H\x04\x7f\x01\xc4\xe3\xda\x14\xd8\xd4\x04i\x84r\x85\x001A\xdf\x93\x02\"\x11\xf3!q\xd5\x81\xc6\x99'\xfb[\xc1\r|\xb5 \xd8\x1f\xa1\x0e\xee\xda\x1d\x00\x00\x00\xe8;Q\xd8~a&\x90\xcaJi\xcace]r&\x19c\x9eL\xefSg\x17\xcc\xedh{\x8d)\x91\x7f\xf11j+\xb5\\\xdb\x19&\xf8\x00\x16\n\x18ca\xe4\x1c@6\xcc\x7f\xc0k$\xc6\xcb\x0fl9we\xa7}I\xde\xd3R\x01>M\xa9\xf1\xec:f\x02\xebiz\xa0\xee\x9b\xfe\xda\xab0\x96\xc3d\xf5QB\x97u\xa0\xf2I\x19i\xea\xa9\x9a\xd8\xd8\xd5\x8d\xecl\x84\xe3-\xf9\xa7\xab\x8a\xc3[\x9a\x05\x86dE==\"\x9d\xaf\xc5\xbe\x84q95GH7B\x05[0@\xcf]\xc9y?\xc7\x00\xbf\x1a\xc1\xb79\xd0\xfe\xde\xa8\xc9\xa00\xe42\x0f\x8c0\x02\xd3y\xce\xcbr\xec\x17j\xdb\xc1mv\xeeL\xe0Z\x8f\xad\x8e?W\x0e\x94\xd1n#\xd9\x90\r\x04gmK\xf6nG\x86\x96\xb1RF\xa6\xfdF\xd4VI\xc8\x1d\x8e\xa1\x89a`\xe4\xb8\x98\x8bhx\xc3X}\x01\x04\x04\x04\x04\x04\x04\x04\x04\x04\x04\x04\x04\x04\x04\x04\x04\x04\x04\x04\x04\x04\x04\x04\x04\x04\x04\x04\x04\x04\x04\x04\x04\x00\x00\x00\x00\x00X\xees\x00G\x92\xc9\t\\\xdb\x9c\r\xecy\x92P\x9d2\xb4!\xff\x80\x94\xefS\x8a\x8ai\x1e,\xd2\xbc\xfe@\xac\xa4\xd2\x19\x06\x8b.S)\x01\xb6\xa9O\xbe\x06\xde\xfd?\x80\xd8\xbb\xa5@;\xc8\x08\xe1\xe9}\xa8\xd6\x99\xb8S\xff\xbe\x9b\x15\xe4\x05\x0c\xb6\r$\x0c\x88\x9f\x97\x05\xe9\xd1\xab\\\xe4n\x98\x05\xe1\x11\xc1\x81[Q\xdez\xa46\x96\x93\x04\xe1\xd9\x05\xd96\x12\x93\xf0\x7f\xdeJ\x14\xf9\x05\xaf\xa5#(\x93\xcc\xff\x0by\xaa\xe7k\xeb2\x9d\x00\x00\x00\x00\x82\x00e6\x84\xc9\xc6vf\xe5-\xec\xde\xb9\xf4\x83:\x83\xeb\xe3\xde\t\x1f\xcb<\x98\x03U%l\xf4~\xe8\x0e\x80\x01\xe01\xe4\n\xa5\xca\x97\xa48\xb6\x9e\x9d\xde\xb0Gio\xbaRP\xd3h\xe4\xd5q6<\x1ev\xf1\xff\xd2 B\xcb\x85)\xd5\x88\x97Z\x92\x8d\x10V\xe6\xfb\xd14M\xc8\xca\xc8H\x80R\xe4\x94\x8b\xef<\x05\xce)n\xbb\xdar\xb5\xbcm]n\xdbt\x9b\xfdV\x86\xb2O\xa8\xfe\x90P\x18\xd8\x1c\\\xaf\xa9Rc2\x9b\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00^\xc74\xe4\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x07\x93m\x0e\x1a@\xa6 g\xde+\xe2qk\x86\xe3\x13\xa5q=l\x1b\xfd\xfc\xc7\x9f\xbe\x1c\xc0\xd2\x9f\xf7\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x80\x00\x00\x00\x00\x00\x00\x00\x00X\xees\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\xa4%\x91\x82\xb4\xd8\xe0\xaf!3\x1f\xc5\xbe&\x81\xf9S@\x0bg&\xfa@\x95\xe3\xb9\x1a\xe8\xf0\x05\xa86\x06\xf0[Y\xd3\xb2\x00\x00\xc8\x12\xbe\xc2\x1c\x12eg\xebS\xcak\xdf\x8c~\xacm\xef<\x1d'\xe5\x12\x88^\x07\x06\x86$\xd6R\x93\x079\x9cQ\xe0\x08\xc8\xc75\x8ep]\xf6`I\x93\x07)\xe2?nc;)\n\xc3\x81\x87\x15\xad\xe3\x1eJ\xc0\x93\x83\xd6\xbf0\x15i\x98\xad\x9f\x17\xd7]\xca\x8c\xd3\x07\xc6\x9d\xa4\x0b\x0c\xa2`\xe4<mo\xd5\xd9\x8c\xb9\x01%\x17\xc8\x17\xfe\xade\x02\x87\xd6\x1b\xdd\x9ch\x80;k\xf9\xc6A3\xdc\xab>e\xb5\xa5\x0c\xb9\xa4%\x91\x82\xb4\xd8\xe0\xaf!3\x1f\xc5\xbe&\x81\xf9S@\x0bg&\xfa@\x95\xe3\xb9\x1a\xe8\xf0\x05\xa86\x00\x00\x01\xd1\xa9J \x00\x00\x00\x00\x00\x00\x00\x00\x00\x003\x89q\x1aT\xe3F\x1b\x9aw\x0f\x9bH\x17B4F\x1c\xe8?\xd5u\th~g\xae2\xd4\xdb\xae\x1e\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\xd5\x8b=\x8a\xea\x15\x9fj\xe5#s\xc6PS\xc4\x84D\x98\xe7eI8m\t2\xa3\x82\xc7\xc0A\x84A.\x88\xb0A\xf3\x99$d\xaf\xe0\x04\xa5\xeee\xd0\x96\x15\xd2G\xbeM\x86r@r\xba\xb6aT-\x8cY\xcd\xd2\xdfq2\x10>W\xe2\xbd\xdd\x03\x99;\x00\xdc\xaa\xd3o\xd2+\xf5|\xfb\x89\xffV'\x9c\x03\x81\xe2\x00\x00",  # noqa: E501
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
