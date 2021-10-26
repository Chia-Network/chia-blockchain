from chia.util.ints import uint32, uint64

# 1 Sit coin = 1,000,000,000,000 = 1 trillion mojo.
_mojo_per_chia = 1000000000000
_blocks_per_year = 1681920  # 32 * 6 * 24 * 365

# preserve + testnet supply
PREFARM = 1000000

# TODO fork height to be decided
# after reward hardfork activated, all the block rewards go to farmer,
# because the pool contract singleton can't migrated to the forked chains,
# so the pool protocol don't work in forked chains without re-plotting.
REWARD_HARDFORK_HEIGHT = 2 ** 32 - 1


def reward_hardfork_activated(height: uint32) -> bool:
    return height >= REWARD_HARDFORK_HEIGHT


def calculate_pool_reward(height: uint32) -> uint64:
    """
    Returns the pool reward at a certain block height. The pool earns 7/8 of the reward in each block. If the farmer
    is solo farming, they act as the pool, and therefore earn the entire block reward.
    These halving events will not be hit at the exact times
    (3 years, etc), due to fluctuations in difficulty. They will likely come early, if the network space and VDF
    rates increase continuously.
    """
    if reward_hardfork_activated(height):
        return 0

    if height == 0:
        return uint64(int((7 / 8) * PREFARM * _mojo_per_chia))
    elif height < 3 * _blocks_per_year:
        return uint64(int((7 / 8) * 1 * _mojo_per_chia))
    elif height < 6 * _blocks_per_year:
        return uint64(int((7 / 8) * 0.5 * _mojo_per_chia))
    elif height < 9 * _blocks_per_year:
        return uint64(int((7 / 8) * 0.25 * _mojo_per_chia))
    else:
        return uint64(int((7 / 8) * 0.125 * _mojo_per_chia))


def calculate_base_farmer_reward(height: uint32) -> uint64:
    """
    Returns the base farmer reward at a certain block height.
    The base fee reward is 1/8 of total block reward

    Returns the coinbase reward at a certain block height. These halving events will not be hit at the exact times
    (3 years, etc), due to fluctuations in difficulty. They will likely come early, if the network space and VDF
    rates increase continuously.
    """
    if reward_hardfork_activated(height):
        coefficient = 1.0
    else:
        coefficient = 1 / 8

    if height == 0:
        return uint64(int(coefficient * PREFARM * _mojo_per_chia))
    elif height < 3 * _blocks_per_year:
        return uint64(int(coefficient * 1 * _mojo_per_chia))
    elif height < 6 * _blocks_per_year:
        return uint64(int(coefficient * 0.5 * _mojo_per_chia))
    elif height < 9 * _blocks_per_year:
        return uint64(int(coefficient * 0.25 * _mojo_per_chia))
    else:
        return uint64(int(coefficient * 0.125 * _mojo_per_chia))
