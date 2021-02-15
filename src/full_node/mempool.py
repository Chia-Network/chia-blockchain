from typing import List, Dict

from sortedcontainers import SortedDict

from src.types.blockchain_format.coin import Coin
from src.types.mempool_item import MempoolItem
from src.types.blockchain_format.sized_bytes import bytes32


class Mempool:
    spends: Dict[bytes32, MempoolItem]
    sorted_spends: SortedDict  # Dict[float, Dict[bytes32, MempoolItem]]
    additions: Dict[bytes32, MempoolItem]
    removals: Dict[bytes32, MempoolItem]
    size: int

    # if new min fee is added
    @staticmethod
    def create(size: int):
        self = Mempool()
        self.spends = {}
        self.additions = {}
        self.removals = {}
        self.sorted_spends = SortedDict()
        self.size = size
        return self

    def get_min_fee_rate(self) -> float:
        if self.at_full_capacity():
            fee_per_cost, val = self.sorted_spends.peekitem(index=0)
            return fee_per_cost
        else:
            return 0

    def remove_spend(self, item: MempoolItem):
        removals: List[Coin] = item.spend_bundle.removals()
        additions: List[Coin] = item.spend_bundle.additions()
        for rem in removals:
            del self.removals[rem.name()]
        for add in additions:
            del self.additions[add.name()]
        del self.spends[item.name]
        del self.sorted_spends[item.fee_per_cost][item.name]
        dic = self.sorted_spends[item.fee_per_cost]
        if len(dic.values()) == 0:
            del self.sorted_spends[item.fee_per_cost]

    def add_to_pool(
        self,
        item: MempoolItem,
        additions: List[Coin],
        removals_dic: Dict[bytes32, Coin],
    ):
        if self.at_full_capacity():
            # Val is Dict[hash, MempoolItem]
            fee_per_cost, val = self.sorted_spends.peekitem(index=0)
            to_remove = list(val.values())[0]
            self.remove_spend(to_remove)

        self.spends[item.name] = item

        # sorted_spends is Dict[float, Dict[bytes32, MempoolItem]]
        if item.fee_per_cost in self.sorted_spends:
            self.sorted_spends[item.fee_per_cost][item.name] = item
        else:
            self.sorted_spends[item.fee_per_cost] = {}
            self.sorted_spends[item.fee_per_cost][item.name] = item

        for add in additions:
            self.additions[add.name()] = item
        for key in removals_dic.keys():
            self.removals[key] = item

    def at_full_capacity(self) -> bool:
        return len(self.spends.keys()) >= self.size
