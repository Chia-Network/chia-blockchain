from typing import Any, Dict

constants: Dict[str, Any] = {
    "NUMBER_OF_HEADS": 3,  # The number of tips each full node keeps track of and propagates
    # DIFFICULTY_STARTING is the starting difficulty for the first epoch, which is then further
    # multiplied by another factor of 2^32, to be used in the VDF iter calculation formula.
    "DIFFICULTY_STARTING": 2 ** 31,
    "DIFFICULTY_FACTOR": 3,  # The next difficulty is truncated to range [prev / FACTOR, prev * FACTOR]
    # These 3 constants must be changed at the same time
    "DIFFICULTY_EPOCH": 128,  # The number of blocks per epoch
    "DIFFICULTY_WARP_FACTOR": 4,  # DELAY divides EPOCH in order to warp efficiently.
    "DIFFICULTY_DELAY": 32,  # EPOCH / WARP_FACTOR
    "SIGNIFICANT_BITS": 12,  # The number of bits to look at in difficulty and min iters. The rest are zeroed
    "DISCRIMINANT_SIZE_BITS": 1024,  # Max is 1024 (based on ClassGroupElement int size)
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
    "GENESIS_BLOCK": b'\x02\x02\x02\x02\x02\x02\x02\x02\x02\x02\x02\x02\x02\x02\x02\x02\x02\x02\x02\x02\x02\x02\x02\x02\x02\x02\x02\x02\x02\x02\x02\x02\x00[\x8c6\x15\x85\xbfg\x1c{\x19\xe5\x91y\x90,\rd\x0b=\x0b\x84\x8f\x9c\x83#k&&\xf3\xff\xd8\xb5\x009\x98\xd7\xaa\xe7\xbc\xde\xe2B\xd1\xe8\xd6\xdb\xa1\x94ow\x96uY\xb1"\x11\x0b\x19.\xe1}(\xc9\xbfE\x80\xcch\xa2X\xc0\xd1\xa5\xf04 \xb5\xcfg\x94\xbc\xa8q\x8c\xb8jW\xf5/\xb3P\x8f\x89."\x1b\x00\x00\x00\xd8\xbb)::S\x7f\x89m\xd9\x10\'\xd4\xec\xf5\xbf!|\x89\xa4<\xb1\xde\x80\x8c.n\xf8\x87\x91\xa4\xa7\x12a\xa0tLb6\xb2\xfa\xa1pt\x90c\x0e\xa8|C\x99\x11\xef\xc7\x98\xa7J\xff\xeeZ\x8b\xca{\x93%\xfd\xe8\x99\xc7Jt\x90\x17\xa4lg$\xb39\xd1`\t*\xd7\xeb"\x04]\xbfx\x9f\xec\xd7\x06#\xd2j\x9e\'t\xb6\xeb\x91\x1d\xd6\x10y\xbcf\xc4Z$0\xd5@2\xcd\xe1]PG`E\xf1=\xd7\x87\xc4I\x16\tue00*\x9d\x90\xd7PW\xe2\x00}-&\x12\x11\xa7!E\xa5*\x97\xe16\xc0\x1b\xfbm\x0b\x98\xf1\xac>H\xe4c\xc1Lg\xb0L[\xe7hJ\xac\x90u\xfd9\xfe\xd1\xa8\x1bv::+\x0f\xef\x10\xe6mn\xe4\xc1&\xf7x\xd1\xaa\xaf\x1br\xffl\x8e\xded|\xe6\x93iG\xd4\x01\x02\x02\x02\x02\x02\x02\x02\x02\x02\x02\x02\x02\x02\x02\x02\x02\x02\x02\x02\x02\x02\x02\x02\x02\x02\x02\x02\x02\x02\x02\x02\x02\x00\x00\x00\x00\x00O\xda\xbd\x00B\xab\x83\xf9&K\xb3\xb6R\xc2\x07\xa2\r\xadd\xa8\xfb\xd90\x9e\xb6\x8c2R\x80\xa7,\xdc\x1cy\x1d\xae\xbd\xa2]\x82\x15\n\x86Y\x92\xc2\xd7-;O\xc6 t\x08\x15oe\x86\xf3\x86\x03\xf0\xb6\xed\xb4\x16d[\x00(w\x05\x0e(\xd2\x1bZ\xc7\xde:\x81}ns\xd0\x95\xf8\x93a(v\x10;:\xa7\x1bS\xb2N\x92\xc3q\x1b2\x95W\x9e\xcd\xce\x840\xdd~\xfa`\xf7\x89.*\x02W(\xb9\x89\xe61\x81\x8f\x1c\xd4-u?\x00\x00\x00\x00\x82\x008\xe3\x93\x84\xcfr\xab2n}\x9c\xda\x8b\xa7\xdc\x10B\xd4\x82\xcc_\t\xd2\\\x8buH\xf57\xdb\xdb\x94\xf5\xc9+G\n^\xc3th\x87i\xca\xc4?\xe8(\xd3\xa5k`\x85d+\x8d\xb3a\xe7\x17\xb4C\x1f#\xff\xf7=\xe8\n\xbe\x08-\xc7\x87\x8b^t\x9dd\xb6o}=\xcamW\xf6\xc1\x16\xd0\xeaI,2\x08\xaeqajv\r\xce6 y\xf2\x88\xe3}\xe7\x18M\xec\xea\x0c\xb3\xaeV\x0bm\x7f"\x8a\xedtaQ\xbb\xf7\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00^\x9f\xd4\xd0\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\xe7,\xa4\x1aI\x19\xc6d\xe8/7\xbf\x9a\x17\xb9 u\xc4R\x90T\xa2\x96a\xe5a\xdf\xa8o\x9bP5\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x80\x00\x00\x00\x00\x00\x00\x00\x00O\xda\xbd\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\xa4%\x91\x82\xb4\xd8\xe0\xaf!3\x1f\xc5\xbe&\x81\xf9S@\x0bg&\xfa@\x95\xe3\xb9\x1a\xe8\xf0\x05\xa86\x06\xf0[Y\xd3\xb2\x00\x00\xcc\xe7\xc9T1\xfb\x0c\xf5_\xf0\xb0r5\x8c\xa3\xb9\x86D\x89\x1e\xf0\x8b\x08\xd9\x19\x93\xc6\xcf\xc7\xaf\xea~\xda\xa5l\xf9\xac\xe2\xb0\x99\x9a\x91q\xe4\\\x8eu\xdc\n\xc2i\xe3\x93\x85\xabf{\x08yC\xe7e-r\x936\x0f\x16~)\xef\xb2\x9d\xd7\x9b\x1f\x97Q\xa3\xd6&\xf3E\xc9CF1l\xb6\x0b;t\x1f\xed\x8e\xc4\x8c\xb9\x01%\x17\xc8\x17\xfe\xade\x02\x87\xd6\x1b\xdd\x9ch\x80;k\xf9\xc6A3\xdc\xab>e\xb5\xa5\x0c\xb9\xa4%\x91\x82\xb4\xd8\xe0\xaf!3\x1f\xc5\xbe&\x81\xf9S@\x0bg&\xfa@\x95\xe3\xb9\x1a\xe8\xf0\x05\xa86\x00\x00\x01\xd1\xa9J \x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x1a\x80n~U\x07\xb9\xdd~\xf9\x94\xacsrD2\x8d\xa1\xe4I\'\x9f~"\xdb\xf35\x06\xf9d\x82\xef\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\xc1"\xaa\xc7\xe2\x10*_Yk9\xbfw\xbd\xb0T$\xee\x83\xc2\x05\xa6bQ\x92\xd4\xce\xb5HF\xe5\xf5hL\x18\xf1p-\xf7F]\xe3\xc0Vk\x17\xd1\xef\x12\xf1\x87\xe4\xd0\xce\xb0\xe30\xb4WB@\xbc\r\x0b\xfd\xd1H\x99\x18\x16\xda\x87\x03\x81\x94f*}\xceT\xf5\xaa1\xa3\xf35\x18\x92\x95`\x1d\xbb\xec\x11\xa1\xfd\x00\x00',  # noqa: E501
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
