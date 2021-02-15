from typing import List

from dataclasses import dataclass

from src.types.blockchain_format.coin import Coin
from src.types.blockchain_format.program import Program
from .announcement import Announcement
from src.util.chain_utils import additions_for_solution, announcements_for_solution
from src.util.streamable import Streamable, streamable


@dataclass(frozen=True)
@streamable
class CoinSolution(Streamable):
    """
    This is a rather disparate data structure that validates coin transfers. It's generally populated
    with data from different sources, since burned coins are identified by name, so it is built up
    more often that it is streamed.
    """

    coin: Coin
    solution: Program

    def additions(self) -> List[Coin]:
        return additions_for_solution(self.coin.name(), self.solution)

    def announcements(self) -> List[Announcement]:
        return announcements_for_solution(self.coin.name(), self.solution)
