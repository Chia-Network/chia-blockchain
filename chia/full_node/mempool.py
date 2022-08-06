from datetime import datetime
from typing import Dict, List

from sortedcontainers import SortedDict

from chia.policy.fee_estimation import FeeMempoolInfo
from chia.policy.fee_estimator import FeeEstimatorConfig, FeeEstimatorInterface
from chia.policy.fee_estimator_demo import FeeEstimatorDemo
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.mempool_item import MempoolItem
from chia.util.ints import uint64


class Mempool:
    def __init__(self, max_size_in_cost: int, minimum_fee_per_cost_to_replace: uint64):
        self.spends: Dict[bytes32, MempoolItem] = {}
        self.sorted_spends: SortedDict = SortedDict()
        self.additions: Dict[bytes32, MempoolItem] = {}
        self.removals: Dict[bytes32, MempoolItem] = {}
        self.max_size_in_cost: int = max_size_in_cost
        self.total_mempool_cost: int = 0
        self.minimum_fee_per_cost_to_replace = minimum_fee_per_cost_to_replace
        self.fee_estimator: FeeEstimatorInterface = FeeEstimatorDemo(config=FeeEstimatorConfig())

    def get_min_fee_rate(self, cost: int) -> float:  # xxx
        """
        Gets the minimum fpc rate that a transaction with specified cost will need in order to get included.
        """

        if self.at_full_capacity(cost):
            current_cost = self.total_mempool_cost

            # Iterates through all spends in increasing fee per cost
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

    def remove_from_pool(self, item: MempoolItem):
        """
        Removes an item from the mempool.
        """
        removals: List[Coin] = item.removals
        additions: List[Coin] = item.additions
        for rem in removals:
            del self.removals[rem.name()]
        for add in additions:
            del self.additions[add.name()]
        del self.spends[item.name]
        del self.sorted_spends[item.fee_per_cost][item.name]
        dic = self.sorted_spends[item.fee_per_cost]
        if len(dic.values()) == 0:
            del self.sorted_spends[item.fee_per_cost]
        self.total_mempool_cost -= item.cost
        assert self.total_mempool_cost >= 0

        mempool_info = FeeMempoolInfo(
            uint64(self.max_size_in_cost),
            uint64(self.minimum_fee_per_cost_to_replace),
            uint64(self.total_mempool_cost),
            datetime.now(),
        )
        self.fee_estimator.remove_mempool_item(mempool_info, item)

    def add_to_pool(
        self,
        item: MempoolItem,
    ):
        """
        Adds an item to the mempool by kicking out transactions (if it doesn't fit), in order of increasing fee per cost
        """

        while self.at_full_capacity(item.cost):
            # Val is Dict[hash, MempoolItem]
            fee_per_cost, val = self.sorted_spends.peekitem(index=0)
            to_remove = list(val.values())[0]
            self.remove_from_pool(to_remove)

        self.spends[item.name] = item

        # sorted_spends is Dict[float, Dict[bytes32, MempoolItem]]
        if item.fee_per_cost not in self.sorted_spends:
            self.sorted_spends[item.fee_per_cost] = {}

        self.sorted_spends[item.fee_per_cost][item.name] = item

        for add in item.additions:
            self.additions[add.name()] = item
        for coin in item.removals:
            self.removals[coin.name()] = item
        self.total_mempool_cost += item.cost

        mempool_info = FeeMempoolInfo(
            uint64(self.max_size_in_cost),
            uint64(self.minimum_fee_per_cost_to_replace),
            uint64(self.total_mempool_cost),
            datetime.now(),
        )
        self.fee_estimator.add_mempool_item(mempool_info, item)

    def at_full_capacity(self, cost: int) -> bool:
        """
        Checks whether the mempool is at full capacity and cannot accept a transaction with size cost.
        """

        return self.total_mempool_cost + cost > self.max_size_in_cost
