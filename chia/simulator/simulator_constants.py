if __name__ == "__main__":
    from tests.block_tools import BlockTools, test_constants
    from chia.util.default_root import DEFAULT_ROOT_PATH

    # TODO: mariano: fix this with new consensus
    bt = BlockTools(root_path=DEFAULT_ROOT_PATH)
    new_genesis_block = bt.create_genesis_block(test_constants, b"0")

    print(bytes(new_genesis_block))
