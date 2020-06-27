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
    "NUMBER_ZERO_BITS_CHALLENGE_SIG": 3,  # H(plot signature of the challenge) must start with these many zeroes
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
    "GENESIS_BLOCK": b"\x02\x02\x02\x02\x02\x02\x02\x02\x02\x02\x02\x02\x02\x02\x02\x02\x02\x02\x02\x02\x02\x02\x02\x02\x02\x02\x02\x02\x02\x02\x02\x02\t\xa0\xb1x\xaa:\xad\xc1VH\x08y\x8b\xc5j\xa82\x03|\xf0\xbc\x1a\xa5\x0c\x92\t\xea\xd9\xc6\xfbd \x8c\x00\xd5\xa1\xd8\x1bv'1\xcb\xeb\xba\xd2\xdb\xae@\x18\xa6\x8cmm\x9aL6\xa1\xa5!(\xc8g\xac\x9dLUu_\xa2\x7f%\xde)'\\\xdbv\t\xec\xa3\x9b\xf9\xee\xd8\xa7\xd4\x163\xbb,\nb\xd6\xf7\x96s\x13\x00\x00\x00\x987\x97s2\xa2W2M9\x03Z\xdc`@\xeb\x0eN\xf45\xbc\xc5Lj\xf0\xd6\xeaN\x99\xccm>\xa1\xaa\xd3\x91!u\x93\x05\x91\x9c\x90\x96\xee\x83\xa4\x7f\x17o\xa2\x88\xb0]\xb3\x01h\xf1\xf30!\xa0\xa8\xc8\x89\x81P\x9e\xc0\x14\x0f\xf3\xc9u\xc2\x00y\x07{k|\xf3/9\x11h\xb8\xceu\x9b\xc5\x1b=\xd1~>F\x1dS\xd4\xcc\xb4\xcf\xd6\x04\"\x10\x06\xeeh\xed\x1dM\xe0\xd4\xe2\xb3\x92\xf1\xa2O\xe2V\x94?\xe4bR\xaf\x85\xd8!\xb7\x8d\xae\xaf\x9cu\xc8z\xb9lv\x92\xb3\xc1eW\n\x8eS\xa7\x0f\x01\x02\x02\x02\x02\x02\x02\x02\x02\x02\x02\x02\x02\x02\x02\x02\x02\x02\x02\x02\x02\x02\x02\x02\x02\x02\x02\x02\x02\x02\x02\x02\x02\x00\x00\x00\x00\x00\x08\xef\xe1\x00!\xbc\n\xb5\xd8\xe4\x7f\x1e%\xc0\x01\x91TO\x884u\x12\x8cp\xc8}\xc2\x99Q\xe7&i\ttG\xf97\xa7\x9f\xd3*\xb2z%]\xed&c\\D29\xcbkn\x96\x1bn\xb1\x1d\xcf\xd3]/^\x85\xf0Y\x00\x18\x87\xa2\x13G\x96\xd9\x01@\x1e\xcf\x15? \xd8\xfa\xce\xf3 \x9f\n\xcaJ\x03\x1b?\xf8\x0c'\x81s\x8f\xaa\xa6\rd\x8c\xee\xe6 =\xb4\xfaFtM\xc1\xf2t\xff#\x80\xd4\xdb\x84\x97\x06\xc2\x88!\xc0\x16\x84\xf3\x00\x00\x00\x00\x82\x00#\x19NfN\xda$\xca\xdc\xa2~\x04\t\xcb\x15\xc2\xf7\x80`\x8e\x98\xaf\xc6\xe4\x91I.\xaf\x8b\xa1\xc5\xa7i\x1d#\xf4Q\xfa\xa7Sa)M\x1b\xa2\xb2\x86\tv\x10n\x88[\xe8\x12c\xec\xa5\xdbw\xd4\xf1+^\x00\x13c\xce0\xd4keP\x84\xc7\x9b\x8c{\xf9\xf1A\x8eg\xfcG\x1b\nf\xd5\x1bw,\x03:/\xedK\x8b\xa8\xac\xf9`\xc3\xd2kIz\xf2E\xc8\xc2\xf3\x1f\xd8]tY\xcb1\x00d\xa9\xb0]p\x0eV\xed\xed\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00^\xf6\xf8E\xd8)\x8e\x0e\xe4\xe4_Ac\xc1\x9d\x16z\x13[\xd4\\*Fy\xd6\xa7Z\xfb\xea\x9b[\x8d\x185Q\xa0\xefA\x1a\x80\xa2|\xcaYqe\xf0Kq\xe5j\xe1I\x11|F\xe5\xed\x18\xf8O\x15X\xca\xea\x93\xfb\x07\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x08\x00\x00\x00\x00\x00\x00\x00\x08\xef\xe1\xab\x80\xcb\xf0\x0b\xf3w\xe1\x14\xe4\xef\x85o\x82\xa6\x97\x0b\xa8\x1e\x94S\xa4\xb9D\xa2\xe5`l\xaeL\xbbz\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x000\x94B\x19af\x95\xe4\x8fz\x9bT\xb3\x88w\x10J\x1f_\xbe\x85\xc6\x1d\xa2\xfb\xe3RuA\x8ad\xbc\x00\x00\x01\xd1\xa9J \x000\x94B\x19af\x95\xe4\x8fz\x9bT\xb3\x88w\x10J\x1f_\xbe\x85\xc6\x1d\xa2\xfb\xe3RuA\x8ad\xbc\x00\x00\x00\x00\xc7\x0f\xceO3h\x80\xc0d\x8a\xe4\xb2il\xa8\xd3\x08\xf6\xe3\x9e\xba\x94_\x1d\xc24\xdf\xdd\x99}Z/*\x18t y,\xfd\xd5\xa1\xd1i0I_\xd3\x8d\x11\xb3HU\x16\xe7\x95\x85s\xcc\xfetD\x83\xb6\xe0\xb0\x1e5H\xf5ta#U}\xbc\xb5\xe8'\x8dsu\xc6\xea0\xe3w\xeb\xf4\xfa\xb1\xf9\x07\xf0\x01\x90\xe9\x00\x00\x00\x00\x00\x00\x00\x00\xb7\xf5\xd6\"?\xb5G1\x8b\x0f\xce\xe6\xc4\xf5y\xf2\x02\xa8\xea\xa6\xd0\xe66\xd8\xd7?\xfb>\xc0\xe5\x1a5\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00F\xad,\xb2uC\xd4\x11\x9a\x18\x8b\xd6\r\x16\x8a\xf6\x96\x85*\xc4\x08\x8d\x80O\x8aP|m\xc6\xdc\x98\xf9xp1.C\x81\xaa\x80\xe1\x12\xca\xb7\x97\xce\xcf<\x153*\xd4\xba\xeb\x9b\x8fJZ\xc0L\xd76\xc6\x83\xbar\x19'\xdc\xbbUj\xfe1Jb=\x9f\xf1\xbf\x88\"\xe7\x8c\x14\x06UD\x96\xcba%\x9c\xd21\x87\x00\x00\x00\x00\x04\x01@\x02\x18",  # noqa: E501
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
