from typing import Dict

from src.consensus.default_constants import DEFAULT_CONSTANTS
from src.util.block_tools import BlockTools


def make_test_constants_with_genesis(test_constants_overrides: Dict):
    test_constants = make_test_constants_without_genesis(test_constants_overrides)

    bt = BlockTools()

    new_genesis_block = bt.create_genesis_block(test_constants, bytes([0] * 32), b"0")

    final_test_constants = test_constants.replace(
        GENESIS_BLOCK=bytes(new_genesis_block)
    )

    return final_test_constants, bt


def make_test_constants_without_genesis(test_constants_overrides: Dict):

    test_constants = DEFAULT_CONSTANTS.replace(**test_constants_overrides)

    return test_constants
