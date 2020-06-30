from typing import Dict

from src.consensus.constants import constants
from src.util.block_tools import BlockTools


def make_test_constants_with_genesis(test_constants_overrides: Dict):
    test_constants = constants.replace(**test_constants_overrides)

    bt = BlockTools()

    new_genesis_block = bt.create_genesis_block(test_constants, bytes([0] * 32), b"0")

    final_test_constants = test_constants.replace(
        GENESIS_BLOCK=bytes(new_genesis_block)
    )

    return final_test_constants, bt
