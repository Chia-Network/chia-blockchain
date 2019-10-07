from src.util.ints import uint64, uint32


def calculate_block_reward(height: uint32) -> uint64:
    """
    Returns the coinbase reward at a certain block height.
    # TODO: implement real block schedule
    """
    return uint64(10)
