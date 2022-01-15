if __name__ == "__main__":
    from tests.block_tools import create_block_tools, test_constants
    from tests.util.keyring import TempKeyring
    from chinilla.util.default_root import DEFAULT_ROOT_PATH

    with TempKeyring() as keychain:
        # TODO: mariano: fix this with new consensus
        bt = create_block_tools(root_path=DEFAULT_ROOT_PATH, keychain=keychain)
        # TODO: address hint error and remove ignore
        #       error: Argument 2 to "create_genesis_block" of "BlockTools" has incompatible type "bytes"; expected
        #       "bytes32"  [arg-type]
        new_genesis_block = bt.create_genesis_block(test_constants, b"0")  # type: ignore[arg-type]

        print(bytes(new_genesis_block))
