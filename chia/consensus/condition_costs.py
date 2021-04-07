from enum import Enum


class ConditionCost(Enum):
    # Condition Costs
    AGG_SIG = 92  # 1 ms BLS verify = 10,000 clvm cost / 108 cost multiplier
    CREATE_COIN = 200
    ASSERT_MY_COIN_ID = 0
    ASSERT_SECONDS_NOW_EXCEEDS = 0
    ASSERT_SECONDS_AGE_EXCEEDS = 0
    ASSERT_HEIGHT_NOW_EXCEEDS = 0
    ASSERT_HEIGHT_AGE_EXCEEDS = 0
    RESERVE_FEE = 0
    CREATE_ANNOUNCEMENT_WITH_ID = 0
    ASSERT_ANNOUNCEMENT = 0
