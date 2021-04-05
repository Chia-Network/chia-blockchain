from dataclasses import dataclass
from typing import List

from chia.consensus.cost_calculator import CostResult
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.spend_bundle import SpendBundle
from chia.util.ints import uint64
from chia.util.streamable import Streamable, streamable


@dataclass(frozen=True)
@streamable
class MempoolItem(Streamable):
    spend_bundle: SpendBundle
    fee: uint64
    cost_result: CostResult
    spend_bundle_name: bytes32
    additions: List[Coin]
    removals: List[Coin]

    def __lt__(self, other):
        # TODO test to see if it's < or >
        return self.fee_per_cost < other.fee_per_cost

    @property
    def fee_per_cost(self) -> float:
        return int(self.fee) / int(self.cost_result.cost)

    @property
    def name(self) -> bytes32:
        return self.spend_bundle_name
