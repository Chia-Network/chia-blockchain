from __future__ import annotations

from enum import Enum


class ConditionCost(Enum):
    # Condition Costs
    AGG_SIG = 1200000  # the cost of one G1 subgroup check + aggregated signature validation
    CREATE_COIN = 1800000

    # with hard fork 2 (Chia 3.0) all spends have a cost
    SPEND_COST = CREATE_COIN // 4
    NEW_CREATE_COIN = CREATE_COIN - SPEND_COST

    # with hard fork 2 (Chia 3.0) all conditions have a cost
    # SEND/RECEIVE MESSAGE and CREATE/ASSERT ANNOUNCEMENT
    MESSAGE_CONDITION_COST = 700
    # all other conditions
    GENERIC_CONDITION_COST = 200
