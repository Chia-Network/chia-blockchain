from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional

from sortedcontainers import SortedDict

from chia.full_node.fee_estimation import FeeMempoolInfo, MempoolInfo
from chia.full_node.fee_estimator_interface import FeeEstimatorInterface
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.clvm_cost import CLVMCost
from chia.types.mempool_item import MempoolItem
from chia.util.ints import uint64


class MempoolRemoveReason(Enum):
    CONFLICT = 1
    BLOCK_INCLUSION = 2
    POOL_FULL = 3


class Mempool:
    def __init__(self, mempool_info: MempoolInfo, fee_estimator: FeeEstimatorInterface):
        self._spends: Dict[bytes32, MempoolItem] = {}
        self._sorted_spends: SortedDict = SortedDict()
        self.mempool_info: MempoolInfo = mempool_info
        self.fee_estimator: FeeEstimatorInterface = fee_estimator
        self._removal_coin_id_to_spendbundle_ids: Dict[bytes32, List[bytes32]] = {}
        self._total_mempool_cost: CLVMCost = CLVMCost(uint64(0))
        self._total_mempool_fees: int = 0

    def total_mempool_fees(self) -> int:
        return self._total_mempool_fees

    def total_mempool_cost(self) -> CLVMCost:
        return self._total_mempool_cost

    def all_spends(self) -> List[MempoolItem]:
        return list(self._spends.values())

    def all_spend_ids(self) -> List[bytes32]:
        return list(self._spends.keys())

    def spends_by_feerate(self) -> List[MempoolItem]:
        ret: List[MempoolItem] = []
        for spends_with_fpc in reversed(self._sorted_spends.values()):
            ret.extend(spends_with_fpc.values())
        return ret

    def size(self) -> int:
        return len(self._spends)

    def get_spend_by_id(self, spend_bundle_id: bytes32) -> Optional[MempoolItem]:
        return self._spends.get(spend_bundle_id, None)

    def get_spends_by_coin_id(self, spent_coin_id: bytes32) -> List[MempoolItem]:
        spend_bundle_ids = self._removal_coin_id_to_spendbundle_ids.get(spent_coin_id)
        if spend_bundle_ids is None:
            return []
        ret: List[MempoolItem] = []
        for spend_bundle_id in spend_bundle_ids:
            ret.append(self._spends[spend_bundle_id])
        return ret

    def get_min_fee_rate(self, cost: int) -> float:
        """
        Gets the minimum fpc rate that a transaction with specified cost will need in order to get included.
        """

        if self.at_full_capacity(cost):
            current_cost = self._total_mempool_cost

            # Iterates through all spends in increasing fee per cost
            fee_per_cost: float
            for fee_per_cost, spends_with_fpc in self._sorted_spends.items():
                for spend_name, item in spends_with_fpc.items():
                    current_cost -= item.cost
                    # Removing one at a time, until our transaction of size cost fits
                    if current_cost + cost <= self.mempool_info.max_size_in_cost:
                        return fee_per_cost
            raise ValueError(
                f"Transaction with cost {cost} does not fit in mempool of max cost {self.mempool_info.max_size_in_cost}"
            )
        else:
            return 0

    def remove_from_pool(self, items: List[bytes32], reason: MempoolRemoveReason) -> None:
        """
        Removes an item from the mempool.
        """
        for spend_bundle_id in items:
            item: Optional[MempoolItem] = self._spends.get(spend_bundle_id)
            if item is None:
                continue
            assert item.name == spend_bundle_id
            removals: List[Coin] = item.removals
            for rem in removals:
                rem_name: bytes32 = rem.name()
                self._removal_coin_id_to_spendbundle_ids[rem_name].remove(spend_bundle_id)
                if len(self._removal_coin_id_to_spendbundle_ids[rem_name]) == 0:
                    del self._removal_coin_id_to_spendbundle_ids[rem_name]
            del self._spends[item.name]
            del self._sorted_spends[item.fee_per_cost][item.name]
            dic = self._sorted_spends[item.fee_per_cost]
            if len(dic.values()) == 0:
                del self._sorted_spends[item.fee_per_cost]
            self._total_mempool_cost = CLVMCost(uint64(self._total_mempool_cost - item.cost))
            self._total_mempool_fees = self._total_mempool_fees - item.fee
            assert self._total_mempool_cost >= 0
            info = FeeMempoolInfo(self.mempool_info, self._total_mempool_cost, self._total_mempool_fees, datetime.now())
            if reason != MempoolRemoveReason.BLOCK_INCLUSION:
                self.fee_estimator.remove_mempool_item(info, item)

    def add_to_pool(self, item: MempoolItem) -> None:
        """
        Adds an item to the mempool by kicking out transactions (if it doesn't fit), in order of increasing fee per cost
        """

        assert item.npc_result.conds is not None

        while self.at_full_capacity(item.cost):
            # Val is Dict[hash, MempoolItem]
            fee_per_cost, val = self._sorted_spends.peekitem(index=0)
            to_remove: MempoolItem = list(val.values())[0]
            self.remove_from_pool([to_remove.name], MempoolRemoveReason.POOL_FULL)

        self._spends[item.name] = item

        # _sorted_spends is Dict[float, Dict[bytes32, MempoolItem]]
        if item.fee_per_cost not in self._sorted_spends:
            self._sorted_spends[item.fee_per_cost] = {}

        self._sorted_spends[item.fee_per_cost][item.name] = item

        for coin in item.removals:
            coin_id = coin.name()
            if coin_id not in self._removal_coin_id_to_spendbundle_ids:
                self._removal_coin_id_to_spendbundle_ids[coin_id] = []
            self._removal_coin_id_to_spendbundle_ids[coin_id].append(item.name)

        self._total_mempool_cost = CLVMCost(uint64(self._total_mempool_cost + item.cost))
        self._total_mempool_fees = self._total_mempool_fees + item.fee
        info = FeeMempoolInfo(self.mempool_info, self._total_mempool_cost, self._total_mempool_fees, datetime.now())
        self.fee_estimator.add_mempool_item(info, item)

    def at_full_capacity(self, cost: int) -> bool:
        """
        Checks whether the mempool is at full capacity and cannot accept a transaction with size cost.
        """

        return self._total_mempool_cost + cost > self.mempool_info.max_size_in_cost
