from __future__ import annotations

import chia_rs

ELIGIBLE_FOR_DEDUP = chia_rs.ELIGIBLE_FOR_DEDUP
if hasattr(chia_rs, "SpendConditions"):
    SpendConditions = chia_rs.SpendConditions
else:
    # Fallback to the old name if the new name does not exist
    SpendConditions = chia_rs.Spend
SpendBundleConditions = chia_rs.SpendBundleConditions
