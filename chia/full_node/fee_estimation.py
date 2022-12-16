from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import List

from chia.types.clvm_cost import CLVMCost
from chia.types.fee_rate import FeeRate
from chia.types.mempool_item import MempoolItem
from chia.types.mojos import Mojos
from chia.util.ints import uint32


@dataclass(frozen=True)
class FeeMempoolInfo:
    """
    Information from Mempool and MempoolItems needed to estimate fees.
    Updated when `MemPoolItem`s are added or removed from the Mempool.

    Attributes:
        max_size_in_cost (uint64): This is the maximum capacity of the mempool, measured in XCH per CLVM Cost
        max_block_clvm_cost (CLVMCost): max CLVM cost allowed in a block
        minimum_fee_per_cost_to_replace (uint64): Smallest FPC that  might be accepted to replace another SpendBundle
        current_mempool_cost (uint64): This is the current "size" of the mempool, measured in CLVM Cost
        current_mempool_fees (Mojos):  Sum of fees for all spends waiting in the Mempool
        time (datetime): Local time this sample was taken

        Note that we use the node's local time, not "Blockchain time" for the timestamp above
    """

    max_size_in_cost: CLVMCost  # Max CLVMCost allowed in the Mempool total
    max_block_clvm_cost: CLVMCost  # Max CLVMCost allowed in a created block
    minimum_fee_per_cost_to_replace: FeeRate
    current_mempool_cost: CLVMCost  # Current sum of CLVM cost of all SpendBundles in mempool (mempool "size")
    current_mempool_fees: Mojos  # Sum of fees for all spends waiting in the Mempool
    time: datetime  # Local time this sample was taken


@dataclass(frozen=True)
class FeeMempoolItem:
    height_added: uint32
    fee_per_cost: FeeRate


@dataclass(frozen=True)
class FeeBlockInfo:  # See BlockRecord
    """
    Information from Blockchain needed to estimate fees.
    """

    block_height: uint32
    included_items: List[MempoolItem]
