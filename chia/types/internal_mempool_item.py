from __future__ import annotations

from dataclasses import dataclass
from typing import Dict

from chia.core.types.ints import uint32
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.mempool_item import BundleCoinSpend
from chia.types.spend_bundle import SpendBundle
from chia.types.spend_bundle_conditions import SpendBundleConditions


@dataclass
class InternalMempoolItem:
    spend_bundle: SpendBundle
    conds: SpendBundleConditions
    height_added_to_mempool: uint32
    # Map of coin ID to coin spend data between the bundle and its NPCResult
    bundle_coin_spends: Dict[bytes32, BundleCoinSpend]
