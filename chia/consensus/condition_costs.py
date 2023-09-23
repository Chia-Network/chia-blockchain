from __future__ import annotations

from enum import Enum


class ConditionCost(Enum):
    # Condition Costs
    AGG_SIG = 1200000  # the cost of one G1 subgroup check + aggregated signature validation
    CREATE_COIN = 1800000
