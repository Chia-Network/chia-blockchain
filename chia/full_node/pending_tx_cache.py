from __future__ import annotations

from typing import Dict

from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.mempool_item import MempoolItem


class PendingTxCache:
    _cache_max_total_cost: int
    _cache_cost: int
    _txs: Dict[bytes32, MempoolItem]

    def __init__(self, cost_limit: int):
        self._cache_max_total_cost = cost_limit
        self._cache_cost = 0
        self._txs = {}

    def add(self, item: MempoolItem) -> None:
        """
        Adds SpendBundles that have failed to be added to the pool in potential tx set.
        This is later used to retry to add them.
        """
        if item.spend_bundle_name in self._txs:
            return None

        self._txs[item.spend_bundle_name] = item
        self._cache_cost += item.cost

        while self._cache_cost > self._cache_max_total_cost:
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
