from __future__ import annotations

from chia_rs.sized_ints import uint32
from typing_extensions import Protocol

from chia.full_node.fee_estimation import FeeBlockInfo, FeeMempoolInfo, MempoolItemInfo
from chia.types.clvm_cost import CLVMCost
from chia.types.fee_rate import FeeRateV2


class FeeEstimatorInterface(Protocol):
    def new_block_height(self, block_height: uint32) -> None:
        """Called immediately when block height changes. Can be called multiple times before `new_block`"""

    def new_block(self, block_info: FeeBlockInfo) -> None:
        """A new transaction block has been added to the blockchain"""

    def add_mempool_item(self, mempool_item_info: FeeMempoolInfo, mempool_item: MempoolItemInfo) -> None:
        """A MempoolItem (transaction and associated info) has been added to the mempool"""

    def remove_mempool_item(self, mempool_info: FeeMempoolInfo, mempool_item: MempoolItemInfo) -> None:
        """A MempoolItem (transaction and associated info) has been removed from the mempool"""

    def estimate_fee_rate(self, *, time_offset_seconds: int) -> FeeRateV2:
        """time_offset_seconds: number of seconds into the future for which to estimate fee"""

    def mempool_size(self) -> CLVMCost:
        """Report last seen mempool size"""

    def mempool_max_size(self) -> CLVMCost:
        """Report current mempool max "size" (i.e. CLVM cost)"""

    def get_mempool_info(self) -> FeeMempoolInfo:
        """Report Mempool current configuration and state"""
