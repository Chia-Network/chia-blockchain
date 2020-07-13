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
    "GENESIS_BLOCK": b"\x00\x00Q\x16\x16\x16\x16\x16\x16\x16\x16\x16\x16\x16\x16\x16\x16\x16\x16\x16\x16\x16\x16\x16\x16\x16\x16\x16\x16\x16\x16\x16\x84\xe8-\x9f\xcd\x80E\xe8y\xb6\x88I6\xbbkt\x01\x8f-\xf3z\x96\xd6\xb6\xefy\xe4\xf5o1!\xc6\xed\xd0\x1f\xed\xc0\x19\n\xc7j\xa8I\x9a\xdc|\xfe4\x94o\x16H\xef\xc97\xe24.`5\xc2\xfe\x03K\xfd\x87\xaf\x93\xf4\xdfW\xa3\xca\x8a\x1e\x01\x0740\x01A\x13\xa4#\xfe\xe3\x11\xe3\x80Y\xcc\xf8[mq&\x12\x00\x00\x00\x90\x98y\xe4j\xe8\x9a\xd1\x0b^c-\x97C\xf2\x13w2\xf3\xe5\xc6D\x8e1e\x83|`c\xcaR\xa19\xcd\x01\x96\x1e\xcdJ\xb3\x93z\x139)\xb5\x1am<V\xe6\x03\xf5\xe8\xab5\xde&\x96\xd3\x1eBV\x9c\xfd\x08\x96XN#\xe3\x08\xe2\x9f&3F\xef\xd7\xfbdQ\xe6\xce5\x91\xffUf\x18*'\xc2\xfbtB\xf3\x9e\x02j\xba\x80\xed~\xb7\xca\xed\xd3\x00lI\xe1\x91M\xe4\xdbr\x80Z\x82\x05&h\xda\x15$?:\xdd\xf6\x16\xc1\x16\xae\xd8\xf2\x96'G\xbf5\x85\x8fB\x9f\x01\x00\x00Q\x16\x16\x16\x16\x16\x16\x16\x16\x16\x16\x16\x16\x16\x16\x16\x16\x16\x16\x16\x16\x16\x16\x16\x16\x16\x16\x16\x16\x16\x00\x00\x00\x00\x01\x19\xf1\x80\x00\x11\xe2\xf6^^;j\x18\xb3e\x9fs\x8f\x95\x82\x9e\x84\xae\x1cP\xd6\xc7\x98\x0b\x06\x97M\xbb\xcf\xdf<au\xe6U\xe7tgE@\x86r\xb5\xfb\xf3\x15\x04A@\x0evn\xd4\x80\x95XO&eF-W\xab\x9a\xff\xfb\xf1z\xde\x04\xfa\xecv\xac\xc3m\xd6\x95^\xb9\x8c\xa2=\xbc\n\xe0\x85\x83S\x00,\x16\x10N\n\x82p\xb7\xd4\n\x99\xb6\xff\xf6\x93a\x7f\r\xa2\xb5\xb1\xbdT\x99\xc0\xc6\xeczO\x18c&\xae\x81\x8e\x95\x1d\xcaE\x00\x00\x00\x00\x82\x00e\x95\x06g\xe1\xbb\xbb\x81 #e\x19\x07}\xcb\xacIp\xc3\xc3\xbb\xbf\xdc\xbc\x9fVhW\x13\xdd\xcd\xf0\x90\x8fH\xbf\x8e\x15\x030\x1f\xc5\xb4r\xd0\xa7\xbf\xfa\xee\x99\xee\x97o#`z\x12\x0e\xc6\x11\xc8\xb1c\xe2\x00\"Ds\x13-g\x14\xef\x05t\xf7\xe6\xf4`\xbc_=\xce3\x89\x03\x8d=L\xfc\x08\xb9\x9d\xbf\xd6\x83\xf0\xa5\xaf\x17G/\xf0\xee\xb3\x94m\x03\x93\xfd\xd3\x11M\x95l,\xec\x03\xd0\xc7\x83\xb0,\xaeE\x98\x8a\xac\x99\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00_\x0c]\x88\xd8)\x8e\x0e\xe4\xe4_Ac\xc1\x9d\x16z\x13[\xd4\\*Fy\xd6\xa7Z\xfb\xea\x9b[\x8d\x185Q\xa0\xf5\xdbW\xad\xdd\xf5W\xff\xb7\x9a\x1a\xab\xd6\x01\x93\x1b\x8b\xd7\x00\xf1\x9e\x1d\xa3(\x1d\x8d\xb0`\xbef5\xd2\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x80\x00\x00\x00\x00\x00\x01\x19\xf1\x80\xab\x80\xcb\xf0\x0b\xf3w\xe1\x14\xe4\xef\x85o\x82\xa6\x97\x0b\xa8\x1e\x94S\xa4\xb9D\xa2\xe5`l\xaeL\xbbz\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x000\x94B\x19af\x95\xe4\x8fz\x9bT\xb3\x88w\x10J\x1f_\xbe\x85\xc6\x1d\xa2\xfb\xe3RuA\x8ad\xbc\x00\x00\x01\xd1\xa9J \x000\x94B\x19af\x95\xe4\x8fz\x9bT\xb3\x88w\x10J\x1f_\xbe\x85\xc6\x1d\xa2\xfb\xe3RuA\x8ad\xbc\x00\x00\x00\x00\x88\xcb\x13\xe8f\x10\x12\x9e\x19\r\xa9\xaa\xd0%\x98 c\xf5\x03L.\xba\xff\xd4\xd2<\xb0\xa1H\xad\xb9l\xe8&\x95 _w\x99\x81\x19i\x8aH%\x9c`\x18\x88n\xc4\xbf\xb3ABL\xfe\xe7\xaf\x1c!\x9c\x87'\xd3h\xfb\x92\x0f\x12\xa9\xfcH\xe0;5\x9dX@\x8d?w\xd0b\xc7\xf7I\x08\xed\x7f?C\x9b\x15\xb1\xe5\x00\x00\x00\x00\x00\x00\x00\x00Q\xa2\n\xf8\xd9n\xc16\xc9I\xcd$\xf3\x9a;m\x9c\x9bX/\x99 \x94\xb9\x97d\xbe\xb9c\xe1\x1fr\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x82\xde\x9d\x8e\xb1\xa85\x0e8D>\x97\xa0u\xe1X\xd3\xd5\xb0\xce\xe9\xbbvG\x0c-\xe1\xdbw/Kw<\xc0\x0bpT{\xa8`\x8c\x8aW\xd6\xce\xe7\x96&\x8eb#\xce\xc5\xbc.\xf1\x8b}i\xa1\xff\xeeR\xb5JTH0\x8f\xe8w7\x97\xa1M\xc6\x15\xc4\xce\xcb\x81\x153\x87&\x83\\\x1bq\xf5\xde\xf9'=\xb8\x83\x00\x00\x00\x00\x04\x01@\x02\x18",  # noqa: E501
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
