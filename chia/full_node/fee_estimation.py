from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import List

from chia.types.clvm_cost import CLVMCost
from chia.types.fee_rate import FeeRate
from chia.types.mempool_item import MempoolItem
from chia.types.mojos import Mojos
from chia.util.ints import uint32, uint64


@dataclass(frozen=True)
class MempoolInfo:
    """
    Information from the Mempool needed to estimate fees.
    This information is constant during the lifetime of the FullNode process
    Attributes:
        max_size_in_cost (uint64): This is the maximum capacity of the mempool, measured in XCH per CLVM Cost
        minimum_fee_per_cost_to_replace (uint64): Smallest FPC that  might be accepted to replace another SpendBundle
        max_block_clvm_cost (uint64): Max allowed cost of a farmed block
    """

    max_size_in_cost: CLVMCost  # Mempool max allowed CLVM cost total
    minimum_fee_per_cost_to_replace: FeeRate
    max_block_clvm_cost: CLVMCost  # Max CLVMCost allowed in the Mempool


@dataclass(frozen=True)
class FeeMempoolInfo:
    """
    Information from Mempool and MempoolItems needed to estimate fees.
    Updated when `MemPoolItem`s are added or removed from the Mempool.
    This information is more dynamic in nature than the info in `MempoolInfo`

    Attributes:
        mempool_info (MempoolInfo): A `MempoolInfo`, defined above. Parameters of our mempool.
        current_mempool_cost (uint64):This is the current capacity of the mempool, measured in XCH per CLVM Cost
        current_mempool_fees (Mojos): Sum of fees for all spends waiting in the Mempool
        time (datetime): Local time this sample was taken

        Note that we use the node's local time, not "Blockchain time" for the timestamp above
    """

    mempool_info: MempoolInfo
    current_mempool_cost: CLVMCost  # Current sum of CLVM cost of all SpendBundles in mempool (mempool "size")
    current_mempool_fees: Mojos  # Sum of fees for all spends waiting in the Mempool
    time: datetime  # Local time this sample was taken


EmptyMempoolInfo = MempoolInfo(
    CLVMCost(uint64(0)), FeeRate.create(Mojos(uint64(0)), CLVMCost(uint64(1))), CLVMCost(uint64(0))
)


EmptyFeeMempoolInfo = FeeMempoolInfo(
    EmptyMempoolInfo,
    CLVMCost(uint64(0)),
    Mojos(uint64(0)),
    datetime.min,
)


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
