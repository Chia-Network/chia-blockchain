from dataclasses import dataclass

from .coin import Coin
from .program import Program
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
