from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from chia.consensus.cost_calculator import NPCResult
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.spend_bundle import SpendBundle
from chia.util.generator_tools import additions_for_npc
from chia.util.ints import uint32, uint64
from chia.util.streamable import Streamable, streamable


@streamable
@dataclass(frozen=True)
class MempoolItem(Streamable):
    spend_bundle: SpendBundle
    fee: uint64
    npc_result: NPCResult
    spend_bundle_name: bytes32
    height_added_to_mempool: uint32

    # If present, this SpendBundle is not valid at or before this height
    assert_height: Optional[uint32] = None

    def __lt__(self, other: MempoolItem) -> bool:
        return self.fee_per_cost < other.fee_per_cost

    @property
    def fee_per_cost(self) -> float:
        return int(self.fee) / int(self.cost)

    @property
    def name(self) -> bytes32:
        return self.spend_bundle_name

    @property
    def cost(self) -> uint64:
        assert self.npc_result.conds is not None
        return uint64(self.npc_result.conds.cost)

    @property
    def additions(self) -> List[Coin]:
        return additions_for_npc(self.npc_result)

    @property
    def removals(self) -> List[Coin]:
        return self.spend_bundle.removals()
