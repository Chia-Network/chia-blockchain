from __future__ import annotations

import chia_rs

ELIGIBLE_FOR_DEDUP = chia_rs.ELIGIBLE_FOR_DEDUP
try:
    SpendConditions = chia_rs.SpendConditions
except AttributeError:
    # Fallback to the old name if the new name does not exist
    SpendConditions = chia_rs.Spend
SpendBundleConditions = chia_rs.SpendBundleConditions
