from dataclasses import dataclass
from typing import List

from hddcoin.consensus.cost_calculator import NPCResult
from hddcoin.types.blockchain_format.coin import Coin
from hddcoin.types.blockchain_format.program import SerializedProgram
from hddcoin.types.blockchain_format.sized_bytes import bytes32
from hddcoin.types.spend_bundle import SpendBundle
from hddcoin.util.ints import uint64
from hddcoin.util.streamable import Streamable, streamable


@dataclass(frozen=True)
@streamable
class MempoolItem(Streamable):
    spend_bundle: SpendBundle
    fee: uint64
    npc_result: NPCResult
    cost: uint64
    spend_bundle_name: bytes32
    additions: List[Coin]
    removals: List[Coin]
    program: SerializedProgram

    def __lt__(self, other):
        return self.fee_per_cost < other.fee_per_cost

    @property
    def fee_per_cost(self) -> float:
        return int(self.fee) / int(self.cost)

    @property
    def name(self) -> bytes32:
        return self.spend_bundle_name
