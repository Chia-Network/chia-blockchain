from tad.util.ints import uint32, uint64

# 1 Tad coin = 1,000,000,000,000 = 1 trillion mtad.
_mtad_per_tad = 1000000000000
_blocks_per_year = 1681920  # 32 * 6 * 24 * 365
_blocks_per_week = int(_blocks_per_year / 52)
_blocks_per_half_year = int(_blocks_per_year / 2)

def calculate_pool_reward(height: uint32) -> uint64:
    """
    Returns the pool reward at a certain block height. The pool earns 7/8 of the reward in each block. If the farmer
    is solo farming, they act as the pool, and therefore earn the entire block reward.
    These halving events will not be hit at the exact times
    (3 years, etc), due to fluctuations in difficulty. They will likely come early, if the network space and VDF
    rates increase continuously.
    """
    return uint64(int(0))

    if height == 0:
        return uint64(int((7 / 8) * 200000 * _mtad_per_tad))
    elif height < 3 * _blocks_per_year:
        return uint64(int((7 / 8) * 2 * _mtad_per_tad))
    elif height < 6 * _blocks_per_year:
        return uint64(int((7 / 8) * 1 * _mtad_per_tad))
    elif height < 9 * _blocks_per_year:
        return uint64(int((7 / 8) * 0.5 * _mtad_per_tad))
    elif height < 12 * _blocks_per_year:
        return uint64(int((7 / 8) * 0.25 * _mtad_per_tad))
    else:
        return uint64(int((7 / 8) * 0.125 * _mtad_per_tad))


def calculate_base_farmer_reward(height: uint32) -> uint64:
    """
    Returns the coinbase reward at a certain block height. These halving events will not be hit at the exact times
    (3 years, etc), due to fluctuations in difficulty. They will likely come early, if the network space and VDF
    rates increase continuously.
    """

    if height == 0:
        return uint64(300000 * _mtad_per_tad)
    elif height < 3 * _blocks_per_year:
        return uint64(int(2 * _mtad_per_tad))
    elif height < 6 * _blocks_per_year:
        return uint64(int(1 * _mtad_per_tad))
    elif height < 9 * _blocks_per_year:
        return uint64(int(0.5 * _mtad_per_tad))
    elif height < 12 * _blocks_per_year:
        return uint64(int(0.25 * _mtad_per_tad))
    else:
        return uint64(1 * _mtad_per_tad)
