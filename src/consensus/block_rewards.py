from src.util.ints import uint32, uint64


def calculate_block_reward(height: uint32) -> uint64:
    """
    Returns the coinbase reward at a certain block height.
    1 Chia coin = 16,000,000,000,000 = 16 trillion mojo.
    """
    if height == 0:
        return uint64(500000000000000000)
    return uint64(14000000000000)


def calculate_base_fee(height: uint32) -> uint64:
    """
    Returns the base fee reward at a certain block height.
    1 base fee reward is 1/8 of total block reward
    """
    return uint64(2000000000000)
