from src.util.ints import uint32, uint64


def calculate_block_reward(height: uint32) -> uint64:
    """
    Returns the coinbase reward at a certain block height.
    1 Chia coin = 16,000,000,000,000 = 16 trillion mojo.
    """
    return uint64(16000000000000)
