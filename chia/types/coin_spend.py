from __future__ import annotations

from dataclasses import dataclass
from typing import List

from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import INFINITE_COST, SerializedProgram
from chia.util.chain_utils import additions_for_solution, fee_for_solution
from chia.util.streamable import Streamable, streamable


@streamable
@dataclass(frozen=True)
class CoinSpend(Streamable):
    """
    This is a rather disparate data structure that validates coin transfers. It's generally populated
    with data from different sources, since burned coins are identified by name, so it is built up
    more often that it is streamed.
    """

    coin: Coin
    puzzle_reveal: SerializedProgram
    solution: SerializedProgram

    # TODO: this function should be moved out of the full node. It cannot be
    # called on untrusted input
    def additions(self) -> List[Coin]:
        return additions_for_solution(self.coin.name(), self.puzzle_reveal, self.solution, INFINITE_COST)

    # TODO: this function should be moved out of the full node. It cannot be
    # called on untrusted input
    def reserved_fee(self) -> int:
        return fee_for_solution(self.puzzle_reveal, self.solution, INFINITE_COST)
