from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional

from sortedcontainers import SortedDict

from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.mempool_item import MempoolItem
from chia.util.ints import uint32


@dataclass
class ConflictTxCache:
    _cache_max_total_cost: int
    _cache_max_size: int = 1000
    _cache_cost: int = field(default=0, init=False)
    _txs: Dict[bytes32, MempoolItem] = field(default_factory=dict, init=False)

    def get(self, bundle_name: bytes32) -> Optional[MempoolItem]:
        return self._txs.get(bundle_name, None)

    def add(self, item: MempoolItem) -> None:
        """
        Adds SpendBundles that have failed to be added to the pool in potential tx set.
        This is later used to retry to add them.
        """
        name = item.name

        if name in self._txs:
            return None

        self._txs[name] = item
        self._cache_cost += item.cost

        while self._cache_cost > self._cache_max_total_cost or len(self._txs) > self._cache_max_size:
            first_in = list(self._txs.keys())[0]
            self._cache_cost -= self._txs[first_in].cost
            self._txs.pop(first_in)

    def drain(self) -> Dict[bytes32, MempoolItem]:
        ret = self._txs
        self._txs = {}
        self._cache_cost = 0
        return ret

    def cost(self) -> int:
        return self._cache_cost


@dataclass
class PendingTxCache:
    _cache_max_total_cost: int
    _cache_max_size: int = 3000
    _cache_cost: int = field(default=0, init=False)
    _txs: Dict[bytes32, MempoolItem] = field(default_factory=dict, init=False)
    _by_height: SortedDict[uint32, Dict[bytes32, MempoolItem]] = field(default_factory=SortedDict, init=False)

    def get(self, bundle_name: bytes32) -> Optional[MempoolItem]:
        return self._txs.get(bundle_name, None)

    def add(self, item: MempoolItem) -> None:
        """
        Adds SpendBundles that are not yet valid because of a height assertion.
        They will be re-tried once their height requirement is satisfied
        """
        assert item.assert_height is not None

        name = item.name

        if name in self._txs:
            return None

        self._txs[name] = item
        self._cache_cost += item.cost
        self._by_height.setdefault(item.assert_height, {})[name] = item

        while self._cache_cost > self._cache_max_total_cost or len(self._txs) > self._cache_max_size:
            # we start removing items with the highest assert_height first
            to_evict = self._by_height.items()[-1]
            if to_evict[1] == {}:
                self._txs.pop(to_evict[0])
                continue

            first_in = list(to_evict[1].keys())[0]
            removed_item = self._txs.pop(first_in)
            self._cache_cost -= removed_item.cost
            to_evict[1].pop(first_in)
            if to_evict[1] == {}:
                self._by_height.popitem()

    def drain(self, up_to_height: uint32) -> Dict[bytes32, MempoolItem]:
        ret: Dict[bytes32, MempoolItem] = {}

        if self._txs == {}:
            return ret

        height_line = self._by_height.items()[0]
        while height_line[0] < up_to_height:
            ret.update(height_line[1])
            for name, item in height_line[1].items():
                self._cache_cost -= item.cost
                self._txs.pop(name)
            self._by_height.popitem(0)
            if len(self._by_height) == 0:
                break
            height_line = self._by_height.items()[0]

        return ret

    def cost(self) -> int:
        return self._cache_cost
