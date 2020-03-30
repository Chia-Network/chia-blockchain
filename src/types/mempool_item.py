from dataclasses import dataclass

from src.types.spend_bundle import SpendBundle
from src.types.sized_bytes import bytes32
from src.util.ints import uint64


@dataclass(frozen=True)
class MempoolItem:
    spend_bundle: SpendBundle
    fee_per_cost: float
    fee: uint64
    cost: uint64

    def __lt__(self, other):
        # TODO test to see if it's < or >
        return self.fee_per_cost < other.fee_per_cost

    @property
    def name(self) -> bytes32:
        return self.spend_bundle.name()
