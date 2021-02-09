from src.util.ints import uint32, uint64


def calculate_pool_reward(height: uint32) -> uint64:
    """
    Returns the coinbase reward at a certain block height.
    1 Chia coin = 1,000,000,000,000 = 1 trillion mojo.
    These are temporary testnet numbers to test halvings
    """
    if height == 0:
        return uint64(500000000000000000)
    if height < 2000:
        return uint64(875000000000)
    if height < 4000:
        return uint64(875000000000 // 2)
    if height < 6000:
        return uint64(875000000000 // 4)
    return uint64(875000000000 // 8)


def calculate_base_farmer_reward(height: uint32) -> uint64:
    """
    Returns the base farmer reward at a certain block height.
    1 base fee reward is 1/8 of total block reward
    These are temporary testnet numbers to test halvings
    """
    if height < 2000:
        return uint64(125000000000)
    if height < 4000:
        return uint64(125000000000 // 2)
    if height < 6000:
        return uint64(125000000000 // 4)
    return uint64(125000000000 // 8)
