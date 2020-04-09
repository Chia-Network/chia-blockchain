from dataclasses import dataclass
from typing import List

from src.types.coin import Coin
from src.types.sized_bytes import bytes32
from src.util.chain_utils import additions_for_solution
from src.util.streamable import Streamable, streamable
from .BLSSignature import BLSSignature
from .coin_solution import CoinSolution


@dataclass(frozen=True)
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
        coin_solutions: List[CoinSolution] = []
        sigs = []
        for _ in spend_bundles:
            coin_solutions += _.coin_solutions
            sigs.append(_.aggregated_signature)
        aggregated_signature = BLSSignature.aggregate(sigs)
        return cls(coin_solutions, aggregated_signature)

    def additions(self) -> List[Coin]:
        items: List[Coin] = []
        for coin_solution in self.coin_solutions:
            items.extend(
                additions_for_solution(
                    coin_solution.coin.name(), coin_solution.solution
                )
            )
        return items

    def removals(self) -> List[Coin]:
        """ This should be used only by wallet"""
        return [_.coin for _ in self.coin_solutions]

    def fees(self) -> int:
        """ Unsafe to use for fees validation!!! """
        amount_in = sum(_.amount for _ in self.removals())
        amount_out = sum(_.amount for _ in self.additions())

        return amount_in - amount_out

    def removal_names(self) -> List[bytes32]:
        return [_.coin.name() for _ in self.coin_solutions]

    def name(self) -> bytes32:
        return self.get_hash()
