# Uncomment to generate new GENESIS_BLOCK
# from tests.block_tools import BlockTools

# bt = BlockTools()
from src.util.make_test_constants import make_test_constants_with_genesis


test_constants = make_test_constants_with_genesis(
    {
        "DIFFICULTY_STARTING": 1,
        "DISCRIMINANT_SIZE_BITS": 8,
        "BLOCK_TIME_TARGET": 10,
        "DIFFICULTY_EPOCH": 12,  # The number of blocks per epoch
        "DIFFICULTY_DELAY": 3,  # EPOCH / WARP_FACTOR
        "PROPAGATION_THRESHOLD": 10,
        "PROPAGATION_DELAY_THRESHOLD": 20,
        "TX_PER_SEC": 1,
        "MEMPOOL_BLOCK_BUFFER": 10,
        "MIN_ITERS_STARTING": 50 * 1,
        "CLVM_COST_RATIO_CONSTANT": 108,
        "COINBASE_FREEZE_PERIOD": 0,
    }
)

# test_constants["GENESIS_BLOCK"] = bytes(
# bt.create_genesis_block(test_constants, bytes([0] * 32), b"0")
# )

# print(test_constants["GENESIS_BLOCK"])
