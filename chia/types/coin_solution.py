from dataclasses import dataclass
from typing import List

from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program
from chia.util.chain_utils import additions_for_solution, announcements_for_solution, announcement_names_for_solution
from chia.util.streamable import Streamable, streamable
from chia.types.blockchain_format.sized_bytes import bytes32
from .announcement import Announcement


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
        return additions_for_solution(self.coin.name(), self.puzzle_reveal, self.solution)

    def announcements(self) -> List[Announcement]:
        return announcements_for_solution(self.coin, self.puzzle_reveal, self.solution)

    def announcement_names(self) -> List[bytes32]:
        return announcement_names_for_solution(self.coin, self.puzzle_reveal, self.solution)
