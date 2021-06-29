from enum import Enum


class Chain(Enum):
    CHALLENGE_CHAIN = 1
    REWARD_CHAIN = 2
    INFUSED_CHALLENGE_CHAIN = 3
    BLUEBOX = 4


class IterationType(Enum):
    SIGNAGE_POINT = 1
    INFUSION_POINT = 2
    END_OF_SUBSLOT = 3


class StateType(Enum):
    PEAK = 1
    END_OF_SUB_SLOT = 2
    FIRST_SUB_SLOT = 3
