from __future__ import annotations

import logging
from datetime import datetime
from typing import Dict, List, Optional

from sortedcontainers import SortedDict

from chia.full_node.bitcoin_fee_estimator import create_bitcoin_fee_estimator
from chia.full_node.fee_estimation import FeeMempoolInfo
from chia.full_node.fee_estimator_interface import FeeEstimatorInterface
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.clvm_cost import CLVMCost
from chia.types.fee_rate import FeeRate
from chia.types.mempool_item import MempoolItem
from chia.util.ints import uint64


class Mempool:
    def __init__(self, max_size_in_cost: int, minimum_fee_per_cost_to_replace: uint64, max_block_cost_clvm: uint64):
        self.log = logging.getLogger(__name__)
        self.spends: Dict[bytes32, MempoolItem] = {}
        self.sorted_spends: SortedDict = SortedDict()
        self.removals: Dict[bytes32, List[bytes32]] = {}  # From removal coin id to spend bundle id
        self.max_size_in_cost: int = max_size_in_cost
        self.total_mempool_cost: int = 0
        self.minimum_fee_per_cost_to_replace: uint64 = minimum_fee_per_cost_to_replace
        self.fee_estimator: FeeEstimatorInterface = create_bitcoin_fee_estimator(max_block_cost_clvm, self.log)

    def get_min_fee_rate(self, cost: int) -> float:
        """
        Gets the minimum fpc rate that a transaction with specified cost will need in order to get included.
        """

        if self.at_full_capacity(cost):
            current_cost = self.total_mempool_cost

            # Iterates through all spends in increasing fee per cost
            fee_per_cost: float
            for fee_per_cost, spends_with_fpc in self.sorted_spends.items():
                for spend_name, item in spends_with_fpc.items():
                    current_cost -= item.cost
                    # Removing one at a time, until our transaction of size cost fits
                    if current_cost + cost <= self.max_size_in_cost:
                        return fee_per_cost
            raise ValueError(
                f"Transaction with cost {cost} does not fit in mempool of max cost {self.max_size_in_cost}"
            )
        else:
            return 0

    def remove_from_pool(self, items: List[bytes32]) -> None:
        """
        Removes an item from the mempool.
        """
        for spend_bundle_id in items:
            item: Optional[MempoolItem] = self.spends.get(spend_bundle_id)
            if item is None:
                continue
            assert item.name == spend_bundle_id
            removals: List[Coin] = item.removals
            for rem in removals:
                rem_name: bytes32 = rem.name()
                self.removals[rem_name].remove(spend_bundle_id)
                if len(self.removals[rem_name]) == 0:
                    del self.removals[rem_name]
            del self.spends[item.name]
            del self.sorted_spends[item.fee_per_cost][item.name]
            dic = self.sorted_spends[item.fee_per_cost]
            if len(dic.values()) == 0:
                del self.sorted_spends[item.fee_per_cost]
            self.total_mempool_cost -= item.cost
            assert self.total_mempool_cost >= 0
            mempool_info = self.get_mempool_info()
            self.fee_estimator.remove_mempool_item(mempool_info, item)

    def add_to_pool(self, item: MempoolItem) -> None:
        """
        Adds an item to the mempool by kicking out transactions (if it doesn't fit), in order of increasing fee per cost
        """

        while self.at_full_capacity(item.cost):
            # Val is Dict[hash, MempoolItem]
            fee_per_cost, val = self.sorted_spends.peekitem(index=0)
            to_remove: MempoolItem = list(val.values())[0]
            self.remove_from_pool([to_remove.name])

        self.spends[item.name] = item

        # sorted_spends is Dict[float, Dict[bytes32, MempoolItem]]
        if item.fee_per_cost not in self.sorted_spends:
            self.sorted_spends[item.fee_per_cost] = {}

        self.sorted_spends[item.fee_per_cost][item.name] = item

        for coin in item.removals:
            coin_id = coin.name()
            if coin_id not in self.removals:
                self.removals[coin_id] = []
            self.removals[coin_id].append(item.name)
        self.total_mempool_cost += item.cost

        mempool_info = self.get_mempool_info()
        self.fee_estimator.add_mempool_item(mempool_info, item)

    def at_full_capacity(self, cost: int) -> bool:
        """
        Checks whether the mempool is at full capacity and cannot accept a transaction with size cost.
        """

        return self.total_mempool_cost + cost > self.max_size_in_cost

    def get_mempool_info(self) -> FeeMempoolInfo:
        return FeeMempoolInfo(
            CLVMCost(uint64(self.max_size_in_cost)),
            FeeRate(uint64(self.minimum_fee_per_cost_to_replace)),
            CLVMCost(uint64(self.total_mempool_cost)),
            datetime.now(),
            CLVMCost(uint64(self.max_size_in_cost)),
        )
