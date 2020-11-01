from enum import Enum


class ConditionCost(Enum):
    # Condition Costs
    AGG_SIG = 20
    CREATE_COIN = 200
    ASSERT_COIN_CONSUMED = 0
    ASSERT_MY_COIN_ID = 0
    ASSERT_TIME_EXCEEDS = 0
    ASSERT_BLOCK_INDEX_EXCEEDS = 0
    ASSERT_BLOCK_AGE_EXCEEDS = 0
    ASSERT_FEE = 0
