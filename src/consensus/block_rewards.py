from src.util.ints import uint32, uint64


def calculate_block_reward(height: uint32) -> uint64:
    """
    Returns the coinbase reward at a certain block height.
    """
    return uint64(1000000000)
