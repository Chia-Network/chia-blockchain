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
    "DIFFICULTY_STARTING": 2 ** 20,
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
    "GENESIS_BLOCK": b"\x00\x00Q\x16\x16\x16\x16\x16\x16\x16\x16\x16\x16\x16\x16\x16\x16\x16\x16\x16\x16\x16\x16\x16\x16\x16\x16\x16\x16\x16\x16\x16\x08fc\x9e\xd4w,K\x91v\xf61:\xbe\x9a\x0b\xe9w\xb9\x01\x19\xb0\xd4\x8d\x9f\x0b\xac\r;km\xc2\x04}Y\xbd\x86\x82s\xca`A\xc6\xbc\xc3\x0b\xbb\xb7\x14p\xfbI\xda\xc5\xd0\x02\xbbr\x1eV\x86\xaeN\x84\xfdo\x00\xfeL\xba\x987o*\x95\x8b\x8a\xb2G\xc4\x90g_\x15DL;\xa5E\x03\x8c\xbb\xf0\xbe,\x11\x14\x00\x00\x00\xa0^H\xf1\x1a\xd0E\x945\xf8}c\x8d\xc3\x9a\x03\x1c\xeaO\xe3R\"=\xaaM\xb4\xd9\xee1`\xde\xf1\xc4\xef\xa4#`\xe3\xe3K\x0fE\xa9n\xe9j\x98\xef\xcdP0\xb8t,?wL\xc8\x84H\xd0\xd1\xef\xbd\xa1i}L\xe8\n\x1ep\x1e\xe0hK\xeb\xb7\xc2\xd4,\x89y\x99w\x86\x8aF\xf1KV\x18V\x9a\xb6\xc2\xc6\x19k\xf5\xa6|\x03\xc0c\xc5\x9fQ\x0e\xc6n\xde\x8b\xa6\x01\x83\xa8\xaa\xe5\x84j\x1e\xfa7&\x06\x83\xd9k\x01$\x9f\x1f\xb3\xf7d\xec\xd5\xef\x0f\x9b\x17:\xb6'\xaf\x84\n\x0fS\x1e\xd5\xdab\xa9}|\xce\x1b\x9a\x05\x01\x00\x00Q\x16\x16\x16\x16\x16\x16\x16\x16\x16\x16\x16\x16\x16\x16\x16\x16\x16\x16\x16\x16\x16\x16\x16\x16\x16\x16\x16\x16\x16\x00\x00\x00\x00\x00ra\x12\x00S\x91\xbe{\xbb\xceU\x9e\xfe\xaf\xc8\"\x87p\xb5+S\xaeE']\xee\"LNV\xe1\xcd]\x95\xa4\xfd=\xec\xe3L\x16)\xdc\x01\x06\x15\x8d\xee\xeb\xd8\xe6\x13Q1i\xa07\xea\xdarohH\x9e\xf6\xd0\xb6p\xff\xaf\x1f\xa83z7\x86j2\x11i\xbb{\x89\xd6\x94\xb2\x97\xad\xf7U\x03B\xfb\x89\x8f\xebS\xcc\\\x17\xec\xd6.s\xd0Ba\xca\xa0\x14(\xff\xf5\xdcAP<\x8e\x19_\x15\x1b\xc3\xaa>\xd7\xb0\xc4.!R_\x13\x00\x00\x00\x00\x82\x00Tq\xeef\x8e\xbb\x90\xc4\xc5\x96\x98\xbd\xfd\x89\xb5\xcc\x82\x1b\x8e\xe6>\xd2\x18\x8f\x1e\x81iaT\xa0\x9c\xa0\xec3r\xc1\x7f\x90\x10\x0e\xf5@\xbb\xc4\x8bI\xff\xa8\x064c?\xba2\xb0]\x98z\x06\xad/\xfc\xbe\xc5\x00\x11Xu1'\x14^\xdc\xd5\xd7\xacwd\xe8\x16\x07\x85f\x90\xe7\xf8\xe8\ti\xbfQ\x05\xdf\xf2\xfc\xf7Z\xf3]\x97Z\xa0O\xef\x95T'\x10\xe1\xbe\x7f\xdb\x0cj\x1a\xc3\xb4\x96X\x88\x05\x1e~\xd0\x83\x08J\xd3k\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00^\xfe\x83G\xd8)\x8e\x0e\xe4\xe4_Ac\xc1\x9d\x16z\x13[\xd4\\*Fy\xd6\xa7Z\xfb\xea\x9b[\x8d\x185Q\xa0Mo\xc8V\x04\xce\x7f7\x15\xfd~\xd4\xb4\xd7\xafMH\xc9\xb9,\x88 \x84\x8b@\x1f\xcaB\x99\xa5`\x10\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x10\x00\x00\x00\x00\x00\x00\x00ra\x12\xab\x80\xcb\xf0\x0b\xf3w\xe1\x14\xe4\xef\x85o\x82\xa6\x97\x0b\xa8\x1e\x94S\xa4\xb9D\xa2\xe5`l\xaeL\xbbz\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x000\x94B\x19af\x95\xe4\x8fz\x9bT\xb3\x88w\x10J\x1f_\xbe\x85\xc6\x1d\xa2\xfb\xe3RuA\x8ad\xbc\x00\x00\x01\xd1\xa9J \x000\x94B\x19af\x95\xe4\x8fz\x9bT\xb3\x88w\x10J\x1f_\xbe\x85\xc6\x1d\xa2\xfb\xe3RuA\x8ad\xbc\x00\x00\x00\x00Y\xe6\xb2@\x86t\xd0\x01vq\x8al\x93y\x85\x8f\xb6\xdcb\xd6d\x89@\xda\x8eD\"\x10u\x1a\x82o\xe5\x1e\xe3\xc7\x0ceb\xbc\xb7_&\x87\xb4\r\x9d\xe2\t\xe4\xe9\xbe$\t\x19|\x95N\xb2\xeaU\xf0\xb9\x02\xe3\xbc\xe34Z1\xb2\xa6rM\xf24G\xa2\x14\xe9\xc4\xd0\xea\x1c\xdd\xf1\xc1\xb1\x04p?\x89\xa8\x1c8\xf2\x00\x00\x00\x00\x00\x00\x00\x00$\xaa\xdc\xcb\xa8\x83o\xa2\xcb\xaaf\x9c\x14\xcd_Bn-\xfe\xde:(\xe2\x05\xf4\xbaM\t|\x8d\x8cb\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\xce`\xb5\x1fd\x9brcf\x17\xf1\x18]\x82\x95L\x01U\xa8\x9bZY\x16\xc7\x83\x95\xf4\xfa\xfe\x8f0\xf8\xe2TM\x1fV\xc0\xa1\xdd8\x8b\xb1y\x1d\x0e>\xee\x0b\xd9\xdd\t&\xa7\xf8%\xf3\xf4\xa4\xcc\xa3\xf4\xb3m\xae\x8fe\xb0\xc4\x8a\x08^F\x96\x86\xee\xadV\xcb\xeb5R19\xd91N\x12G\xbe\xdbr\x8a\xc3'\xcc\x00\x00\x00\x00\x04\x01@\x02\x18",  # noqa: E501
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
