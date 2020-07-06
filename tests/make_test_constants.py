from typing import Dict

from src.consensus.constants import constants
from .block_tools import BlockTools


def make_test_constants_with_genesis(test_constants_overrides: Dict):
    print("AMKING TESTS CONSTANTS")

    test_constants = constants.replace(**test_constants_overrides)

    bt = BlockTools()

    new_genesis_block = bt.create_genesis_block(test_constants, bytes([0] * 32), b"0")
    print("genesis:", new_genesis_block)

    final_test_constants = test_constants.replace(
        GENESIS_BLOCK=bytes(new_genesis_block)
    )
    return final_test_constants, bt
