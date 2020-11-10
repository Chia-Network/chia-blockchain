from src.types.program import Program
from .coin import Coin


class CoinWithPuzzle(Coin):
    """
    This is a coin with its puzzle hash resolved.
    CoinWithPuzzle is used by the command line tool "chia tx"
    NOTE: By the time that this struct is used, the value of the puzzle is TRUSTED
    """

    puzzle: Program

    def __init__(self, coin: Coin, puzzle: Program):
        self.puzzle = puzzle
        super(Coin, self).__init__(coin)
