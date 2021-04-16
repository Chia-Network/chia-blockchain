from dataclasses import dataclass
from typing import List

from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program, INFINITE_COST
from chia.util.chain_utils import additions_for_solution
from chia.util.streamable import Streamable, streamable


@dataclass(frozen=True)
@streamable
class CoinSolution(Streamable):
    """
    This is a rather disparate data structure that validates coin transfers. It's generally populated
    with data from different sources, since burned coins are identified by name, so it is built up
    more often that it is streamed.
    """

    coin: Coin
    puzzle_reveal: Program
    solution: Program

    def additions(self) -> List[Coin]:
        return additions_for_solution(self.coin.name(), self.puzzle_reveal, self.solution, INFINITE_COST)
