from .Coin import Coin
from .Program import Program
from src.util.streamable import Streamable, streamable

@streamable
class CoinSolution(Streamable):
    """
    This is a rather disparate data structure that validates coin transfers. It's generally populated
    with data from different sources, since burned coins are identified by name, so it is built up
    more often that it is streamed.
    """
    coin: Coin
    solution: Program
'''
    def conditions(self):
        # TODO: this (and the ones below) are in the wrong spot. Fix them
        from chiasim.validation.consensus import conditions_for_puzzle_hash_solution
        return conditions_for_puzzle_hash_solution(self.coin.puzzle_hash, self.solution)

    def conditions_dict(self):
        from chiasim.validation.Conditions import conditions_by_opcode
        return conditions_by_opcode(self.conditions())

    def additions(self):
        from chiasim.validation.consensus import created_outputs_for_conditions_dict
        return created_outputs_for_conditions_dict(self.conditions_dict(), self.coin.name())
'''