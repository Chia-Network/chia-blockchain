from enum import Enum


class ConditionCost(Enum):
    # Condition Costs
    AGG_SIG = 20
    CREATE_COIN = 200
    ASSERT_COIN_CONSUMED = 5
    ASSERT_MY_COIN_ID = 5
    ASSERT_TIME_EXCEEDS = 5
    ASSERT_BLOCK_INDEX_EXCEEDS = 5
    ASSERT_BLOCK_AGE_EXCEEDS = 5
