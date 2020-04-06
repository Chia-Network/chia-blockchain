from typing import Dict, Any

# Uncomment to generate new GENESIS_BLOCK
#from tests.block_tools import BlockTools

#bt = BlockTools()

test_constants: Dict[str, Any] = {
    "DIFFICULTY_STARTING": 5,
    "DISCRIMINANT_SIZE_BITS": 16,
    "BLOCK_TIME_TARGET": 10,
    "MIN_BLOCK_TIME": 2,
    "DIFFICULTY_FACTOR": 3,
    "DIFFICULTY_EPOCH": 12,  # The number of blocks per epoch
    "DIFFICULTY_WARP_FACTOR": 4,  # DELAY divides EPOCH in order to warp efficiently.
    "DIFFICULTY_DELAY": 3,  # EPOCH / WARP_FACTOR
    "MIN_ITERS_STARTING": 50 * 2,
    "COINBASE_FREEZE_PERIOD": 0,
}

#test_constants["GENESIS_BLOCK"] = bytes(
    #bt.create_genesis_block(test_constants, bytes([0] * 32), b"0")
#)

#print(test_constants["GENESIS_BLOCK"])
