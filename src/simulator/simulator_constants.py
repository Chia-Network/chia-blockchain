from src.consensus.default_constants import DEFAULT_CONSTANTS

test_constants = DEFAULT_CONSTANTS.replace(
    **{
        "DIFFICULTY_STARTING": 1,
        "DISCRIMINANT_SIZE_BITS": 8,
        "SUB_SLOT_TIME_TARGET": 300,
        "TX_PER_SEC": 1,
        "MEMPOOL_BLOCK_BUFFER": 10,
        "SUB_SLOT_ITERS_STARTING": 2 ** 10,
        "NUMBER_ZERO_BITS_PLOT_FILTER": 1,  # H(plot signature of the challenge) must start with these many zeroes
        "CLVM_COST_RATIO_CONSTANT": 108,
    }
)

if __name__ == "__main__":
    from src.util.default_root import DEFAULT_ROOT_PATH
    from src.util.block_tools import BlockTools

    # TODO: mariano: fix this with new consensus
    bt = BlockTools(root_path=DEFAULT_ROOT_PATH)
    new_genesis_block = bt.create_genesis_block(test_constants, b"0")

    print(bytes(new_genesis_block))
