from src.consensus.constants import constants

test_constants = constants.replace(
    **{
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
        "NUMBER_ZERO_BITS_PLOT_FILTER": 1,  # H(plot signature of the challenge) must start with these many zeroes
        "NUMBER_ZERO_BITS_ICP_FILTER": 1,  # H(plot signature of the challenge) must start with these many zeroes
        "CLVM_COST_RATIO_CONSTANT": 108,
        "COINBASE_FREEZE_PERIOD": 0,
    }
)

if __name__ == "__main__":
    from src.util.default_root import DEFAULT_ROOT_PATH
    from src.util.block_tools import BlockTools

    # TODO: mariano: fix this with new consensus
    bt = BlockTools(root_path=DEFAULT_ROOT_PATH)
    new_genesis_block = bt.create_genesis_block(test_constants, bytes([0] * 32), b"0")

    print(bytes(new_genesis_block))
