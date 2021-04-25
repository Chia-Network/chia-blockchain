from enum import Enum


class ConditionCost(Enum):
    # Condition Costs
    AGG_SIG = 1200000  # the cost of one G1 subgroup check + aggregated signature validation
    CREATE_COIN = 1800000
    ASSERT_MY_COIN_ID = 0
    ASSERT_SECONDS_RELATIVE = 0
    ASSERT_SECONDS_ABSOLUTE = 0
    ASSERT_HEIGHT_RELATIVE = 0
    ASSERT_HEIGHT_ABSOLUTE = 0
    RESERVE_FEE = 0
    CREATE_COIN_ANNOUNCEMENT = 0
    ASSERT_COIN_ANNOUNCEMENT = 0
    CREATE_PUZZLE_ANNOUNCEMENT = 0
    ASSERT_PUZZLE_ANNOUNCEMENT = 0
