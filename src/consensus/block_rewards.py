from src.consensus.constants import ConsensusConstants
from src.util.ints import uint32, uint64

"""
    These are the rewards, divided into 7/8 for the pool and 1/8 for the farmer.
    First block: TBD
    1 chia - first 5 years
    0.5 chia - second 5 years
    0.25 chia - third 5 years
    0.125 chia - then and infinity
"""


def calculate_pool_reward(constants: ConsensusConstants, height: uint32) -> uint64:
    """
    Returns the coinbase reward at a certain block height.
    1 Chia coin = 1,000,000,000,000 = 1 trillion mojo.
    """

    if height == 0:
        # Pre-farm reward goes to the pre-farm pool key (which is hard-coded in constants)
        # TODO: put final amount
        return uint64(500000000000000000)
    if height < constants.NUM_BLOCKS_HALVING:
        # First 5 years
        return uint64(875000000000)
    if height < constants.NUM_BLOCKS_HALVING * 2:
        # Second 5 years
        return uint64(875000000000 // 2)
    if height < constants.NUM_BLOCKS_HALVING * 3:
        # Third 5 years
        return uint64(875000000000 // 4)
    # Then and infinity
    return uint64(875000000000 // 8)


def calculate_base_farmer_reward(constants: ConsensusConstants, height: uint32) -> uint64:
    """
    Returns the base farmer reward at a certain block height.
    1 base fee reward is 1/8 of total block reward
    """
    if height < constants.NUM_BLOCKS_HALVING:
        # First 5 years
        return uint64(125000000000)
    if height < constants.NUM_BLOCKS_HALVING * 2:
        # Second 5 years
        return uint64(125000000000 // 2)
    if height < constants.NUM_BLOCKS_HALVING * 3:
        # Third 5 years
        return uint64(125000000000 // 4)
    # Then and infinity
    return uint64(125000000000 // 8)
