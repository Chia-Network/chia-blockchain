from dataclasses import dataclass
from typing import List

from src.consensus.cost_calculator import CostResult
from src.types.blockchain_format.coin import Coin
from src.types.spend_bundle import SpendBundle
from src.types.blockchain_format.sized_bytes import bytes32
from src.util.ints import uint64


@dataclass(frozen=True)
class MempoolItem:
    spend_bundle: SpendBundle
    fee_per_cost: float
    fee: uint64
    cost_result: CostResult
    spend_bundle_name: bytes32
    additions: List[Coin]
    removals: List[Coin]

    def __lt__(self, other):
        # TODO test to see if it's < or >
        return self.fee_per_cost < other.fee_per_cost

    @property
    def name(self) -> bytes32:
        return self.spend_bundle_name
