from __future__ import annotations

from enum import Enum


class ConditionCost(Enum):
    # Condition Costs
    AGG_SIG = 1200000  # the cost of one G1 subgroup check + aggregated signature validation
    CREATE_COIN = 1800000

    # with hard fork 2 (Chia 3.0) all conditions past the first 100 (per spend)
    # has an additional cost of 500
    GENERIC_CONDITION_COST = 500
