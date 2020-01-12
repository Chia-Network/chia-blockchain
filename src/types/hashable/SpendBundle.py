from typing import List
from src.util.streamable import Streamable, streamable
from .BLSSignature import BLSSignature
from .CoinSolution import CoinSolution


@streamable
class SpendBundle(Streamable):
    """
    This is a list of coins being spent along with their solution programs, and a single
    aggregated signature. This is the object that most closely corresponds to a bitcoin
    transaction (although because of non-interactive signature aggregation, the boundaries
    between transactions are more flexible than in bitcoin).
    """
    coin_solutions: List[CoinSolution]
    aggregated_signature: BLSSignature

    @classmethod
    def aggregate(cls, spend_bundles):
        coin_solutions = []
        sigs = []
        for _ in spend_bundles:
            coin_solutions += _.coin_solutions
            sigs.append(_.aggregated_signature)
        aggregated_signature = BLSSignature.aggregate(sigs)
        return cls(coin_solutions, aggregated_signature)

    def additions(self):
        from chiasim.wallet.deltas import additions_for_solution
        items = []
        for coin_solution in self.coin_solutions:
            items += additions_for_solution(coin_solution.coin.name(), coin_solution.solution)
        return tuple(items)

    def removals(self):
        return tuple(_.coin for _ in self.coin_solutions)

    def fees(self) -> int:
        amount_in = sum(_.amount for _ in self.removals())
        amount_out = sum(_.amount for _ in self.additions())
        return amount_in - amount_out
